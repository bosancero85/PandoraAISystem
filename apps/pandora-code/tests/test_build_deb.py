"""Tests für Punkt 8: build_deb.sh baut ein echtes, korrektes Debian-Paket.

Baut tatsächlich mit dpkg-deb (kein Mock) und prüft das Ergebnis mit dpkg-deb -I/-c sowie durch
Extrahieren + echten Import-Versuch – genau die Art von Fehlern (falsche Dateirechte, falscher
Modul-Aufruf im Wrapper-Skript), die ein reiner Syntax-Check nie gefunden hätte.

Übersprungen, wenn dpkg-deb nicht installiert ist (das Skript ist bewusst nur für Debian/Kali-artige
Systeme gedacht – Akis Raspberry Pi 4B und Acer Aspire 5930g, beide Kali Linux).
"""
from __future__ import annotations

import shutil
import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BUILD_SCRIPT = REPO_ROOT / "build_deb.sh"

DPKG_DEB = shutil.which("dpkg-deb")


@unittest.skipUnless(DPKG_DEB, "dpkg-deb nicht installiert (nur auf Debian/Kali-artigen Systemen nutzbar)")
class BuildDebTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.version = "9.9.9-test"
        proc = subprocess.run(
            ["bash", str(BUILD_SCRIPT), cls.version], cwd=REPO_ROOT,
            capture_output=True, text=True, timeout=120,
        )
        cls.build_result = proc
        cls.deb_path = REPO_ROOT / "dist" / f"pandora-code_{cls.version}_all.deb"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.deb_path.unlink(missing_ok=True)

    def test_build_succeeds(self) -> None:
        self.assertEqual(self.build_result.returncode, 0, self.build_result.stderr)

    def test_deb_file_was_created(self) -> None:
        self.assertTrue(self.deb_path.is_file(), f"{self.deb_path} wurde nicht erzeugt")

    def test_control_metadata(self) -> None:
        info = subprocess.run([DPKG_DEB, "-I", str(self.deb_path)], capture_output=True, text=True, check=True).stdout
        self.assertIn("Package: pandora-code", info)
        self.assertIn(f"Version: {self.version}", info)
        self.assertIn("Architecture: all", info)
        self.assertIn("Depends: python3", info)

    def test_no_file_has_overly_restrictive_permissions(self) -> None:
        """Regressionstest für den beim Bauen gefundenen Bug: kopierte Quelldateien konnten 600 (nur für
        root lesbar) erben, was den Import für normale Nutzer nach der Installation gebrochen hätte."""
        listing = subprocess.run([DPKG_DEB, "-c", str(self.deb_path)], capture_output=True, text=True,
                                 check=True).stdout
        for line in listing.splitlines():
            mode = line.split()[0]
            if mode.startswith("d"):
                self.assertEqual(mode, "drwxr-xr-x", line)
            elif mode.startswith("-"):
                self.assertIn(mode, ("-rw-r--r--", "-rwxr-xr-x"), line)

    def test_executable_scripts_are_exactly_the_expected_three(self) -> None:
        listing = subprocess.run([DPKG_DEB, "-c", str(self.deb_path)], capture_output=True, text=True,
                                 check=True).stdout
        executables = {line.split()[-1] for line in listing.splitlines() if line.startswith("-rwxr-xr-x")}
        self.assertEqual(executables, {"./usr/bin/pandora", "./usr/bin/pandora-code"})

    def test_version_can_be_overridden_via_argument(self) -> None:
        info = subprocess.run([DPKG_DEB, "-I", str(self.deb_path)], capture_output=True, text=True, check=True).stdout
        self.assertIn("9.9.9-test", info)


