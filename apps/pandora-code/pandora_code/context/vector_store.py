"""Lokales Vektor-RAG: findet bei großen Repositories nur die semantisch relevanten Codeblöcke, statt das
Kontextfenster des Ollama-Modells mit ganzen Dateien zu überlasten.

Zwei Embedding-Backends, automatisch gewählt (immer lokal, kein Cloud-Dienst):
- **Ollama-Embeddings** (`OllamaClient.embed`, `/api/embed`): echte semantische Nähe, sofern ein
  Embedding-Modell installiert ist (z. B. `ollama pull nomic-embed-text`, ~270 MB). Wird automatisch erkannt.
- **Hashing-Fallback** (reine Python-Standardbibliothek, keine Installation nötig): Feature-Hashing über
  Wort-Tokens auf einen festen Vektorraum – eine lexikalische Näherung, die ohne jedes Zusatzpaket und ohne
  Embedding-Modell funktioniert, damit die Suche auch "out of the box" nutzbar ist.

Statt einer vollwertigen Vektordatenbank (ChromaDB/Qdrant) genügt für ein einzelnes lokales Repository ein
schlanker, selbst geschriebener Index: eine JSON-Datei unter `.pandora/vector_index.json` mit einem Vektor
pro Codeblock, linear per Kosinus-Ähnlichkeit durchsucht (mit `numpy` beschleunigt, falls vorhanden – sonst
reines Python). Das bleibt auf Repository-Größen, wie sie auf einem Raspberry Pi 4B bearbeitet werden,
schnell genug und braucht keinen zusätzlichen Serverprozess.
"""
from __future__ import annotations

import ast
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from ..ollama_client import OllamaClient, OllamaError

try:
    import numpy as _np  # type: ignore
except Exception:  # pragma: no cover - numpy ist optional, reines Python funktioniert genauso
    _np = None

INDEX_FILE = ".pandora/vector_index.json"
INDEX_VERSION = 1
MAX_CHUNKS = 6000  # Sicherung gegen Ausufern in Monorepos auf schwacher Hardware (Pi 4B)
MAX_FILE_BYTES = 1_500_000
HASH_DIMS = 256  # Vektorbreite des Fallback-Backends
CHUNK_LINES = 40  # Fenstergröße für nicht-Python-Dateien (Zeilen)
CHUNK_OVERLAP = 8
EMBED_BATCH = 32  # Texte pro Ollama-Anfrage

EXCLUDE_DIRS = {
    ".git", "__pycache__", "node_modules", "venv", ".venv", "env", "dist", "build", ".mypy_cache",
    ".pytest_cache", ".idea", ".vscode", "site-packages", "vendor", "target", ".tox", ".ruff_cache",
}
SOURCE_EXTENSIONS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".c", ".h", ".cpp", ".cc", ".hpp", ".lua", ".go", ".rs",
    ".java", ".rb", ".php", ".sh", ".md",
}
# Bekannte Ollama-Embedding-Modellfamilien (Namensteil vor ':'), zur automatischen Erkennung in `pick_embed_model`.
EMBED_FAMILIES = (
    "nomic-embed-text", "mxbai-embed-large", "all-minilm", "snowflake-arctic-embed",
    "bge-m3", "bge-large", "bge-base", "granite-embedding", "embeddinggemma",
)

_WORD = re.compile(r"[A-Za-zÄÖÜäöüß_][A-Za-zÄÖÜäöüß0-9_]{1,}")


def pick_embed_model(installed: list[str]) -> str | None:
    """Sucht unter den installierten Ollama-Modellen ein bekanntes Embedding-Modell (Hot Reload: wird bei
    jedem Aufbau neu geprüft, ein später per `ollama pull nomic-embed-text` nachgeladenes Modell greift
    also ohne Neustart)."""
    for name in installed:
        base = name.split(":", 1)[0].lower()
        if any(base == fam or base.startswith(fam) for fam in EMBED_FAMILIES):
            return name
    return None


class Embedder(Protocol):
    name: str

    def embed(self, texts: list[str]) -> list[list[float]]: ...


@dataclass
class OllamaEmbedder:
    """Echtes semantisches Embedding über ein lokal installiertes Ollama-Embedding-Modell."""
    client: OllamaClient
    model: str

    @property
    def name(self) -> str:
        return f"ollama:{self.model}"

    def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), EMBED_BATCH):
            out.extend(self.client.embed(self.model, texts[i:i + EMBED_BATCH]))
        return out


