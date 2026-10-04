"""Einstieg für die gebauten Programme (PyInstaller): `pandora-code-Linux code ...` und `pandora-code-Linux ...`.

Wie der Startbefehl `pandora code`: Ein führendes „code“ wird verworfen.
"""
from pandora_code.cli import pandora_entry

if __name__ == "__main__":
    pandora_entry()