@unittest.skipUnless(DPKG_DEB, "dpkg-deb nicht installiert (nur auf Debian/Kali-artigen Systemen nutzbar)")
class BuildDebContentTests(unittest.TestCase):
    """Baut einmal mit der echten Projektversion und extrahiert, um den Inhalt end-to-end zu prüfen."""

    @classmethod
    def setUpClass(cls) -> None:
        proc = subprocess.run(["bash", str(BUILD_SCRIPT)], cwd=REPO_ROOT, capture_output=True, text=True,
                              timeout=120)
        if proc.returncode != 0:
            raise RuntimeError(f"build_deb.sh fehlgeschlagen: {proc.stderr}")
        from pandora_code import __version__
        cls.deb_path = REPO_ROOT / "dist" / f"pandora-code_{__version__}_all.deb"
        import tempfile
        cls.tmp = tempfile.mkdtemp(prefix="pandora_deb_test_")
        subprocess.run([DPKG_DEB, "-x", str(cls.deb_path), cls.tmp], check=True)

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.tmp, ignore_errors=True)
        cls.deb_path.unlink(missing_ok=True)

    def _env(self) -> dict:
        import os
        return {**os.environ, "PYTHONPATH": f"{self.tmp}/usr/lib/python3/dist-packages"}

    def test_package_is_importable_from_extracted_tree(self) -> None:
        proc = subprocess.run(
            ["python3", "-c", "import pandora_code, pandora_code.cli; print(pandora_code.__file__)"],
            capture_output=True, text=True, env=self._env(), cwd="/tmp",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn(self.tmp, proc.stdout)  # lädt wirklich aus dem extrahierten Baum, nicht vom Dev-Checkout

    def test_wrapper_scripts_invoke_the_package_not_the_submodule_directly(self) -> None:
        """Regressionstest für den beim Bauen gefundenen Bug: 'python3 -m pandora_code.cli' führt cli.py
        nur als Modul OHNE main()-Aufruf aus (kein __main__-Guard dort) - das Skript muss unbedingt
        'python3 -m pandora_code' (das Package, dessen __main__.py main() aufruft) verwenden. Prüft gezielt
        die exec-Zeile, nicht den ganzen Dateitext (der erklärende Kommentar nennt 'pandora_code.cli'
        legitim als Namen der Python-Funktion, auf die er sich bezieht)."""
        for name in ("pandora", "pandora-code"):
            lines = (Path(self.tmp) / "usr/bin" / name).read_text(encoding="utf-8").splitlines()
            exec_lines = [ln for ln in lines if ln.strip().startswith("exec ")]
            self.assertEqual(len(exec_lines), 1, lines)
            self.assertEqual(exec_lines[0].strip(), 'exec python3 -m pandora_code "$@"')

    def test_pandora_help_actually_prints_usage(self) -> None:
        proc = subprocess.run(
            [f"{self.tmp}/usr/bin/pandora", "code", "--help"],
            capture_output=True, text=True, env=self._env(), cwd="/tmp",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("usage: pandora-code", proc.stdout)
        self.assertGreater(len(proc.stdout.splitlines()), 5)  # Regressionsschutz: nicht nur leere Zeile(n)

    def test_pandora_strips_leading_code_case_insensitively(self) -> None:
        for leading in ("code", "Code", "CODE"):
            proc = subprocess.run(
                [f"{self.tmp}/usr/bin/pandora", leading, "--version"],
                capture_output=True, text=True, env=self._env(), cwd="/tmp",
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("Pandora", proc.stdout)

    def test_pandora_code_hyphen_variant_works_directly(self) -> None:
        proc = subprocess.run([f"{self.tmp}/usr/bin/pandora-code", "--version"],
                              capture_output=True, text=True, env=self._env(), cwd="/tmp")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("Pandora", proc.stdout)

    def test_doctor_runs_and_fails_cleanly_without_a_reachable_ollama(self) -> None:
        proc = subprocess.run(
            [f"{self.tmp}/usr/bin/pandora-code", "--doctor", "--host", "127.0.0.1:1"],
            capture_output=True, text=True, env=self._env(), cwd="/tmp", timeout=20,
        )
        self.assertEqual(proc.returncode, 1)
        self.assertIn("nicht erreichbar", proc.stdout)

    def test_readme_and_changelog_are_included(self) -> None:
        doc_dir = Path(self.tmp) / "usr/share/doc/pandora-code"
        self.assertTrue((doc_dir / "README.md").is_file())
        self.assertTrue((doc_dir / "changelog.Debian.gz").is_file())

    def test_playbook_templates_are_packaged(self) -> None:
        templates = Path(self.tmp) / "usr/lib/python3/dist-packages/pandora_code/playbook_template"
        self.assertTrue(any(templates.glob("*.md")))

    def test_no_pycache_or_bytecode_shipped(self) -> None:
        """Prüft das .deb-Archiv selbst (nicht das extrahierte Verzeichnis, das durch andere Tests in
        dieser Klasse zwischenzeitlich per 'python3 -c import ...' ganz normal eigene __pycache__-Ordner
        angesammelt haben kann - das ist natürliches Python-Verhalten beim Importieren, kein Bug)."""
        listing = subprocess.run([DPKG_DEB, "-c", str(self.deb_path)], capture_output=True, text=True,
                                 check=True).stdout
        self.assertNotIn("__pycache__", listing)
        self.assertNotIn(".pyc", listing)


class BuildDebWithoutDpkgTests(unittest.TestCase):
    """Läuft auch ohne dpkg-deb: prüft, dass das Skript dann klar scheitert statt kryptisch."""

    def test_script_fails_clearly_if_dpkg_deb_missing(self) -> None:
        if DPKG_DEB:
            self.skipTest("dpkg-deb ist hier installiert - dieser Zweig gilt nur für dessen Abwesenheit.")
        proc = subprocess.run(["bash", str(BUILD_SCRIPT)], cwd=REPO_ROOT, capture_output=True, text=True)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("dpkg-deb", proc.stdout + proc.stderr)

    def test_script_is_syntactically_valid_bash_regardless_of_platform(self) -> None:
        proc = subprocess.run(["bash", "-n", str(BUILD_SCRIPT)], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)


if __name__ == "__main__":
    unittest.main()
