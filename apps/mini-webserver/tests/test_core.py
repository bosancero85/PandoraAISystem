import json
import os
import socket
import ssl
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mini_webserver.core import certs
from mini_webserver.core.server import (ServerController, ServerError, list_html, suggest_page,
                                        validate_folder, validate_port, validate_upstream)
from mini_webserver.utils import net, paths, settings


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def write(folder, name, text="x"):
    with open(os.path.join(folder, name), "w", encoding="utf-8") as fh:
        fh.write(text)


class ValidationTests(unittest.TestCase):
    def test_port(self):
        self.assertEqual(validate_port(" 8080 "), 8080)
        for bad in ("abc", "", "0", "70000", "-1"):
            with self.assertRaises(ServerError):
                validate_port(bad)

    def test_folder(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(validate_folder(d), os.path.abspath(d))
            with self.assertRaises(ServerError):
                validate_folder(os.path.join(d, "gibt-es-nicht"))
        with self.assertRaises(ServerError):
            validate_folder("   ")


class PageTests(unittest.TestCase):
    def test_suggest_and_list(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(list_html(d), [])
            self.assertEqual(suggest_page(d), "")
            write(d, "zeta.html")
            write(d, "alpha.HTM")
            write(d, "notiz.txt")
            self.assertEqual(list_html(d), ["alpha.HTM", "zeta.html"])
            self.assertEqual(suggest_page(d), "alpha.HTM")
            write(d, "index.html")
            self.assertEqual(suggest_page(d), "")


class PathTests(unittest.TestCase):
    def test_initial_folder(self):
        with tempfile.TemporaryDirectory() as base, tempfile.TemporaryDirectory() as saved:
            self.assertEqual(paths.initial_folder(saved, base), saved)      # keine HTML im App-Ordner
            write(base, "seite.html")
            self.assertEqual(paths.initial_folder(saved, base), base)       # HTML neben der App gewinnt
            self.assertEqual(paths.initial_folder("/gibt/es/nicht", base), base)
        with tempfile.TemporaryDirectory() as base:
            self.assertEqual(paths.initial_folder("/gibt/es/nicht", base), base)


class SettingsTests(unittest.TestCase):
    def test_roundtrip_and_garbage(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "sub", "s.json")
            self.assertEqual(settings.load(p), settings.DEFAULTS)
            data = {"folder": "C:\\Web", "port": 9000, "https": False, "upstream": "http://10.0.0.5:11434"}
            self.assertTrue(settings.save(data, p))
            self.assertEqual(settings.load(p), data)
            with open(p, "w") as fh:
                fh.write("{kaputt")
            self.assertEqual(settings.load(p), settings.DEFAULTS)
            with open(p, "w") as fh:
                fh.write('{"folder": 5, "port": "80", "https": "ja", "upstream": 3}')
            self.assertEqual(settings.load(p), settings.DEFAULTS)


class NetTests(unittest.TestCase):
    def test_local_ip_is_ipv4(self):
        socket.inet_aton(net.local_ip())


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        write(self.dir.name, "index.html", "<h1>Hallo</h1>")
        self.logs = []
        self.ctl = ServerController(log=self.logs.append)

    def tearDown(self):
        self.ctl.stop()
        self.dir.cleanup()

    def get(self, port, path="/"):
        return urllib.request.urlopen("http://127.0.0.1:%d%s" % (port, path), timeout=5)

    def test_serves_folder_and_logs(self):
        port = free_port()
        self.ctl.start(self.dir.name, port)
        self.assertTrue(self.ctl.running)
        with self.get(port) as resp:
            self.assertEqual(resp.read(), b"<h1>Hallo</h1>")
            self.assertEqual(resp.headers["Cache-Control"], "no-cache")
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self.get(port, "/fehlt.html")
        self.assertEqual(cm.exception.code, 404)
        self.assertTrue(any("GET / " in line for line in self.logs), self.logs)
        self.assertTrue(any("Server gestartet" in line for line in self.logs))

    def test_no_path_traversal(self):
        port = free_port()
        self.ctl.start(self.dir.name, port)
        with self.assertRaises(urllib.error.HTTPError):
            self.get(port, "/..%2f..%2f..%2fetc/passwd")

    def test_stop_and_restart(self):
        port = free_port()
        self.ctl.start(self.dir.name, port)
        self.assertTrue(self.ctl.stop())
        self.assertFalse(self.ctl.running)
        self.assertFalse(self.ctl.stop())
        with self.assertRaises(urllib.error.URLError):
            self.get(port)
        self.ctl.start(self.dir.name, port)  # gleicher Port gleich wieder frei
        with self.get(port) as resp:
            self.assertEqual(resp.status, 200)

    def test_double_start_and_bad_input(self):
        port = free_port()
        self.ctl.start(self.dir.name, port)
        with self.assertRaises(ServerError):
            self.ctl.start(self.dir.name, port)
        self.ctl.stop()
        with self.assertRaises(ServerError):
            self.ctl.start("/gibt/es/nicht", port)
        with self.assertRaises(ServerError):
            self.ctl.start(self.dir.name, "abc")
        self.assertFalse(self.ctl.running)

    def test_port_in_use_message(self):
        blocker = socket.socket()
        blocker.bind(("0.0.0.0", 0))
        blocker.listen(1)
        try:
            with self.assertRaises(ServerError) as cm:
                self.ctl.start(self.dir.name, blocker.getsockname()[1])
            self.assertIn("belegt", str(cm.exception))
            self.assertFalse(self.ctl.running)
        finally:
            blocker.close()

    def test_warns_without_html(self):
        with tempfile.TemporaryDirectory() as empty:
            self.ctl.start(empty, free_port())
        self.assertTrue(any("keine HTML" in line for line in self.logs))


class UpstreamTests(unittest.TestCase):
    def test_validate_upstream(self):
        self.assertEqual(validate_upstream(""), "")
        self.assertEqual(validate_upstream("  "), "")
        self.assertEqual(validate_upstream("192.168.178.40"), "http://192.168.178.40:11434")
        self.assertEqual(validate_upstream("http://localhost:9999/"), "http://localhost:9999")
        for bad in ("https://x:11434", "http://", "http://host:abc"):
            with self.assertRaises(ServerError):
                validate_upstream(bad)


class CertTests(unittest.TestCase):
    def test_issue_reuse_and_renew(self):
        with tempfile.TemporaryDirectory() as d:
            paths, new = certs.ensure_certificates(d, ["192.168.178.40", "MeinPC", "", "192.168.178.40"])
            self.assertTrue(new)
            hosts = certs.cert_hosts(paths.cert)
            self.assertTrue({"192.168.178.40", "meinpc", "localhost", "127.0.0.1"} <= hosts)
            with open(paths.ca_cert, "rb") as fh:
                ca_before = fh.read()
            _, new = certs.ensure_certificates(d, ["192.168.178.40"])
            self.assertFalse(new)                                   # nichts geändert, nichts neu
            paths, new = certs.ensure_certificates(d, ["192.168.178.99"])
            self.assertTrue(new)                                    # neue IP, neues Server-Zertifikat
            self.assertIn("192.168.178.99", certs.cert_hosts(paths.cert))
            with open(paths.ca_cert, "rb") as fh:
                self.assertEqual(fh.read(), ca_before)              # CA bleibt gleich (Handy muss nichts neu installieren)

    def test_split_hosts(self):
        self.assertEqual(certs.split_hosts(["A.local", "10.0.0.1", "a.local", " ", "::1"]),
                         (["a.local"], ["10.0.0.1", "::1"]))


class _FakeOllama(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    seen = {}

    def do_GET(self):
        body = json.dumps({"models": [{"name": "test:1"}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        _FakeOllama.seen = {"body": self.rfile.read(int(self.headers["Content-Length"])), "headers": dict(self.headers)}
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        for i in range(2):
            line = (json.dumps({"i": i}) + "\n").encode()
            self.wfile.write(b"%x\r\n%s\r\n" % (len(line), line))
            self.wfile.flush()
            time.sleep(0.2)
        self.wfile.write(b"0\r\n\r\n")

    def log_message(self, *args):
        pass


class HttpsAndProxyTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        write(self.dir.name, "index.html", "<h1>Sicher</h1>")
        self.certdir = tempfile.TemporaryDirectory()
        self.paths, _ = certs.ensure_certificates(self.certdir.name, ["127.0.0.1"])
        self.ctx = ssl.create_default_context(cafile=self.paths.ca_cert)
        self.up_port = free_port()
        self.upstream = ThreadingHTTPServer(("127.0.0.1", self.up_port), _FakeOllama)
        threading.Thread(target=self.upstream.serve_forever, daemon=True).start()
        self.logs = []
        self.ctl = ServerController(log=self.logs.append)
        self.port = free_port()
        self.base = "https://127.0.0.1:%d" % self.port

    def tearDown(self):
        self.ctl.stop()
        self.upstream.shutdown()
        self.upstream.server_close()
        self.dir.cleanup()
        self.certdir.cleanup()

    def open(self, path, **kw):
        return urllib.request.urlopen(self.base + path, context=self.ctx, timeout=5, **kw)

    def test_https_serves_and_is_secure(self):
        self.ctl.start(self.dir.name, self.port, tls=self.paths)
        self.assertTrue(self.ctl.https)
        with self.open("/") as resp:
            self.assertEqual(resp.read(), b"<h1>Sicher</h1>")
        with self.assertRaises(urllib.error.URLError):               # ohne CA-Vertrauen: Zertifikatsfehler
            urllib.request.urlopen(self.base + "/", timeout=5)
        self.assertTrue(any("HTTPS" in line for line in self.logs))

    def test_ca_download(self):
        self.ctl.start(self.dir.name, self.port, tls=self.paths)
        with self.open("/mini-webserver-ca.crt") as resp:
            self.assertEqual(resp.headers["Content-Type"], "application/x-x509-ca-cert")
            self.assertTrue(resp.read().startswith(b"-----BEGIN CERTIFICATE-----"))

    def test_proxy_forwards_and_streams(self):
        self.ctl.start(self.dir.name, self.port, tls=self.paths, upstream="127.0.0.1:%d" % self.up_port)
        with self.open("/api/tags") as resp:
            self.assertEqual(json.loads(resp.read())["models"][0]["name"], "test:1")
        req = urllib.request.Request(self.base + "/api/chat", data=b'{"model":"x"}', method="POST",
                                     headers={"Content-Type": "application/json", "Origin": "https://fremd.example",
                                              "Referer": "https://fremd.example/"})
        start = time.time()
        with urllib.request.urlopen(req, context=self.ctx, timeout=10) as resp:
            first = resp.readline()
            self.assertLess(time.time() - start, 0.15)               # erste Zeile kommt sofort, nicht erst am Ende
            self.assertEqual(json.loads(first), {"i": 0})
            self.assertEqual(json.loads(resp.read()), {"i": 1})
        self.assertEqual(_FakeOllama.seen["body"], b'{"model":"x"}')
        self.assertNotIn("Origin", _FakeOllama.seen["headers"])      # sonst lehnt Ollama fremde Herkunft ab
        self.assertNotIn("Referer", _FakeOllama.seen["headers"])

    def test_proxy_off_without_upstream(self):
        self.ctl.start(self.dir.name, self.port, tls=self.paths)
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self.open("/api/tags")
        self.assertEqual(cm.exception.code, 404)

    def test_proxy_bad_gateway_message(self):
        self.ctl.start(self.dir.name, self.port, tls=self.paths, upstream="127.0.0.1:%d" % free_port())
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self.open("/api/tags")
        self.assertEqual(cm.exception.code, 502)
        self.assertIn("nicht erreichbar", json.loads(cm.exception.read())["error"])

    def test_plain_http_on_tls_port_does_not_break_server(self):
        self.ctl.start(self.dir.name, self.port, tls=self.paths)
        with self.assertRaises(Exception):
            urllib.request.urlopen("http://127.0.0.1:%d/" % self.port, timeout=3)
        with self.open("/") as resp:                                 # Server läuft danach normal weiter
            self.assertEqual(resp.status, 200)


class IconTests(unittest.TestCase):
    def test_icon(self):
        from mini_webserver.utils.icon import make_icon
        for running in (True, False):
            self.assertEqual(make_icon(running, 32).size, (32, 32))


if __name__ == "__main__":
    unittest.main()