@dataclass
class HashingEmbedder:
    """Abhängigkeitsfreier Fallback: Feature-Hashing über Wort-Tokens (Bag-of-Words auf festem Vektorraum).

    Kein echtes semantisches Verständnis, aber eine brauchbare lexikalische Näherung – findet z. B.
    Codeblöcke, die dieselben Bezeichner/Wörter wie die Anfrage benutzen, komplett ohne Zusatzinstallation.
    """
    dims: int = HASH_DIMS

    @property
    def name(self) -> str:
        return f"hashing:{self.dims}"

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]

    def _vector(self, text: str) -> list[float]:
        vec = [0.0] * self.dims
        for token in _WORD.findall(text.lower()):
            idx = hash(token) % self.dims
            vec[idx] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]


def _cosine(a: list[float], b: list[float]) -> float:
    if _np is not None:
        av, bv = _np.asarray(a), _np.asarray(b)
        denom = float(_np.linalg.norm(av) * _np.linalg.norm(bv)) or 1.0
        return float(_np.dot(av, bv)) / denom
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a)) or 1.0
    norm_b = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (norm_a * norm_b)


@dataclass
class Chunk:
    file: str
    start_line: int
    end_line: int
    label: str  # z. B. Funktions-/Klassenname oder "Zeilen 1-40"
    vector: list[float]
    mtime: float


@dataclass
class SearchHit:
    file: str
    start_line: int
    end_line: int
    label: str
    score: float
    snippet: str


