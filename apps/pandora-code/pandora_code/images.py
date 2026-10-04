"""Bildeingabe: @pfad/zum/bild.png im Prompt, /image und Read auf Bilddateien."""
from __future__ import annotations

import base64
import re
from dataclasses import dataclass, field
from pathlib import Path

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_IMAGES = 5  # pro Nachricht
_TOKEN = re.compile(r"""(?<!\S)@(?:"([^"]+)"|'([^']+)'|(\S+))""")
_TRAILING = ",.;:!?)"


class ImageError(Exception):
    """Bild nicht lesbar, zu groß oder kein Bildformat."""


def is_image_bytes(data: bytes) -> bool:
    signatures = (b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff", b"GIF87a", b"GIF89a", b"BM")
    return data.startswith(signatures) or (data[:4] == b"RIFF" and data[8:12] == b"WEBP")


def encode_image(path: Path) -> str:
    """Liest eine Bilddatei und gibt Base64 zurück (Format wird an den Dateikopf-Bytes geprüft)."""
    size = path.stat().st_size
    if size > MAX_IMAGE_BYTES:
        raise ImageError(f"zu groß ({size // 1024} KB, Maximum {MAX_IMAGE_BYTES // 1024} KB)")
    data = path.read_bytes()
    if not is_image_bytes(data):
        raise ImageError("keine gültige Bilddatei")
    return base64.b64encode(data).decode("ascii")


@dataclass
class ImageResult:
    text: str
    images: list[str] = field(default_factory=list)
    names: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def extract_images(text: str, cwd: Path) -> ImageResult:
    """Ersetzt @bild.png durch [Bild: bild.png] und sammelt die Bilder als Base64."""
    result = ImageResult(text)

    def replace(match: re.Match[str]) -> str:
        raw = match.group(1) or match.group(2) or match.group(3)
        core, suffix = raw, ""
        if match.group(3):
            core = raw.rstrip(_TRAILING)
            suffix = raw[len(core):]
        try:
            path = Path(core).expanduser()
            if not path.is_absolute():
                path = cwd / path
            if path.suffix.lower() not in IMAGE_EXTENSIONS or not path.is_file():
                return match.group(0)  # kein Bild: Text unverändert lassen
        except (OSError, ValueError):
            return match.group(0)
        if len(result.images) >= MAX_IMAGES:
            result.errors.append(f"{path.name}: mehr als {MAX_IMAGES} Bilder pro Nachricht")
            return match.group(0)
        try:
            result.images.append(encode_image(path))
        except (ImageError, OSError) as err:
            result.errors.append(f"{path.name}: {err}")
            return match.group(0)
        result.names.append(path.name)
        return f"[Bild: {path.name}]{suffix}"

    result.text = _TOKEN.sub(replace, text)
    return result
