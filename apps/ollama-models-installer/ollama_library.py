# Ollama Modell Installer - Katalog der Ollama-Bibliothek (reine Logik, ohne GUI)
#
# Die Daten sind ein Schnappschuss von https://ollama.com/library.
# Jeder Eintrag: (Name, Faehigkeiten, Groessen)
#   Faehigkeiten: t=tools, k=thinking, v=vision, e=embedding, c=cloud, a=audio
#   Groessen:     durch Leerzeichen getrennte Tags, z. B. "8b 70b"; leer = nur Standard-Tag
#
# Cloud-only-Modelle (Faehigkeit "c", keine Groessen) werden ueber den Tag
# "<name>:cloud" angesprochen und benoetigen ein Ollama-Konto (ollama signin).

import os
import re
import shutil
import sys

LIBRARY_SNAPSHOT_DATE = "2026-09-28"

STD_CHOICE = "Standard (latest)"
CLOUD_TAG = "cloud"

CATEGORY_ALL = "Alle Kategorien"
CATEGORIES = [CATEGORY_ALL, "Allgemein", "Code", "Reasoning", "Vision", "Embeddings"]

LIMIT_CHOICES = {
    "≤ 4B (4 GB VRAM)": 4.0,
    "≤ 8B": 8.0,
    "≤ 14B": 14.0,
    "≤ 32B": 32.0,
    "Unbegrenzt": None,
}
LIMIT_DEFAULT = "≤ 8B"

GB_PER_BILLION_PARAMS = 0.6  # grobe Schaetzung fuer Q4-Quantisierung
EMBEDDING_LATEST_PARAMS = 0.5  # Embedding-Modelle ohne Groessen-Tag sind klein

CAP_LABELS = {
    "t": "🛠 Tools",
    "k": "🧠 Thinking",
    "v": "👁 Vision",
    "e": "📐 Embedding",
    "c": "☁ Cloud",
    "a": "🔊 Audio",
}

