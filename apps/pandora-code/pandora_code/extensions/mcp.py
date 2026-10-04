"""MCP-Client (Model Context Protocol): Werkzeuge externer Server einbinden.

Unterstützt stdio-Server ("command"/"args"/"env") und Streamable-HTTP-Server ("url"/"headers").
Konfiguration in .mcp.json oder settings.json:
  {"mcpServers": {"name": {"command": "npx", "args": ["-y", "server-paket"], "env": {"KEY": "${KEY}"}}}}
Die Werkzeuge heißen mcp__<server>__<werkzeug>; nur solche mit readOnlyHint laufen ohne Rückfrage.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from pathlib import Path

from .. import __version__
from ..tools import Tool, ToolContext, ToolError, clip

PROTOCOL_VERSION = "2025-03-26"
INIT_TIMEOUT = 30
LIST_TIMEOUT = 30
CALL_TIMEOUT = 120
CONNECT_DEADLINE = 60  # Gesamtzeit für das parallele Verbinden aller Server


class McpError(Exception):
    """Fehler bei Verbindung oder Aufruf eines MCP-Servers."""


def _error_text(error: object) -> str:
    if isinstance(error, dict):
        return str(error.get("message") or error)
    return str(error)


def expand(value: object) -> str:
    """Ersetzt $VAR und ${VAR} aus der Umgebung (z. B. für API-Schlüssel, die nicht in der Datei stehen sollen)."""
    return os.path.expandvars(str(value))


def resolve_command(command: str, cwd: Path) -> str:
    if os.sep in command or "/" in command:
        path = Path(command).expanduser()
        path = path if path.is_absolute() else cwd / path
        if path.exists():
            return str(path)
    else:
        found = shutil.which(command)  # findet unter Windows auch npx.cmd
        if found:
            return found
    raise McpError(f"Befehl nicht gefunden: {command}")


class _Slot:
    def __init__(self) -> None:
        self.event = threading.Event()
        self.result: object = None
        self.error: object = None


class StdioTransport:
    """JSON-RPC über stdin/stdout eines Kindprozesses (eine JSON-Nachricht pro Zeile)."""

    def __init__(self, command: str, args: list[str], env: dict[str, str], cwd: Path) -> None:
        exe = resolve_command(command, cwd)
        self._lock = threading.Lock()
        self._pending: dict[int, _Slot] = {}
        self._next_id = 0
        self.closed = False
        self.stderr_tail: deque[str] = deque(maxlen=30)
        try:
            self.proc = subprocess.Popen(
                [exe, *args], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace", bufsize=1, cwd=cwd, env={**os.environ, **env},
            )
        except OSError as err:
            raise McpError(f"Start fehlgeschlagen: {err}") from None
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()

    def _read_stderr(self) -> None:
        for line in self.proc.stderr:
            self.stderr_tail.append(line.rstrip())

    def _read_stdout(self) -> None:
        try:
            for line in self.proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    message = json.loads(line)
                except ValueError:
                    continue  # Server, die Logs auf stdout schreiben
                if isinstance(message, dict):
                    self._dispatch(message)
        finally:
            self._fail_all()

    def _dispatch(self, message: dict) -> None:
        if "method" in message:
            if "id" in message:  # Anfrage des Servers an uns
                if message["method"] == "ping":
                    self._send({"jsonrpc": "2.0", "id": message["id"], "result": {}})
                else:
                    self._send({"jsonrpc": "2.0", "id": message["id"],
                                "error": {"code": -32601, "message": "Methode nicht unterstützt"}})
            return
        with self._lock:
            slot = self._pending.pop(message.get("id"), None)
        if slot:
            if "error" in message:
                slot.error = message["error"]
            else:
                slot.result = message.get("result")
            slot.event.set()

    def _fail_all(self) -> None:
        with self._lock:
            self.closed = True
            slots, self._pending = list(self._pending.values()), {}
        tail = " | ".join(list(self.stderr_tail)[-3:])
        for slot in slots:
            slot.error = {"message": "Server beendet" + (f" ({tail})" if tail else "")}
            slot.event.set()

    def _send(self, message: dict) -> None:
        try:
            self.proc.stdin.write(json.dumps(message) + "\n")
            self.proc.stdin.flush()
        except (OSError, ValueError):
            raise McpError("Server nicht erreichbar (Pipe geschlossen)") from None

    def request(self, method: str, params: dict | None = None, timeout: float = 60):
        slot = _Slot()
        with self._lock:
            if self.closed:
                raise McpError("Server beendet")
            self._next_id += 1
            request_id = self._next_id
            self._pending[request_id] = slot
        self._send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}})
        if not slot.event.wait(timeout):
            with self._lock:
                self._pending.pop(request_id, None)
            raise McpError(f"Zeitüberschreitung bei {method} ({timeout:.0f}s)")
        if slot.error is not None:
            raise McpError(_error_text(slot.error))
        return slot.result

    def notify(self, method: str, params: dict | None = None) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def close(self) -> None:
        try:
            self.proc.stdin.close()
        except (OSError, ValueError):
            pass
        self.proc.terminate()
        try:
            self.proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.proc.kill()


class HttpTransport:
    """Streamable HTTP: jede Nachricht ist ein POST; die Antwort ist JSON oder ein SSE-Strom."""

    def __init__(self, url: str, headers: dict[str, str] | None = None) -> None:
        self.url = url
        self.headers = dict(headers or {})
        self.session: str | None = None
        self.protocol: str | None = None
        self._lock = threading.Lock()
        self._next_id = 0

    def _post(self, body: dict, timeout: float):
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream", **self.headers}
        if self.session:
            headers["Mcp-Session-Id"] = self.session
        if self.protocol:
            headers["MCP-Protocol-Version"] = self.protocol
        request = urllib.request.Request(self.url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
        try:
            response = urllib.request.urlopen(request, timeout=timeout)
        except urllib.error.HTTPError as err:
            raise McpError(f"HTTP {err.code}: {err.read()[:200].decode('utf-8', 'replace')}") from None
        except (urllib.error.URLError, OSError) as err:
            raise McpError(f"Server nicht erreichbar: {getattr(err, 'reason', err)}") from None
        self.session = response.headers.get("Mcp-Session-Id") or self.session
        return response

    @staticmethod
    def _read_sse(response, request_id: int) -> dict:
        data: list[str] = []
        for raw in response:
            line = raw.decode("utf-8", "replace").rstrip("\r\n")
            if line.startswith("data:"):
                data.append(line[5:].lstrip())
            elif not line and data:
                try:
                    message = json.loads("\n".join(data))
                except ValueError:
                    message = None
                data = []
                if isinstance(message, dict) and message.get("id") == request_id and ("result" in message or "error" in message):
                    return message
        raise McpError("Antwort-Strom endete ohne Ergebnis")

    def request(self, method: str, params: dict | None = None, timeout: float = 60):
        with self._lock:
            self._next_id += 1
            request_id = self._next_id
        body = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}}
        with self._post(body, timeout) as response:
            if "text/event-stream" in response.headers.get("Content-Type", ""):
                message = self._read_sse(response, request_id)
            else:
                try:
                    message = json.loads(response.read().decode("utf-8"))
                except ValueError:
                    raise McpError("Ungültige JSON-Antwort") from None
        if isinstance(message, list):  # Batch-Antwort
            message = next((m for m in message if isinstance(m, dict) and m.get("id") == request_id), {})
        if not isinstance(message, dict):
            raise McpError("Unerwartete Antwort")
        if "error" in message:
            raise McpError(_error_text(message["error"]))
        return message.get("result")

    def notify(self, method: str, params: dict | None = None) -> None:
        with self._post({"jsonrpc": "2.0", "method": method, "params": params or {}}, 30) as response:
            response.read()

    def close(self) -> None:
        if not self.session:
            return
        request = urllib.request.Request(self.url, headers={**self.headers, "Mcp-Session-Id": self.session}, method="DELETE")
        try:
            urllib.request.urlopen(request, timeout=5).close()
        except (urllib.error.URLError, OSError):
            pass


class McpServer:
    def __init__(self, name: str, config: dict, cwd: Path) -> None:
        self.name = name
        self.config = config
        self.cwd = cwd
        self.transport: StdioTransport | HttpTransport | None = None
        self.tool_specs: list[dict] = []
        self.error: str | None = None
        self.connected = False

    @property
    def kind(self) -> str:
        return "http" if self.config.get("url") else "stdio"

    def connect(self) -> None:
        config = self.config
        if config.get("url"):
            headers = {str(k): expand(v) for k, v in (config.get("headers") or {}).items()}
            transport: StdioTransport | HttpTransport = HttpTransport(expand(config["url"]), headers)
        elif config.get("command"):
            args = [expand(a) for a in config.get("args") or []]
            env = {str(k): expand(v) for k, v in (config.get("env") or {}).items()}
            transport = StdioTransport(expand(config["command"]), args, env, self.cwd)
        else:
            raise McpError("weder 'command' noch 'url' angegeben")
        self.transport = transport
        try:
            init = transport.request(
                "initialize",
                {"protocolVersion": PROTOCOL_VERSION, "capabilities": {},
                 "clientInfo": {"name": "pandora-code", "version": __version__}},
                timeout=INIT_TIMEOUT,
            )
            if isinstance(transport, HttpTransport) and isinstance(init, dict):
                transport.protocol = init.get("protocolVersion")
            transport.notify("notifications/initialized")
            self.tool_specs = self._list_tools(transport)
            self.connected = True
        except Exception:
            transport.close()
            raise

    @staticmethod
    def _list_tools(transport) -> list[dict]:
        specs: list[dict] = []
        cursor = None
        for _ in range(20):  # Seitenlimit gegen Endlosschleifen
            result = transport.request("tools/list", {"cursor": cursor} if cursor else {}, timeout=LIST_TIMEOUT) or {}
            specs += [s for s in result.get("tools", []) if isinstance(s, dict) and s.get("name")]
            cursor = result.get("nextCursor")
            if not cursor:
                break
        return specs

    def call(self, tool: str, args: dict) -> dict:
        if self.transport is None:
            raise McpError("nicht verbunden")
        result = self.transport.request("tools/call", {"name": tool, "arguments": args}, timeout=CALL_TIMEOUT)
        return result if isinstance(result, dict) else {}

    def close(self) -> None:
        if self.transport is not None:
            self.transport.close()


def safe_name(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", text)


def format_result(ctx: ToolContext, result: dict) -> str:
    parts: list[str] = []
    for item in result.get("content") or []:
        if not isinstance(item, dict):
            continue
        kind = item.get("type")
        if kind == "text":
            parts.append(str(item.get("text", "")))
        elif kind == "image" and item.get("data"):
            ctx.pending_images.append(str(item["data"]))
            parts.append("[Bild vom MCP-Server – wird dem Modell als nächste Nachricht angehängt]")
        elif kind == "resource" and isinstance(item.get("resource"), dict):
            resource = item["resource"]
            parts.append(str(resource.get("text") or f"[Ressource {resource.get('uri', '?')}]"))
        else:
            parts.append(json.dumps(item, ensure_ascii=False))
    if not parts and result.get("structuredContent") is not None:
        parts.append(json.dumps(result["structuredContent"], ensure_ascii=False))
    text = clip("\n".join(parts).strip() or "(keine Ausgabe)")
    if result.get("isError"):
        raise ToolError(text)
    return text


def make_tool(server: McpServer, spec: dict) -> Tool:
    name = f"mcp__{safe_name(server.name)}__{safe_name(spec['name'])}"[:64]
    parameters = spec.get("inputSchema") if isinstance(spec.get("inputSchema"), dict) else {}
    parameters = {"type": "object", "properties": {}, **parameters}
    read_only = (spec.get("annotations") or {}).get("readOnlyHint") is True
    remote_name = spec["name"]

    def run(ctx: ToolContext, args: dict) -> str:
        try:
            return format_result(ctx, server.call(remote_name, args))
        except McpError as err:
            raise ToolError(f"MCP-Server '{server.name}': {err}") from None

    def preview(ctx: ToolContext, args: dict) -> str:
        return f"MCP {server.name} → {remote_name}\n{json.dumps(args, ensure_ascii=False, indent=2)[:800]}"

    description = f"[MCP {server.name}] {spec.get('description') or remote_name}"[:1000]
    return Tool(name, description, parameters, run, mutating=not read_only, preview=preview)


def _connect(server: McpServer) -> None:
    try:
        server.connect()
    except Exception as err:
        server.error = f"{type(err).__name__}: {err}" if not isinstance(err, McpError) else str(err)


def install(agent, settings) -> None:
    servers = [McpServer(n, c, agent.ctx.cwd) for n, c in settings.mcp_servers.items()]
    agent.mcp_servers = servers
    if not servers:
        return
    threads = [threading.Thread(target=_connect, args=(s,), daemon=True) for s in servers]
    for thread in threads:
        thread.start()
    deadline = time.monotonic() + CONNECT_DEADLINE
    for server, thread in zip(servers, threads):
        thread.join(max(deadline - time.monotonic(), 0.1))
        if thread.is_alive():
            server.error = "Zeitüberschreitung beim Verbinden"
    count = 0
    for server in servers:
        if server.error or not server.connected:
            server.error = server.error or "nicht verbunden"
            server.close()
            agent.notice(f"MCP-Server '{server.name}': {server.error}", error=True)
            continue
        agent.closers.append(server.close)
        for spec in server.tool_specs:
            agent.add_tool(make_tool(server, spec))
            count += 1
    connected = sum(1 for s in servers if s.connected and not s.error)
    if connected:
        agent.notice(f"MCP: {connected} Server verbunden, {count} Werkzeuge")

    def mcp_command(arg: str, agent, ui) -> str | None:
        lines = []
        for server in agent.mcp_servers:
            state = f"✗ {server.error}" if server.error else f"✓ {len(server.tool_specs)} Werkzeuge"
            lines.append(f"{server.name} ({server.kind}): {state}")
            lines += [f"    mcp__{safe_name(server.name)}__{safe_name(s['name'])}" for s in server.tool_specs]
        ui.info("\n".join(lines) or "Keine MCP-Server konfiguriert (.mcp.json oder ~/.pandora/mcp.json).")
        return None

    agent.register_command("mcp", mcp_command, "/mcp  MCP-Server und ihre Werkzeuge anzeigen")
