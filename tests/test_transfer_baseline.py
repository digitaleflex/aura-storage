"""scripts/transfer-baseline.py: log parsing on synthetic lines (offline)."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "transfer_baseline", Path(__file__).resolve().parents[1] / "scripts" / "transfer-baseline.py"
)
tb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tb)

MIB = 1024 * 1024


def _commit(n, size, hash_ms, total_ms):
    return (f"INFO commit timings oid=o{n} bytes={size} head_ms=5.0 "
            f"hash_ms={hash_ms} total_ms={total_ms}")


def test_commit_buckets_and_reread_rate():
    lines = [_commit(i, 10 * MIB, 100.0, 120.0) for i in range(4)]  # 100 MiB/s
    lines += [_commit(9, 500 * MIB, 5000.0, 5100.0), "unrelated line"]
    out = tb.summarize_commits(lines)
    assert out["count"] == 5
    small = next(b for b in out["buckets"] if b["label"] == "1-32 MiB")
    assert small["n"] == 4 and round(small["reread_mib_s"]) == 100
    big = next(b for b in out["buckets"] if b["label"] == ">= 256 MiB")
    assert big["n"] == 1 and big["hash_p95_ms"] == 5000.0


def test_proxy_flags_killed_and_very_long_puts_only():
    lines = [
        '1.2.3.4 - - [22/Oct/2026:10:00:00 +0000] "PUT /aura/a?X-Amz=1 HTTP/2.0" 200 0 "-" "-" 7 "s3@docker" "http://x" 4000ms',
        '1.2.3.4 - - [22/Oct/2026:10:00:00 +0000] "PUT /aura/b HTTP/2.0" 499 0 "-" "-" 8 "s3@docker" "http://x" 1200000ms',
        '1.2.3.4 - - [22/Oct/2026:10:00:00 +0000] "PUT /aura/c HTTP/2.0" 200 0 "-" "-" 9 "s3@docker" "http://x" 1150000ms',
        '1.2.3.4 - - [22/Oct/2026:10:00:00 +0000] "GET /aura/d HTTP/2.0" 502 0 "-" "-" 3 "s3@docker" "http://x" 9ms',
    ]
    out = tb.summarize_proxy(lines, 1100.0)
    assert out["puts"] == 3  # the GET is ignored
    assert [(p, s) for p, s, _ in out["cut"]] == [("/aura/b", 499), ("/aura/c", 200)]
    assert out["duration_max_s"] == 1200.0


def test_throttling_lines_are_counted():
    assert tb.count_throttling(["ok", "ClientError: SlowDown", "ThrottlingException x"]) == 2


def test_render_handles_empty_input():
    text = tb.render(tb.summarize_commits([]), tb.summarize_proxy([], 1100.0), 0, 1100.0)
    assert "no 'commit timings' line found" in text