_RAW_LIBRARY = [
    ("llama3.1", "t", "8b 70b 405b"),
    ("deepseek-r1", "tk", "1.5b 7b 8b 14b 32b 70b 671b"),
    ("nomic-embed-text", "e", ""),
    ("llama3.2", "t", "1b 3b"),
    ("qwen2.5", "t", "0.5b 1.5b 3b 7b 14b 32b 72b"),
    ("gemma3", "v", "270m 1b 4b 12b 27b"),
    ("qwen3", "tk", "0.6b 1.7b 4b 8b 14b 30b 32b 235b"),
    ("mistral", "t", "7b"),
    ("gemma2", "", "2b 9b 27b"),
    ("gemma4", "vtkac", "e2b e4b 12b 26b 31b"),
    ("llama3", "", "8b 70b"),
    ("qwen2.5-coder", "t", "0.5b 1.5b 3b 7b 14b 32b"),
    ("qwen3.5", "vtk", "0.8b 2b 4b 9b 27b 35b 122b"),
    ("phi3", "", "3.8b 14b"),
    ("mxbai-embed-large", "e", "335m"),
    ("llava", "v", "7b 13b 34b"),
    ("gpt-oss", "tkc", "20b 120b"),
    ("qwen3-coder", "t", "30b 480b"),
    ("gemma", "", "2b 7b"),
    ("qwen", "", "0.5b 1.8b 4b 7b 14b 32b 72b 110b"),
    ("phi4", "", "14b"),
    ("glm-ocr", "vt", ""),
    ("llama2", "", "7b 13b 70b"),
    ("bge-m3", "e", "567m"),
    ("qwen3.6", "vtk", "27b 35b"),
    ("codellama", "", "7b 13b 34b 70b"),
    ("qwen3-vl", "vtk", "2b 4b 8b 30b 32b 235b"),
    ("qwen2", "t", "0.5b 1.5b 7b 72b"),
    ("tinyllama", "", "1.1b"),
    ("mistral-nemo", "t", "12b"),
    ("minicpm-v", "v", "8b"),
    ("llama3.2-vision", "v", "11b 90b"),
    ("qwen2.5vl", "v", "3b 7b 32b 72b"),
    ("deepseek-coder", "", "1.3b 6.7b 33b"),
    ("llama3.3", "t", "70b"),
    ("dolphin3", "", "8b"),
    ("qwen3-embedding", "e", "0.6b 4b 8b"),
    ("smollm2", "t", "135m 360m 1.7b"),
    ("deepseek-v3", "", "671b"),
    ("olmo2", "", "7b 13b"),
    ("all-minilm", "e", "22m 33m"),
    ("codegemma", "", "2b 7b"),
    ("deepseek-coder-v2", "", "16b 236b"),
    ("mistral-small", "t", "22b 24b"),
    ("snowflake-arctic-embed", "e", "22m 33m 110m 137m 335m"),
    ("orca-mini", "", "3b 7b 13b 70b"),
    ("granite3.1-moe", "t", "1b 3b"),
    ("starcoder2", "", "3b 7b 15b"),
    ("nemotron-3-super", "tkc", "120b"),
    ("mixtral", "t", "8x7b 8x22b"),
    ("qwen3.8", "vtk", "27b"),
    ("llama2-uncensored", "", "7b 70b"),
    ("falcon3", "", "1b 3b 7b 10b"),
    ("mistral-small3.2", "vt", "24b"),
    ("translategemma", "v", "4b 12b 27b"),
    ("minimax-m2.7", "tkc", ""),
    ("llava-llama3", "v", "8b"),
    ("qwq", "t", "32b"),
    ("embeddinggemma", "e", "300m"),
    ("gemma3n", "", "e2b e4b"),
    ("smollm", "", "135m 360m 1.7b"),
    ("dolphin-llama3", "", "8b 70b"),
    ("cogito", "t", "3b 8b 14b 32b 70b"),
    ("qwen3-coder-next", "t", ""),
    ("glm-4.7-flash", "tk", ""),
    ("moondream", "v", "1.8b"),
    ("sqlcoder", "", "7b 15b"),
    ("dolphin-mixtral", "", "8x7b 8x22b"),
    ("llama4", "vt", "16x17b 128x17b"),
    ("dolphin-mistral", "", "7b"),
    ("phi4-reasoning", "", "14b"),
    ("hermes3", "t", "3b 8b 70b 405b"),
    ("dolphin-phi", "", "2.7b"),
    ("granite-code", "", "3b 8b 20b 34b"),
    ("phi", "", "2.7b"),
    ("command-r", "t", "35b"),
    ("granite4", "t", "350m 1b 3b"),
    ("yi", "", "6b 9b 34b"),
    ("phi4-mini", "t", "3.8b"),
    ("magistral", "tk", "24b"),
    ("ministral-3", "vt", "3b 8b 14b"),
    ("starcoder", "", "1b 3b 7b 15b"),
    ("openchat", "", "7b"),
    ("devstral-small-2", "vt", "24b"),
    ("codestral", "", "22b"),
    ("mistral-large", "t", "123b"),
    ("wizard-vicuna-uncensored", "", "7b 13b 30b"),
    ("zephyr", "", "7b 141b"),
    ("lfm2.5-thinking", "tk", "1.2b"),
    ("deepscaler", "", "1.5b"),
    ("vicuna", "", "7b 13b 33b"),
    ("glm4", "", "9b"),
    ("wizardcoder", "", "33b"),
    ("openhermes", "", ""),
    ("deepseek-llm", "", "7b 67b"),
    ("nous-hermes", "", "7b 13b"),
    ("deepseek-v2", "", "16b 236b"),
    ("wizardlm2", "", "7b 8x22b"),
    ("falcon", "", "7b 40b 180b"),
    ("openthinker", "", "7b 32b"),
    ("neural-chat", "", "7b"),
    ("lfm2", "t", "24b"),
    ("qwen2-math", "", "1.5b 7b 72b"),
    ("codeqwen", "", "7b"),
    ("granite3.3", "t", "2b 8b"),
    ("llama2-chinese", "", "7b 13b"),
    ("nous-hermes2", "", "10.7b 34b"),
    ("aya", "", "8b 35b"),
    ("stablelm2", "", "1.6b 12b"),
    ("yi-coder", "", "1.5b 9b"),
    ("stable-code", "", "3b"),
    ("wizard-math", "", "7b 13b 70b"),
    ("llama-guard3", "", "1b 8b"),
    ("llama3-chatqa", "", "8b 70b"),
    ("devstral", "t", "24b"),
    ("internlm2", "", "1m 1.8b 7b 20b"),
    ("granite3.1-dense", "t", "2b 8b"),
    ("phi3.5", "", "3.8b"),
    ("granite3-dense", "t", "2b 8b"),
    ("aya-expanse", "t", "8b 32b"),
    ("xwinlm", "", "7b 13b"),
    ("dolphincoder", "", "7b 15b"),
    ("samantha-mistral", "", "7b"),
    ("llama3-gradient", "", "8b 70b"),
    ("llama3-groq-tool-use", "t", "8b 70b"),
    ("granite3.2-vision", "vt", "2b"),
    ("yarn-llama2", "", "7b 13b"),
    ("starling-lm", "", "7b"),
    ("phind-codellama", "", "34b"),
    ("solar", "", "10.7b"),
    ("nomic-embed-text-v2-moe", "e", ""),
    ("granite3-moe", "t", "1b 3b"),
    ("stable-beluga", "", "7b 13b 70b"),
    ("deepcoder", "", "1.5b 14b"),
    ("shieldgemma", "", "2b 9b 27b"),
    ("orca2", "", "7b 13b"),
    ("paraphrase-multilingual", "e", "278m"),
    ("reader-lm", "", "0.5b 1.5b"),
    ("wizardlm", "", ""),
    ("llama-pro", "", ""),
    ("yarn-mistral", "", "7b"),
    ("nexusraven", "", "13b"),
    ("meditron", "", "7b 70b"),
    ("bakllava", "v", "7b"),
    ("nemotron-3-nano", "tkc", "4b 30b"),
    ("command-r-plus", "t", "104b"),
    ("mistral-small3.1", "vt", "24b"),
    ("mistral-openorca", "", "7b"),
    ("exaone-deep", "", "2.4b 7.8b 32b"),
    ("tinydolphin", "", "1.1b"),
    ("medllama2", "", "7b"),
    ("deepseek-v3.1", "tk", "671b"),
    ("nemotron-mini", "t", "4b"),
    ("codegeex4", "", "9b"),
    ("nemotron3", "vtk", "33b"),
    ("opencoder", "", "1.5b 8b"),
    ("wizardlm-uncensored", "", "13b"),
    ("nemotron", "t", "70b"),
    ("reflection", "", "70b"),
    ("codeup", "", "13b"),
    ("nous-hermes2-mixtral", "", "8x7b"),
    ("athene-v2", "t", "72b"),
    ("qwen3-next", "tk", "80b"),
    ("megadolphin", "", "120b"),
    ("everythinglm", "", "13b"),
    ("exaone3.5", "", "2.4b 7.8b 32b"),
    ("solar-pro", "", "22b"),
    ("magicoder", "", "7b"),
    ("nuextract", "", "3.8b"),
    ("mathstral", "", "7b"),
    ("falcon2", "", "11b"),
    ("notus", "", "7b"),
    ("notux", "", "8x7b"),
    ("deepseek-ocr", "v", "3b"),
    ("stablelm-zephyr", "", "3b"),
    ("ornith", "t", "9b 35b"),
    ("bespoke-minicheck", "", "7b"),
    ("duckdb-nsql", "", "7b"),
    ("firefunction-v2", "t", "70b"),
    ("mistrallite", "", "7b"),
    ("wizard-vicuna", "", "13b"),
    ("open-orca-platypus2", "", "13b"),
    ("minimax-m3", "vtkc", ""),
    ("rnj-1", "t", "8b"),
    ("codebooga", "", "34b"),
    ("goliath", "", ""),
    ("kimi-k2.6", "vtkc", ""),
    ("granite4.1", "t", "3b 8b 30b"),
    ("olmo-3", "tk", "7b 32b"),
    ("granite3.2", "t", "2b 8b"),
    ("snowflake-arctic-embed2", "e", "568m"),
    ("llava-phi3", "v", "3.8b"),
    ("medgemma", "v", "4b 27b"),
    ("deepseek-v4-pro", "tkc", ""),
    ("r1-1776", "", "70b 671b"),
    ("sailor2", "", "1b 8b 20b"),
    ("mistral-medium-3.5", "vtk", "128b"),
    ("tulu3", "", "8b 70b"),
    ("granite-embedding", "e", "30m 278m"),
    ("dbrx", "", "132b"),
    ("devstral-2", "t", "123b"),
    ("glm-5.2", "tkc", ""),
    ("ornith-1.5", "v", "9b 35b 397b"),
    ("granite3-guardian", "", "2b 8b"),
    ("command-r7b", "t", "7b"),
    ("phi4-mini-reasoning", "", "3.8b"),
    ("olmo-3.1", "tk", "32b"),
    ("deepseek-v2.5", "", "236b"),
    ("bge-large", "e", "335m"),
    ("alfred", "", "40b"),
    ("smallthinker", "", "3b"),
    ("kimi-k2.7-code", "vtkc", ""),
    ("muse-glimmer", "vtk", "30b"),
    ("command-a", "", "111b"),
    ("cogito-2.1", "", "671b"),
    ("marco-o1", "", "7b"),
    ("command-r7b-arabic", "t", "7b"),
    ("medgemma1.5", "v", "4b"),
    ("functiongemma", "t", "270m"),
    ("nemotron-3.5-lightning", "tk", "30b"),
    ("laguna-s-2.1", "tk", ""),
    ("lfm2.5", "tk", "8b"),
    ("gpt-oss-safeguard", "tk", "20b 120b"),
    ("glm-5.3-flash", "vtkc", ""),
    ("qwen3.8-flash-next", "vtk", ""),
    ("nemotron-cascade-2", "tk", "30b"),
    ("mistral-large-3", "vtc", ""),
    ("laguna-xs-2.1", "tk", ""),
    ("nemotron-3-ultra", "tkc", ""),
    ("granite4.2", "", "3b 8b 30b"),
    ("kimi-k3", "vtkc", ""),
    ("glm-5.3", "tkc", ""),
    ("north-mini-code-1.0", "tk", ""),
    ("minicpm-v4.6", "v", "1b"),
    ("deepseek-v4.1-flash", "vtkc", ""),
    ("minicpm-v4.5", "v", "8b"),
    ("laguna-xs.2", "tk", ""),
    ("granite4.1-guardian", "tk", "8b"),
]

