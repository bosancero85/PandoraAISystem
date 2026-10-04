"""Bindet das lokale Vektor-RAG (context/vector_store.py) als Werkzeug `CodeSearch` und Befehl `/rag` ein.

Wählt automatisch das beste verfügbare Embedding: ein installiertes Ollama-Embedding-Modell (z. B.
`nomic-embed-text`, per Hot Reload über die ModelRegistry aus Punkt 7 erkannt), sonst den abhängigkeitsfreien
Hashing-Fallback. Schlägt das gewählte Ollama-Modell beim ersten Aufbau tatsächlich fehl (z. B. weil es trotz
passendem Namen keine Embeddings liefert), wechselt die Sitzung automatisch und mit sichtbarem Hinweis auf
den Fallback, statt einfach abzubrechen.
"""
from __future__ import annotations

from ..context.vector_store import HashingEmbedder, OllamaEmbedder, VectorStore, pick_embed_model
from ..ollama_client import OllamaError
from ..tools import Tool, ToolContext, ToolError, schema


def _make_embedder(agent, settings):
    installed: list[str] = []
    if agent.registry:
        installed = agent.registry.refresh()
    if not installed:
        try:
            installed = agent.client.list_models()
        except OllamaError:
            installed = []
    override = getattr(settings, "embed_model", None)
    if override:
        match = next((m for m in installed if m == override or m.split(":")[0] == override.split(":")[0]), None)
        if match:
            return OllamaEmbedder(agent.client, match)
    model = pick_embed_model(installed)
    return OllamaEmbedder(agent.client, model) if model else HashingEmbedder()


def _store_for(agent, settings) -> VectorStore:
    store: VectorStore | None = getattr(agent, "vector_store", None)
    if store is None or store.root != agent.ctx.cwd:
        store = VectorStore(agent.ctx.cwd, _make_embedder(agent, settings))
        store.load()  # vorhandenen Index desselben Backends übernehmen; sonst bleibt er leer (lazy build)
        agent.vector_store = store
    return store


def _ensure_built(agent, store: VectorStore) -> VectorStore:
    if store.chunks:
        return store
    try:
        store.build()
        return store
    except OllamaError as err:
        if isinstance(store.embedder, HashingEmbedder):
            raise
        agent.ui.error(
            f"⚠ Embedding-Modell '{store.embedder.model}' fehlgeschlagen ({err}). "
            "Wechsle für die Vektorsuche auf die lokale Wort-Näherung (ohne Ollama)."
        )
        store = VectorStore(agent.ctx.cwd, HashingEmbedder())
        store.build()
        agent.vector_store = store
        return store


def install(agent, settings) -> None:
    agent.vector_store = None  # lazy: erst beim ersten CodeSearch/​/rag aufgebaut (spart Zeit bei kleinen Fragen)

    def code_search(ctx: ToolContext, args: dict) -> str:
        query = str(args.get("query") or "").strip()
        if not query:
            raise ToolError("'query' fehlt.")
        top_k = max(1, min(int(args.get("top_k") or 8), 20))
        store = _ensure_built(agent, _store_for(agent, settings))
        hits = store.search(query, top_k)
        if not hits:
            return "Keine passenden Codeblöcke gefunden (Index leer oder Repository ohne unterstützte Dateien)."
        blocks = [
            f"{h.file}:{h.start_line}-{h.end_line}  [{h.label}]  Ähnlichkeit {h.score:.2f}\n{h.snippet}"
            for h in hits
        ]
        return "\n\n".join(blocks)

    agent.add_tool(Tool(
        "CodeSearch",
        "Semantic-ish search over the whole codebase via a local vector index (embeddings, not text match) – "
        "returns only the most relevant code blocks instead of whole files, so large repositories don't "
        "overflow the context window. Use this to explore an unfamiliar codebase or find where a *concept* "
        "(not an exact name) is implemented, before falling back to Grep for exact-string matches. 'top_k' "
        "caps the number of results (default 8, max 20).",
        schema({"query": {"type": "string", "description": "What you're looking for, in plain language"},
                "top_k": {"type": "integer", "description": "Max results (default 8, max 20)"}},
               ("query",)),
        code_search,
    ))

    def rag_command(arg: str, agent, ui) -> str | None:
        store = _store_for(agent, settings)
        choice = arg.strip().lower()
        if choice in ("neu", "rebuild", "refresh"):
            store.build()
        elif not store.chunks:
            store.build()
        else:
            changed, total = store.refresh()
            ui.info(f"{changed} Datei(en) neu eingebettet, {total} Codeblöcke insgesamt.")
        ui.info(store.summary())
        return None

    agent.register_command(
        "rag", rag_command,
        "/rag [neu]  Vektor-Index für die semantische Codesuche anzeigen/aufbauen "
        "(ohne Argument: nur neue/geänderte Dateien nachbetten)",
    )
