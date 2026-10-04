"""Schlanker Ollama-Client (nur Standardbibliothek): Modellliste und Chat-Streaming."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Iterator
from urllib.parse import urlparse

DEFAULT_PORT = 11434
DEFAULT_NUM_CTX = 16384  # Ollamas eigener Standard (2–4k) ist für einen Coding-Agenten zu klein


class OllamaError(RuntimeError):
    """Fehler bei der Kommunikation mit Ollama."""


PERMISSION_HINT = """Hinweis: Der Ollama-SERVER (nicht Pandora) darf sein Datenverzeichnis nicht anlegen.
Der Pfad '/usr/share/ollama' ist ein Linux-Pfad: Dieser Fehler kommt IMMER von einem Linux-Prozess – auch
wenn der Ollama-Rechner "Windows" ist, läuft Ollama dort dann in WSL oder einem Docker-Container, nicht als
natives Windows-Programm (das würde nie diesen Pfad melden).

Einfachster Fix (egal ob WSL oder Docker, kein sudo/systemd-Wissen nötig): Ollama auf ein Verzeichnis
zeigen lassen, das dem aktuellen Benutzer bereits gehört, statt das Systemverzeichnis zu reparieren:
  WSL/Linux-Terminal, in dem 'ollama serve' läuft:
    OLLAMA_MODELS=$HOME/.ollama/models ollama serve
  Docker (Container neu starten, Modelle landen dann in einem eigenen Docker-Volume statt im Image):
    docker run -d --name ollama -p 11434:11434 -v ollama_data:/root/.ollama ollama/ollama

Alternative, falls 'ollama' dort als Systemdienst läuft UND systemd vorhanden ist (in WSL meist nicht
aktiviert – dann bitte die Zeile mit 'systemctl' einfach weglassen und stattdessen obigen Fix nutzen):
  sudo mkdir -p /usr/share/ollama/.ollama/models
  sudo chown -R ollama:ollama /usr/share/ollama
  sudo systemctl restart ollama

Außerdem: Pandora Code nicht mit 'sudo' starten. Diagnose: pandora code --doctor"""


def explain_error(message: str) -> str:
    """Hängt bei bekannten Server-Fehlern eine konkrete Lösung an die Ollama-Meldung an."""
    lower = message.lower()
    if "permission denied" in lower and any(k in lower for k in ("mkdir", "/usr/share/ollama", ".ollama", "models")):
        return f"{message}\n{PERMISSION_HINT}"
    return message


def normalize_host(host: str | None = None) -> str:
    host = (host or os.environ.get("OLLAMA_HOST") or f"127.0.0.1:{DEFAULT_PORT}").strip()
    if "://" not in host:
        host = "http://" + host
    parsed = urlparse(host)
    netloc = parsed.netloc.replace("0.0.0.0", "127.0.0.1")
    if parsed.port is None:
        netloc += f":{DEFAULT_PORT}"
    return f"{parsed.scheme}://{netloc}"


class OllamaClient:
    def __init__(self, host: str | None = None, num_ctx: int | None = None, timeout: int = 600) -> None:
        self.host = normalize_host(host)
        self.num_ctx = int(num_ctx or os.environ.get("PANDORA_NUM_CTX") or DEFAULT_NUM_CTX)
        self.timeout = timeout

    def _open(self, path: str, payload: dict | None = None):
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            self.host + path,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST" if data is not None else "GET",
        )
        try:
            return urllib.request.urlopen(request, timeout=self.timeout)
        except urllib.error.HTTPError as err:
            body = err.read().decode("utf-8", "replace")
            try:
                message = json.loads(body).get("error", body)
            except (ValueError, AttributeError):
                message = body
            raise OllamaError(explain_error(f"Ollama-Fehler {err.code}: {message}")) from None
        except (urllib.error.URLError, OSError) as err:
            reason = getattr(err, "reason", err)
            raise OllamaError(
                f"Ollama unter {self.host} nicht erreichbar ({reason}). Läuft 'ollama serve'?"
            ) from None

    def list_models(self) -> list[str]:
        with self._open("/api/tags") as response:
            data = json.load(response)
        return [m["name"] for m in data.get("models", [])]

    def chat_stream(self, model: str, messages: list[dict], tools: list[dict] | None = None) -> Iterator[dict]:
        payload: dict = {
            "model": model,
            "messages": messages,
            "stream": True,
            "options": {"num_ctx": self.num_ctx},
        }
        if tools:
            payload["tools"] = tools
        with self._open("/api/chat", payload) as response:
            for raw in response:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    chunk = json.loads(raw)
                except ValueError:
                    continue
                if "error" in chunk:
                    raise OllamaError(explain_error(f"Ollama-Fehler: {chunk['error']}"))
                yield chunk

    def embed(self, model: str, texts: list[str]) -> list[list[float]]:
        """Embedding-Vektoren für `texts` über das lokale Ollama (für das Vektor-RAG, context/vector_store.py).

        Nutzt zuerst die gebündelte Route `/api/embed` (Ollama ≥ 0.1.26, mehrere Texte pro Anfrage); ist die
        auf einem älteren Ollama nicht vorhanden (404), wird automatisch auf die ältere Einzel-Text-Route
        `/api/embeddings` ausgewichen.
        """
        if not texts:
            return []
        try:
            with self._open("/api/embed", {"model": model, "input": texts}) as response:
                data = json.load(response)
            embeddings = data.get("embeddings")
            if embeddings is not None:
                return embeddings
        except OllamaError as err:
            if "404" not in str(err):
                raise
        out: list[list[float]] = []
        for text in texts:
            with self._open("/api/embeddings", {"model": model, "prompt": text}) as response:
                data = json.load(response)
            vector = data.get("embedding")
            if vector is None:
                raise OllamaError(f"Ollama-Antwort ohne 'embedding'/'embeddings' für Modell '{model}'.")
            out.append(vector)
        return out
