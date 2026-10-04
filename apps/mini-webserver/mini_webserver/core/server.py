"""Webserver-Steuerung: liefert einen Ordner per HTTP aus.

Verhält sich wie `python -m http.server <port>`, läuft aber im Programm selbst.
Dadurch braucht die fertige .exe kein installiertes Python.
"""
from __future__ import annotations

import errno
import http.client
import json
import os
import ssl
import sys
import threading
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, List, Optional
from urllib.parse import urlsplit

from .certs import CertPaths

LogFn = Callable[[str], None]

_ADDR_IN_USE = {errno.EADDRINUSE, 98, 48, 10048}
_NO_PERMISSION = {errno.EACCES, 13, 10013}

CA_URL = "/mini-webserver-ca.crt"        # hier lädt das Handy das CA-Zertifikat herunter
PROXY_PREFIX = "/api"                    # alles darunter geht an Ollama
_FORWARD_HEADERS = ("Content-Type", "Accept", "Authorization")


class ServerError(Exception):
    """Fehler mit einer Meldung, die direkt angezeigt werden kann."""


def validate_port(value) -> int:
    try:
        port = int(str(value).strip())
    except ValueError:
        raise ServerError("Der Port muss eine Zahl sein.") from None
    if not 1 <= port <= 65535:
        raise ServerError("Der Port muss zwischen 1 und 65535 liegen.")
    return port


def validate_folder(path) -> str:
    text = str(path or "").strip()
    if not text:
        raise ServerError("Bitte zuerst einen Ordner wählen.")
    folder = os.path.abspath(os.path.expanduser(text))
    if not os.path.isdir(folder):
        raise ServerError("Der Ordner existiert nicht: " + folder)
    return folder


def validate_upstream(value) -> str:
    """Prüft die Ollama-Adresse für die Weiterleitung. Leer heißt: keine Weiterleitung."""
    text = str(value or "").strip()
    if not text:
        return ""
    if "://" not in text:
        text = "http://" + text
    parts = urlsplit(text)
    if parts.scheme != "http":
        raise ServerError("Die Ollama-Adresse muss mit http:// beginnen (Ollama spricht ohne Verschlüsselung).")
    try:
        port = parts.port
    except ValueError:
        raise ServerError("Der Port in der Ollama-Adresse ist ungültig.") from None
    if not parts.hostname:
        raise ServerError("Die Ollama-Adresse ist unvollständig. Beispiel: http://127.0.0.1:11434")
    host = "[%s]" % parts.hostname if ":" in parts.hostname else parts.hostname
    return "http://%s:%d" % (host, port or 11434)


def list_html(folder: str) -> List[str]:
    """HTML-Dateien direkt im Ordner, alphabetisch."""
    try:
        names = os.listdir(folder)
    except OSError:
        return []
    return sorted(n for n in names
                  if n.lower().endswith((".html", ".htm")) and os.path.isfile(os.path.join(folder, n)))


def suggest_page(folder: str) -> str:
    """Dateiname für die Adresse: leer, wenn eine index-Datei existiert, sonst die erste HTML-Datei."""
    files = list_html(folder)
    if not files or any(f.lower() in ("index.html", "index.htm") for f in files):
        return ""
    return files[0]


def friendly_os_error(exc: OSError, port: int) -> str:
    code = getattr(exc, "winerror", None) or exc.errno
    if code in _ADDR_IN_USE or exc.errno in _ADDR_IN_USE:
        return "Port %d ist schon belegt. Wähle einen anderen Port oder beende das andere Programm." % port
    if code in _NO_PERMISSION or exc.errno in _NO_PERMISSION:
        return "Keine Berechtigung für Port %d. Nimm einen Port über 1024." % port
    return "Der Server konnte nicht starten: %s" % exc