_CODE_HINTS = ("code", "devstral", "nsql")
_SIZE_RE = re.compile(r"^(?:e)?(?:(\d+)x)?(\d+(?:\.\d+)?)([bm])$")
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


class LibraryModel:
    """Ein Modell (Familie) der Ollama-Bibliothek."""

    def __init__(self, name, caps, sizes):
        self.name = name
        self.caps = frozenset(caps)
        self.sizes = tuple(sizes.split())
        self.category = category_of(name, self.caps)

    @property
    def cloud_only(self):
        return "c" in self.caps and not self.sizes

    @property
    def cap_text(self):
        return "  ".join(CAP_LABELS[c] for c in "tkveca" if c in self.caps)

    def choices(self):
        """Auswahlmoeglichkeiten fuer das Groessen-Menue."""
        if self.cloud_only:
            return [CLOUD_TAG]
        return [STD_CHOICE] + list(self.sizes)

    def tag_for(self, choice):
        """Vollstaendiger `ollama pull`-Tag fuer eine Menue-Auswahl."""
        if self.cloud_only:
            return f"{self.name}:{CLOUD_TAG}"
        if not choice or choice == STD_CHOICE:
            return self.name
        return f"{self.name}:{choice}"


def parse_size_b(size):
    """Parameterzahl in Milliarden aus einem Groessen-Tag (z. B. '8x7b' -> 56.0)."""
    m = _SIZE_RE.match(size)
    if not m:
        return None
    experts = int(m.group(1)) if m.group(1) else 1
    value = float(m.group(2)) * experts
    return value / 1000.0 if m.group(3) == "m" else value


