"""Tests für scripts/build_release.py und die Übereinstimmung der Dateinamen im ganzen Repo.

Aufruf:  python -m unittest discover -s scripts -p "test_*.py"
PyInstaller wird hier nicht ausgeführt (läuft in GitHub Actions auf dem jeweiligen System).
"""
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_release as br  # noqa: E402

ROOT = br.ROOT


def release_yml() -> str:
    return (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")


class AssetNameTests(unittest.TestCase):
    def test_all_eleven_assets_listed_once(self):
        names = br.expected_assets()
        self.assertEqual(len(names), 11)
        self.assertEqual(len(set(names)), 11, "Dateinamen müssen eindeutig sein")

    def test_every_os_gets_its_installer_webserver_code(self):
        for tag in br.OS_TAGS:
            for app in ("installer", "webserver", "code"):
                self.assertTrue(br.ASSETS[app][tag], "%s/%s ohne Datei" % (app, tag))

    def test_landing_page_download_names_match(self):
        tpl = (ROOT / "scripts" / "landing_template.html").read_text(encoding="utf-8")
        block = tpl[tpl.index("var FILES = {"): tpl.index("var REQ = {")]
        mapping = {"windows": "Win", "macos": "Mac", "linux": "Linux"}
        found = re.findall(r"(\w+): \{ windows: '([^']+)', macos: '([^']+)', linux: '([^']+)' \}", block)
        self.assertEqual({f[0] for f in found}, {"installer", "webserver", "code", "chat"})
        for tool, win, mac, lin in found:
            for os_key, name in zip(("windows", "macos", "linux"), (win, mac, lin)):
                tag = mapping[os_key]
                if tool == "chat":
                    self.assertEqual(name, "Ollama-Browser-Chat-Web.zip")
                else:
                    self.assertIn(name, br.ASSETS[tool][tag], "Landingpage verweist auf %s, Build erzeugt %s" % (name, br.ASSETS[tool][tag]))

    def test_readme_links_use_real_asset_names(self):
        known = set(br.expected_assets())
        for readme in ("README.md", "README.de.md"):
            text = (ROOT / readme).read_text(encoding="utf-8")
            linked = set(re.findall(r"releases/latest/download/([A-Za-z0-9._-]+)\)", text))
            self.assertTrue(linked, readme)
            self.assertEqual(linked - known, set(), "%s verlinkt unbekannte Dateien" % readme)
            self.assertEqual(known - linked - {"SHA256SUMS.txt"}, set(), "%s verlinkt nicht alle Dateien" % readme)

    def test_release_workflow_publishes_the_same_names(self):
        text = release_yml()
        self.assertTrue("--check-assets" in text, "Der Release-Job muss die Vollständigkeit prüfen")
        self.assertTrue("--checksums" in text, "Der Release-Job muss SHA256SUMS.txt schreiben")
        self.assertTrue("fail_on_unmatched_files: true" in text)


class PlanTests(unittest.TestCase):
    def test_plans_exist_for_every_os_and_reference_real_sources(self):
        for tag in br.OS_TAGS:
            steps = br.make_plan(list(br.APP_ORDER), tag)
            self.assertTrue(steps)
            for step in steps:
                if not step.cmd:
                    continue
                for part in step.cmd:
                    p = Path(part)
                    # Quelldateien im Repo (Startdateien, Icons) müssen existieren. Erzeugtes (build/, release/) ausnehmen.
                    if p.is_absolute() and str(ROOT) in part and "release-work" not in part and "/release/" not in part:
                        if p.suffix in (".py", ".ico", ".png"):
                            generated = p.name == "icon.ico" or p.name == "icon.png"
                            self.assertTrue(p.exists() or generated, "%s fehlt (%s)" % (part, tag))

    def test_platform_specific_flags(self):
        def flags(app, tag):
            return " ".join(" ".join(s.cmd) for s in br.make_plan([app], tag) if s.cmd)
        self.assertIn("--windowed", flags("installer", "Win"))
        self.assertIn("--onefile", flags("installer", "Win"))
        self.assertNotIn("--onefile", flags("installer", "Mac"))   # .app-Ordner, kein Einzelprogramm
        self.assertIn("hdiutil", flags("webserver", "Mac"))
        self.assertIn("pystray._win32", flags("webserver", "Win"))
        self.assertIn("pystray._darwin", flags("webserver", "Mac"))
        self.assertIn("pystray._xorg", flags("webserver", "Linux"))
        self.assertIn("--collect-submodules pandora_code", flags("code", "Linux"))
        self.assertIn("build_deb.sh", flags("code", "Linux"))
        self.assertIn("--console", flags("code", "Win"))

    def test_icon_arguments_exist_for_gui_apps(self):
        for tag in br.OS_TAGS:
            for app in ("installer", "webserver"):
                text = " ".join(" ".join(s.cmd) for s in br.make_plan([app], tag) if s.cmd)
                if tag != "Linux":
                    self.assertIn("--icon", text, "%s/%s ohne Symbol" % (app, tag))

    def test_dry_run_prints_and_does_not_build(self):
        res = subprocess.run([sys.executable, str(ROOT / "scripts" / "build_release.py"), "--app", "all", "--os", "Linux", "--dry-run"],
                             capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("PyInstaller", res.stdout)
        self.assertIn("pandora-code-Linux.deb", res.stdout)

    def test_cross_build_is_refused(self):
        other = "Win" if br.current_os() != "Win" else "Mac"
        res = subprocess.run([sys.executable, str(ROOT / "scripts" / "build_release.py"), "--app", "chat", "--os", other],
                             capture_output=True, text=True)
        self.assertEqual(res.returncode, 1)
        self.assertIn("--dry-run", res.stderr)

    def test_bad_arguments(self):
        res = subprocess.run([sys.executable, str(ROOT / "scripts" / "build_release.py")], capture_output=True, text=True)
        self.assertEqual(res.returncode, 2)


class RealBuildTests(unittest.TestCase):
    """Schritte, die ohne PyInstaller laufen: Web-Paket, Prüfsummen, Vollständigkeit, AppImage-Ordner."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self._release = br.RELEASE
        br.RELEASE = self.tmp / "release"

    def tearDown(self):
        br.RELEASE = self._release
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_chat_zip_contents(self):
        for step in br.plan_chat("Linux"):
            step.run()
        target = br.RELEASE / "Ollama-Browser-Chat-Web.zip"
        self.assertTrue(target.is_file())
        names = zipfile.ZipFile(target).namelist()
        for must in ("ollama.html", "script.js", "style.css", "sw.js", "manifest.json", "icons/icon-192.png"):
            self.assertIn("Ollama-Browser-Chat/" + must, names)
        for bad in ("tests/", "playbook/", ".git/", "__pycache__"):
            self.assertFalse(any(bad in n for n in names), "%s gehört nicht ins Web-Paket" % bad)
        self.assertEqual(zipfile.ZipFile(target).testzip(), None)

    def test_checksums_and_completeness(self):
        br.RELEASE.mkdir(parents=True)
        self.assertEqual(len(br.missing_assets(br.RELEASE)), 11)
        for name in br.expected_assets():
            (br.RELEASE / name).write_bytes(name.encode())
        self.assertEqual(br.missing_assets(br.RELEASE), [])
        out = br.write_checksums(br.RELEASE)
        lines = out.read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines), 11)
        self.assertTrue(all(re.fullmatch(r"[0-9a-f]{64}  \S+", l) for l in lines))
        self.assertEqual(br.sha256(br.RELEASE / "pandora-code-Linux"), [l.split()[0] for l in lines if l.endswith("pandora-code-Linux")][0])
        # zweiter Lauf nimmt SHA256SUMS.txt nicht in sich selbst auf
        br.write_checksums(br.RELEASE)
        self.assertEqual(len(out.read_text(encoding="utf-8").strip().splitlines()), 11)
        res = subprocess.run([sys.executable, str(ROOT / "scripts" / "build_release.py"), "--check-assets", str(br.RELEASE)], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stderr)
        (br.RELEASE / "MiniWebserver-Mac.dmg").unlink()
        res = subprocess.run([sys.executable, str(ROOT / "scripts" / "build_release.py"), "--check-assets", str(br.RELEASE)], capture_output=True, text=True)
        self.assertEqual(res.returncode, 1)
        self.assertIn("MiniWebserver-Mac.dmg", res.stderr)

    @unittest.skipIf(sys.platform.startswith("win"), "AppImage-Test nutzt ein Shell-Skript (läuft nur unter Linux und macOS)")
    def test_appimage_appdir_layout(self):
        import os
        binary = self.tmp / "bin" / "MiniWebserver"
        binary.parent.mkdir()
        binary.write_bytes(b"#!/bin/sh\n")
        icon = self.tmp / "icon.png"
        icon.write_bytes(b"png")
        fake_tool = self.tmp / "appimagetool"
        fake_tool.write_text('#!/bin/sh\ncp -r "$1" "$2.appdir-copy" && : > "$2"\n', encoding="utf-8")
        fake_tool.chmod(0o755)
        os.environ["APPIMAGETOOL"] = str(fake_tool)
        try:
            work = self.tmp / "work"
            work.mkdir()
            br.make_appimage(binary, work, "mini-webserver", "Mini Webserver", icon, "MiniWebserver-Linux.AppImage").run()
        finally:
            del os.environ["APPIMAGETOOL"]
        copy = br.RELEASE / "MiniWebserver-Linux.AppImage.appdir-copy"
        self.assertTrue((br.RELEASE / "MiniWebserver-Linux.AppImage").exists())
        self.assertTrue((copy / "usr/bin/MiniWebserver").exists())
        self.assertIn('exec "$HERE/usr/bin/MiniWebserver"', (copy / "AppRun").read_text())
        self.assertTrue(os.access(copy / "AppRun", os.X_OK))
        desktop = (copy / "mini-webserver.desktop").read_text()
        self.assertIn("Exec=MiniWebserver", desktop)
        self.assertIn("Icon=mini-webserver", desktop)
        self.assertTrue((copy / "mini-webserver.png").exists() and (copy / ".DirIcon").exists())

    @unittest.skipUnless(shutil.which("dpkg-deb") and shutil.which("bash"), "dpkg-deb fehlt")
    def test_deb_builds_and_is_copied(self):
        app = ROOT / "apps" / "pandora-code"
        before = set((app / "dist").glob("*.deb")) if (app / "dist").exists() else set()
        try:
            for step in br.plan_code("Linux")[2:]:      # nur .deb bauen und kopieren, ohne PyInstaller
                step.run()
            deb = br.RELEASE / "pandora-code-Linux.deb"
            self.assertTrue(deb.is_file() and deb.stat().st_size > 1000)
            info = subprocess.run(["dpkg-deb", "-I", str(deb)], capture_output=True, text=True).stdout
            self.assertIn("Package: pandora-code", info)
        finally:
            for f in (app / "dist").glob("*.deb") if (app / "dist").exists() else []:
                if f not in before:
                    f.unlink()
            if (app / "dist").exists() and not any((app / "dist").iterdir()):
                (app / "dist").rmdir()


class BundleEntryTests(unittest.TestCase):
    def test_bundle_entry_runs_and_drops_leading_code(self):
        app = ROOT / "apps" / "pandora-code"
        for args in (["--help"], ["code", "--help"]):
            res = subprocess.run([sys.executable, str(app / "pandora_code_bundle.py")] + args, cwd=str(app), capture_output=True, text=True)
            self.assertEqual(res.returncode, 0, res.stderr)
            self.assertIn("usage", (res.stdout + res.stderr).lower())


if __name__ == "__main__":
    unittest.main()