def _python_chunks(text: str) -> list[tuple[int, int, str]]:
    """Ein Chunk pro Top-Level-Funktion/-Klasse (mit ihren Methoden) – inhaltlich sinnvollere Grenzen als
    feste Zeilenfenster, ohne den AST-Code-Graph aus ast_graph.py als Abhängigkeit zu brauchen."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return _line_windows(text)
    lines = text.splitlines()
    chunks: list[tuple[int, int, str]] = []
    covered: list[tuple[int, int]] = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            end = getattr(node, "end_lineno", None) or node.lineno
            chunks.append((node.lineno, end, node.name))
            covered.append((node.lineno, end))
    covered.sort()
    cursor = 1
    leftover: list[tuple[int, int, str]] = []
    for start, end in covered:
        if start > cursor:
            leftover.append((cursor, start - 1, "Modulebene"))
        cursor = max(cursor, end + 1)
    if cursor <= len(lines):
        leftover.append((cursor, len(lines), "Modulebene"))
    for start, end, label in leftover:  # nur nicht-leere Modulebenen-Abschnitte aufnehmen
        if any(line.strip() for line in lines[start - 1:end]):
            chunks.append((start, end, label))
    return chunks or _line_windows(text)


def _line_windows(text: str) -> list[tuple[int, int, str]]:
    lines = text.splitlines()
    if not lines:
        return []
    out: list[tuple[int, int, str]] = []
    start = 1
    step = max(CHUNK_LINES - CHUNK_OVERLAP, 1)
    while start <= len(lines):
        end = min(start + CHUNK_LINES - 1, len(lines))
        out.append((start, end, f"Zeilen {start}-{end}"))
        if end >= len(lines):
            break
        start += step
    return out


def chunk_file(path: Path) -> list[tuple[int, int, str]]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    if path.suffix == ".py":
        return _python_chunks(text)
    return _line_windows(text)


@dataclass
class VectorStore:
    root: Path
    embedder: Embedder
    chunks: list[Chunk] = field(default_factory=list)
    truncated: bool = False

    # -- Persistenz -----------------------------------------------------------------------
    def _index_path(self) -> Path:
        return self.root / INDEX_FILE

    def load(self) -> bool:
        path = self._index_path()
        if not path.exists():
            return False
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        if data.get("version") != INDEX_VERSION or data.get("embedder") != self.embedder.name:
            return False  # anderes Backend/Modell -> Vektoren nicht vergleichbar, neu aufbauen
        self.chunks = [Chunk(**c) for c in data.get("chunks", [])]
        return True

    def save(self) -> None:
        path = self._index_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "version": INDEX_VERSION,
                "embedder": self.embedder.name,
                "chunks": [
                    {**c.__dict__, "vector": [round(v, 5) for v in c.vector]} for c in self.chunks
                ],
            }
            path.write_text(json.dumps(payload), encoding="utf-8")
        except OSError:
            pass  # Index ist ein Cache; schlägt das Schreiben fehl, wird beim nächsten Mal neu aufgebaut

    # -- Aufbau ---------------------------------------------------------------------------
    def _iter_source_files(self):
        count = 0
        for path in sorted(self.root.rglob("*")):
            if not path.is_file() or path.suffix not in SOURCE_EXTENSIONS:
                continue
            if any(part in EXCLUDE_DIRS for part in path.relative_to(self.root).parts[:-1]):
                continue
            try:
                if path.stat().st_size > MAX_FILE_BYTES:
                    continue
            except OSError:
                continue
            if count >= MAX_CHUNKS:  # grobe Vorabgrenze; harte Grenze greift beim Einfügen der Chunks
                self.truncated = True
                return
            count += 1
            yield path

    def build(self) -> None:
        self.chunks = []
        self.truncated = False
        self._reembed_all(list(self._iter_source_files()))
        self.save()

    def refresh(self) -> tuple[int, int]:
        """Baut nur neue/geänderte Dateien neu ein; gibt (geänderte Dateien, Chunks gesamt) zurück."""
        by_file: dict[str, list[Chunk]] = {}
        for c in self.chunks:
            by_file.setdefault(c.file, []).append(c)
        seen: set[str] = set()
        to_rebuild: list[Path] = []
        for path in self._iter_source_files():
            rel = str(path.relative_to(self.root))
            seen.add(rel)
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            existing = by_file.get(rel)
            if existing is None or existing[0].mtime != mtime:
                to_rebuild.append(path)
        if to_rebuild:
            self.chunks = [c for c in self.chunks if c.file not in {str(p.relative_to(self.root)) for p in to_rebuild}]
            self._reembed_all(to_rebuild)
        self.chunks = [c for c in self.chunks if c.file in seen]
        if to_rebuild:
            self.save()
        return len(to_rebuild), len(self.chunks)

    def _reembed_all(self, paths: list[Path]) -> None:
        texts: list[str] = []
        meta: list[tuple[str, int, int, str, float]] = []
        for path in paths:
            rel = str(path.relative_to(self.root))
            try:
                full_text = path.read_text(encoding="utf-8", errors="replace")
                mtime = path.stat().st_mtime
            except OSError:
                continue
            lines = full_text.splitlines()
            for start, end, label in chunk_file(path):
                if len(self.chunks) + len(meta) >= MAX_CHUNKS:
                    self.truncated = True
                    break
                snippet = "\n".join(lines[start - 1:end])
                if not snippet.strip():
                    continue
                texts.append(f"# {rel} :: {label}\n{snippet}")
                meta.append((rel, start, end, label, mtime))
        if not texts:
            return
        vectors = self.embedder.embed(texts)
        for (rel, start, end, label, mtime), vector in zip(meta, vectors):
            self.chunks.append(Chunk(rel, start, end, label, vector, mtime))

    # -- Suche ----------------------------------------------------------------------------
    def search(self, query: str, top_k: int = 8) -> list[SearchHit]:
        if not self.chunks:
            return []
        query_vec = self.embedder.embed([query])[0]
        scored = [(c, _cosine(query_vec, c.vector)) for c in self.chunks]
        scored.sort(key=lambda pair: pair[1], reverse=True)
        hits: list[SearchHit] = []
        for chunk, score in scored[:top_k]:
            hits.append(SearchHit(chunk.file, chunk.start_line, chunk.end_line, chunk.label, score,
                                   _read_snippet(self.root / chunk.file, chunk.start_line, chunk.end_line)))
        return hits

    def summary(self) -> str:
        if not self.chunks:
            return "Vektor-Index leer. /rag baut ihn auf (oder CodeSearch beim ersten Aufruf)."
        files = {c.file for c in self.chunks}
        lines = [f"Vektor-Index: {len(self.chunks)} Codeblöcke aus {len(files)} Datei(en), Backend: {self.embedder.name}"]
        if isinstance(self.embedder, HashingEmbedder):
            lines.append("  Hinweis: kein Ollama-Embedding-Modell gefunden -> lexikalische Näherung (Hashing). "
                          "Für echte semantische Suche: ollama pull nomic-embed-text")
        if self.truncated:
            lines.append(f"  Abgeschnitten bei {MAX_CHUNKS} Codeblöcken (sehr großes Repository)")
        return "\n".join(lines)


def _read_snippet(path: Path, start: int, end: int, max_lines: int = 25) -> str:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return "(Datei nicht mehr lesbar)"
    end = min(end, start + max_lines - 1, len(lines))
    return "\n".join(lines[start - 1:end])