def category_of(name, caps):
    if "e" in caps:
        return "Embeddings"
    if "v" in caps:
        return "Vision"
    if any(hint in name for hint in _CODE_HINTS):
        return "Code"
    if "k" in caps:
        return "Reasoning"
    return "Allgemein"


def load_library():
    """Liefert alle Bibliotheksmodelle als Liste von LibraryModel."""
    return [LibraryModel(*entry) for entry in _RAW_LIBRARY]


def filter_models(models, query="", category=CATEGORY_ALL, include_cloud=False):
    """Filtert nach Suchtext, Kategorie und (optional) Cloud-only-Modellen."""
    terms = query.lower().split()
    result = []
    for m in models:
        if m.cloud_only and not include_cloud:
            continue
        if category != CATEGORY_ALL and m.category != category:
            continue
        haystack = f"{m.name} {' '.join(m.sizes)} {m.category}".lower()
        if all(t in haystack for t in terms):
            result.append(m)
    return result


def pick_choice(model, limit_b, include_cloud=False):
    """Waehlt die groesste Variante innerhalb des Limits.

    Rueckgabe: Menue-Auswahl (str) oder None, wenn nichts passt.
    Modelle ohne Groessen-Tag werden nur bei 'Unbegrenzt' gewaehlt
    (Ausnahme: kleine Embedding-Modelle), da ihre Groesse unbekannt ist.
    """
    if model.cloud_only:
        return CLOUD_TAG if include_cloud else None
    if not model.sizes:
        if limit_b is None or "e" in model.caps:
            return STD_CHOICE
        return None
    fitting = []
    for size in model.sizes:
        params = parse_size_b(size)
        if params is None:
            continue
        if limit_b is None or params <= limit_b:
            fitting.append((params, size))
    if not fitting:
        return None
    return max(fitting)[1]


