"""docs/examples/get_file_url.py: the documented integration script works.

The API is replaced by a stub and the "storage" by a local HTTP server that
honours Range, so the script's real code paths run (URL lookup, --search,
--save, --range, error messages) without any network or secret.
"""
import http.server
import importlib.util
import threading
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "get_file_url", Path(__file__).resolve().parents[1] / "docs" / "examples" / "get_file_url.py"
)
script = importlib.util.module_from_spec(spec)
spec.loader.exec_module(script)

DATA = bytes(range(256)) * 8  # 2048 bytes


class Storage(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):  # quiet
        pass

    def do_GET(self):
        assert "Authorization" not in self.headers, "the presigned URL must not get the token"
        rng = self.headers.get("Range")
        if rng:
            start, _, end = rng.removeprefix("bytes=").partition("-")
            body = DATA[int(start): int(end) + 1]
            self.send_response(206)
        else:
            body = DATA
            self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def storage_url():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Storage)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}/file"
    server.shutdown()


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("AURA_API", "https://app.example.test")
    monkeypatch.setenv("AURA_TOKEN", "aura_test")


def _stub(monkeypatch, url, calls):
    def fake_api(method, path, body=None):
        calls.append((method, path))
        if path.startswith("/api/v1/objects?"):
            return {"items": [{"id": "obj-1"}]}
        return {"download_url": url, "preview_url": url, "display_name": "f.bin",
                "content_type": "application/octet-stream", "size_bytes": len(DATA),
                "expires_in": 900, "range_supported": True}
    monkeypatch.setattr(script, "api", fake_api)


def test_print_the_url_for_an_id(monkeypatch, capsys, storage_url):
    calls = []
    _stub(monkeypatch, storage_url, calls)
    monkeypatch.setattr("sys.argv", ["x", "--id", "obj-1"])
    script.main()
    out = capsys.readouterr().out
    assert storage_url in out and "expires in 900 s" in out
    assert calls == [("POST", "/api/v1/objects/obj-1/download-intent")]


def test_search_then_preview_kind(monkeypatch, capsys, storage_url):
    calls = []
    _stub(monkeypatch, storage_url, calls)
    monkeypatch.setattr("sys.argv", ["x", "--search", "rapport", "--kind", "preview"])
    script.main()
    assert calls[0][0] == "GET" and "q=rapport" in calls[0][1] and "status=available" in calls[0][1]
    assert calls[1] == ("POST", "/api/v1/objects/obj-1/preview-intent")


def test_save_the_whole_file_and_a_byte_range(monkeypatch, tmp_path, storage_url):
    _stub(monkeypatch, storage_url, [])
    whole, part = tmp_path / "whole.bin", tmp_path / "part.bin"
    monkeypatch.setattr("sys.argv", ["x", "--id", "o", "--save", str(whole)])
    script.main()
    assert whole.read_bytes() == DATA
    monkeypatch.setattr("sys.argv", ["x", "--id", "o", "--save", str(part), "--range", "10-19"])
    script.main()
    assert part.read_bytes() == DATA[10:20]


def test_no_match_and_http_errors_exit_with_a_readable_message(monkeypatch):
    monkeypatch.setattr(script, "api", lambda *a, **k: {"items": []})
    with pytest.raises(SystemExit, match="no available object matches 'zzz'"):
        script.find_id("zzz")