def _make_handler(directory: str, log: LogFn, upstream: str = "", ca_path: str = ""):
    target = urlsplit(upstream) if upstream else None

    class Handler(SimpleHTTPRequestHandler):
        timeout = 60  # hängende Verbindungen (zum Beispiel abgebrochener TLS-Start) räumen sich selbst auf

        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=directory, **kwargs)

        def end_headers(self):
            # Beim Bearbeiten der Seite soll das Handy immer die neueste Version laden.
            self.send_header("Cache-Control", "no-cache")
            super().end_headers()

        def log_message(self, format, *args):  # noqa: A002 (Signatur der Basisklasse)
            log("%s  %s" % (self.address_string(), format % args))

        # ---------- Sonderwege ----------
        def _special(self) -> bool:
            """Beantwortet CA-Download und Ollama-Weiterleitung. True, wenn die Anfrage erledigt ist."""
            path = self.path.split("?", 1)[0]
            if ca_path and path == CA_URL and self.command in ("GET", "HEAD"):
                self._send_ca()
                return True
            if target is not None and (path == PROXY_PREFIX or path.startswith(PROXY_PREFIX + "/")):
                self._proxy()
                return True
            return False

        def _send_ca(self):
            try:
                with open(ca_path, "rb") as handle:
                    data = handle.read()
            except OSError:
                self.send_error(HTTPStatus.NOT_FOUND, "CA-Zertifikat nicht gefunden")
                return
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/x-x509-ca-cert")
            self.send_header("Content-Disposition", 'attachment; filename="mini-webserver-ca.crt"')
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(data)

        def _json_error(self, status: HTTPStatus, message: str):
            body = json.dumps({"error": message}, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _proxy(self):
            """Reicht die Anfrage unverändert an Ollama weiter und streamt die Antwort zurück.

            Origin, Referer und Host werden bewusst nicht weitergegeben. Sonst lehnt Ollama
            Anfragen von fremden Herkunftsadressen ab (OLLAMA_ORIGINS).
            """
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = 0
            body = self.rfile.read(length) if length > 0 else None
            headers = {name: self.headers[name] for name in _FORWARD_HEADERS if self.headers.get(name)}
            conn = http.client.HTTPConnection(target.hostname, target.port or 11434, timeout=600)
            try:
                try:
                    conn.request(self.command, self.path, body=body, headers=headers)
                    resp = conn.getresponse()
                except (OSError, http.client.HTTPException) as exc:
                    self._json_error(HTTPStatus.BAD_GATEWAY,
                                     "Ollama unter %s ist nicht erreichbar (%s)." % (upstream, exc))
                    log("Ollama nicht erreichbar: %s" % exc)
                    return
                self.send_response(resp.status)
                content_type = resp.getheader("Content-Type")
                if content_type:
                    self.send_header("Content-Type", content_type)
                self.end_headers()
                if self.command == "HEAD":
                    return
                while True:
                    chunk = resp.read1(8192)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    self.wfile.flush()
            finally:
                conn.close()

        # ---------- Methoden ----------
        def do_GET(self):
            if not self._special():
                super().do_GET()

        def do_HEAD(self):
            if not self._special():
                super().do_HEAD()

        def _other(self):
            if not self._special():
                self.send_error(HTTPStatus.NOT_IMPLEMENTED, "Unsupported method (%r)" % self.command)

        do_POST = do_PUT = do_DELETE = _other

    return Handler


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    # Unter Windows würde SO_REUSEADDR einen doppelt belegten Port verschleiern.
    allow_reuse_address = os.name != "nt"

    def __init__(self, address, handler, log: LogFn, tls: Optional[ssl.SSLContext] = None):
        self._log = log
        self._tls = tls
        self._tls_hint_shown = False
        super().__init__(address, handler)

    def get_request(self):
        sock, addr = self.socket.accept()
        if self._tls is not None:
            # Der Handshake läuft erst im Thread der Verbindung, so blockiert ein
            # unfertiger Verbindungsaufbau nie die Annahme weiterer Verbindungen.
            sock = self._tls.wrap_socket(sock, server_side=True, do_handshake_on_connect=False)
        return sock, addr

    def handle_error(self, request, client_address):
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionError, TimeoutError)):
            return  # Handy hat die Verbindung einfach geschlossen
        if isinstance(exc, ssl.SSLError):
            if not self._tls_hint_shown:
                self._tls_hint_shown = True
                self._log("%s  TLS-Verbindung nicht zustande gekommen (%s). Der Browser muss das Zertifikat "
                          "bestätigen, oder die Adresse wurde mit http:// statt https:// geöffnet."
                          % (client_address[0], getattr(exc, "reason", None) or exc))
            return
        self._log("%s  Fehler: %s" % (client_address[0], exc))


def make_tls_context(paths: CertPaths) -> ssl.SSLContext:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    try:
        context.load_cert_chain(paths.cert, paths.key)
    except (OSError, ssl.SSLError) as exc:
        raise ServerError("Das Zertifikat konnte nicht geladen werden: %s" % exc) from exc
    return context


class ServerController:
    """Startet und stoppt den Webserver. Kennt keine Oberfläche."""

    def __init__(self, log: Optional[LogFn] = None):
        self._log: LogFn = log or (lambda message: None)
        self._httpd: Optional[_Server] = None
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self.folder = ""
        self.port = 0
        self.https = False
        self.upstream = ""

    @property
    def running(self) -> bool:
        return self._httpd is not None

    def start(self, folder, port, tls: Optional[CertPaths] = None, upstream="") -> None:
        """Startet den Server. Mit `tls` läuft er über HTTPS, mit `upstream` leitet er /api an Ollama weiter."""
        with self._lock:
            if self._httpd is not None:
                raise ServerError("Der Server läuft bereits.")
            folder_path = validate_folder(folder)
            port_number = validate_port(port)
            upstream_url = validate_upstream(upstream)
            context = make_tls_context(tls) if tls is not None else None
            handler = _make_handler(folder_path, self._log, upstream_url, tls.ca_cert if tls is not None else "")
            try:
                httpd = _Server(("0.0.0.0", port_number), handler, self._log, context)
            except OSError as exc:
                raise ServerError(friendly_os_error(exc, port_number)) from exc
            thread = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.2},
                                      name="http-server", daemon=True)
            thread.start()
            self._httpd, self._thread = httpd, thread
            self.folder, self.port = folder_path, port_number
            self.https, self.upstream = context is not None, upstream_url
        self._log("Server gestartet (%s). Ordner: %s, Port: %d" % ("HTTPS" if self.https else "HTTP", folder_path, port_number))
        if self.upstream:
            self._log("Ollama-Weiterleitung: %s/... geht an %s" % (PROXY_PREFIX, self.upstream))
        if not list_html(folder_path):
            self._log("Hinweis: In diesem Ordner liegt keine HTML-Datei.")

    def stop(self) -> bool:
        with self._lock:
            httpd, thread = self._httpd, self._thread
            self._httpd = self._thread = None
        if httpd is None:
            return False
        httpd.shutdown()
        httpd.server_close()
        if thread is not None:
            thread.join(timeout=3)
        self._log("Server gestoppt.")
        return True