def estimate_gb(tag):
    """Grobe Groessenschaetzung in GB (Q4) fuer einen Tag; None wenn unbekannt."""
    if tag.endswith(":" + CLOUD_TAG):
        return 0.0
    if ":" not in tag:
        return EMBEDDING_LATEST_PARAMS * GB_PER_BILLION_PARAMS if _is_embedding(tag) else None
    params = parse_size_b(tag.split(":", 1)[1])
    return None if params is None else params * GB_PER_BILLION_PARAMS


def _is_embedding(name):
    for entry in _RAW_LIBRARY:
        if entry[0] == name:
            return "e" in entry[1]
    return False


def normalize_tag(tag):
    """Ergaenzt ':latest', wenn kein Tag angegeben ist."""
    return tag if ":" in tag else f"{tag}:latest"


def normalize_installed(names):
    return {normalize_tag(n) for n in names}


def is_installed(tag, installed):
    """Prueft, ob ein Tag in `ollama list` vorhanden ist (installed = normalisierte Namen)."""
    return normalize_tag(tag) in installed


LINUX_SERVICE_MODELS_DIR = "/usr/share/ollama/.ollama/models"


def ollama_models_dir():
    """Ordner, in dem Ollama seine Modelle ablegt.

    Reihenfolge: OLLAMA_MODELS -> unter Linux der Ordner des systemd-Dienstes
    (Standard-Installation legt Modelle unter /usr/share/ollama ab) -> ~/.ollama/models.
    """
    custom = os.environ.get("OLLAMA_MODELS")
    if custom:
        return custom
    if sys.platform.startswith("linux") and os.path.isdir(LINUX_SERVICE_MODELS_DIR):
        return LINUX_SERVICE_MODELS_DIR
    return os.path.join(os.path.expanduser("~"), ".ollama", "models")


def free_disk_gb(path=None):
    """Freier Speicher (GB) auf dem Datentraeger des Modell-Ordners; None bei Fehler."""
    path = path or ollama_models_dir()
    while path and not os.path.exists(path):
        parent = os.path.dirname(path)
        if parent == path:
            break
        path = parent
    try:
        return shutil.disk_usage(path).free / 1e9
    except OSError:
        return None


def validate_library():
    """Interne Konsistenzpruefung; gibt eine Liste von Fehlermeldungen zurueck."""
    errors = []
    seen = set()
    for name, caps, sizes in _RAW_LIBRARY:
        if name in seen:
            errors.append(f"Duplikat: {name}")
        seen.add(name)
        if not _NAME_RE.match(name):
            errors.append(f"Ungueltiger Name: {name}")
        for c in caps:
            if c not in CAP_LABELS:
                errors.append(f"{name}: unbekannte Faehigkeit '{c}'")
        for size in sizes.split():
            if parse_size_b(size) is None:
                errors.append(f"{name}: Groesse nicht lesbar '{size}'")
    return errors
