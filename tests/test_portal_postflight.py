"""scripts/portal-postflight.sh against a real API process.

The script is what stops a deploy whose public portal is stale or unrouted, so it
is exercised end to end: a healthy API passes, and each kind of breakage fails with
a message that names it. No Docker or TLS: the script is pointed at a local uvicorn
through its documented overrides.
"""
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "portal-postflight.sh"
DOMAIN = "portail.test"

pytestmark = pytest.mark.skipif(
    not (shutil.which("bash") and shutil.which("curl")), reason="bash and curl are required",
)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def api():
    port = _free_port()
    env = {k: v for k, v in os.environ.items() if not k.startswith("AURA_API_")}
    env.update({
        "AURA_API_ADMIN_PASSWORD": "ci-dummy-password", "AURA_API_DB": ":memory:",
        "AURA_S3_ACCESS_KEY": "ci-dummy-access-key-1234",
        "AURA_S3_SECRET_KEY": "ci-dummy-secret-12345678901234567890",
        "AURA_S3_ENDPOINT": "https://127.0.0.1:9", "AURA_COOKIE_SECURE": "0",
        "PUBLIC_DOMAIN": DOMAIN,
    })
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "api.main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(100):
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
                break
            except OSError:
                time.sleep(0.2)
        else:
            pytest.fail("the API did not start")
        yield port
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def _run(port, host=DOMAIN, asset_dir=None):
    env = {
        **os.environ, "PORTAL_CHECK_BASE": f"http://127.0.0.1:{port}",
        "PORTAL_CHECK_CURL_ARGS": f"-H Host:{host}", "PORTAL_CHECK_TIMEOUT": "3",
        "PUBLIC_DOMAIN": DOMAIN,
    }
    if asset_dir:
        env["PORTAL_CHECK_ASSET_DIR"] = str(asset_dir)
    return subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=60)


def test_a_healthy_portal_passes_every_check(api):
    r = _run(api)
    assert r.returncode == 0, r.stderr
    assert "Portal verified" in r.stdout


def test_a_stale_container_is_caught_by_the_stylesheet_hash(api, tmp_path):
    shutil.copy(ROOT / "api" / "portal_assets" / "portal.css", tmp_path / "portal.css")
    with open(tmp_path / "portal.css", "a", encoding="utf-8") as f:
        f.write("/* the checkout moved on, the container did not */\n")
    r = _run(api, asset_dir=tmp_path)
    assert r.returncode == 1
    assert "differs from the checkout" in r.stderr and "stale" in r.stderr


def test_a_host_the_portal_does_not_answer_fails_with_the_status_seen(api):
    r = _run(api, host="autre.test")
    assert r.returncode == 1
    assert "did not answer 200" in r.stderr and "404" in r.stderr


def test_a_missing_reference_file_fails_instead_of_passing(api, tmp_path):
    r = _run(api, asset_dir=tmp_path)  # empty directory
    assert r.returncode == 1 and "reference file" in r.stderr


def test_nothing_listening_fails_after_the_wait():
    r = _run(_free_port())
    assert r.returncode == 1 and "did not answer 200" in r.stderr


def test_the_domain_is_required_when_no_override_is_given():
    env = {k: v for k, v in os.environ.items() if not k.startswith("PORTAL_CHECK_")}
    env.pop("PUBLIC_DOMAIN", None)
    r = subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=30)
    assert r.returncode == 1 and "PUBLIC_DOMAIN is not set" in r.stderr


def test_deploy_runs_the_portal_postflight_last():
    deploy = (ROOT / "scripts" / "deploy.sh").read_text(encoding="utf-8")
    assert deploy.rstrip().endswith('bash "${ROOT_DIR}/scripts/portal-postflight.sh"')
    assert deploy.index("Bundle verified") < deploy.index("portal-postflight.sh")
