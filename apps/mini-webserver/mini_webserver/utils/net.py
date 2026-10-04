"""Netzwerk-Hilfen."""
from __future__ import annotations

import socket


def local_ip() -> str:
    """IP-Adresse des Rechners im lokalen Netzwerk (für den Zugriff vom Handy)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))  # UDP: es werden keine Daten gesendet
        ip = sock.getsockname()[0]
    except OSError:
        ip = ""
    finally:
        sock.close()
    if ip and not ip.startswith("127."):
        return ip
    try:
        for candidate in socket.gethostbyname_ex(socket.gethostname())[2]:
            if not candidate.startswith("127."):
                return candidate
    except OSError:
        pass
    return "127.0.0.1"
