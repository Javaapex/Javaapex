"""Smoke test for the Tomcat-container deploy path (External validation).

Validates the new helpers added to FunctionalTestPipelineService without
requiring a real Docker engine:

  1. _find_gradle_war_module  — detects the ``war`` subproject + task prefix
  2. _find_built_war          — picks the largest built *.war
  3. _wait_for_http_ready     — True vs a live server, False vs a dead port
  4. _start_war_in_tomcat_container — graceful skip when Docker is unavailable
  5. … graceful skip when the WAR cannot be built
  6. … happy path: correct ``docker run`` command shape + success dict

Run:  C:/Python314/python.exe scripts/tomcat_deploy_smoketest.py
"""
from __future__ import annotations

import asyncio
import socket
import sys
import tempfile
import threading
import types
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Stub the `services` package so importing the module does not run services/__init__
# (which imports PyGithub, not installed in this interpreter).
_stub = types.ModuleType("services")
_stub.__path__ = [str(ROOT / "services")]  # type: ignore[attr-defined]
sys.modules["services"] = _stub

from services.functional_test_pipeline import FunctionalTestPipelineService  # noqa: E402

svc = FunctionalTestPipelineService()
results: list[tuple[str, bool, str]] = []


# ── Test 1: _find_gradle_war_module ──────────────────────────────────────────
proj = Path(tempfile.mkdtemp(prefix="warmod_"))
(proj / "build.gradle").write_text("// root project\n", encoding="utf-8")
warmod = proj / "PinnacleToolsWAR"
warmod.mkdir()
(warmod / "build.gradle").write_text("apply plugin: 'war'\n", encoding="utf-8")
mod, prefix = svc._find_gradle_war_module(proj)
ok1 = mod == warmod and prefix == ":PinnacleToolsWAR"
results.append(("find_gradle_war_module", ok1, f"mod={mod}, prefix={prefix!r}"))


# ── Test 2: _find_built_war picks the largest WAR under build/libs ───────────
libs = warmod / "build" / "libs"
libs.mkdir(parents=True)
(libs / "small.war").write_bytes(b"x" * 10)
(libs / "app.war").write_bytes(b"x" * 5000)
war = svc._find_built_war(proj)
ok2 = war is not None and war.name == "app.war"
results.append(("find_built_war_largest", ok2, f"war={war}"))


# ── Test 3: _wait_for_http_ready against a LIVE server returns True ──────────
class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"<html><body>First Page............</body></html>")

    def log_message(self, *_a):  # silence
        pass


httpd = HTTPServer(("127.0.0.1", 0), _Handler)
live_port = httpd.server_address[1]
threading.Thread(target=httpd.serve_forever, daemon=True).start()
ok3 = asyncio.run(
    svc._wait_for_http_ready(f"http://127.0.0.1:{live_port}", timeout_sec=10, settle_sec=0.0)
)
httpd.shutdown()
results.append(("wait_for_http_ready_live", ok3, f"port={live_port}"))


# ── Test 4: _wait_for_http_ready against a DEAD port returns False ───────────
_s = socket.socket()
_s.bind(("127.0.0.1", 0))
dead_port = _s.getsockname()[1]
_s.close()
ok4 = asyncio.run(
    svc._wait_for_http_ready(f"http://127.0.0.1:{dead_port}", timeout_sec=3, settle_sec=0.0)
) is False
results.append(("wait_for_http_ready_dead", ok4, f"dead_port={dead_port}"))


# ── Test 5: graceful skip when Docker is unavailable ─────────────────────────
async def _no_docker() -> bool:
    return False


svc._is_docker_available = _no_docker  # type: ignore[assignment]
profile = {"runtime": {"allocatedPort": 12345}}
res5 = asyncio.run(svc._start_war_in_tomcat_container(proj, profile))
ok5 = res5.get("started") is False and "Docker is not available" in res5.get("message", "")
results.append(("tomcat_no_docker_graceful", ok5, res5.get("message", "")))


# ── Test 6: graceful skip when the WAR cannot be built ───────────────────────
async def _yes_docker() -> bool:
    return True


async def _no_war(_root, _profile):
    return None


svc._is_docker_available = _yes_docker  # type: ignore[assignment]
svc._build_war_file = _no_war  # type: ignore[assignment]
res6 = asyncio.run(svc._start_war_in_tomcat_container(proj, profile))
ok6 = res6.get("started") is False and "Could not build a WAR" in res6.get("message", "")
results.append(("tomcat_no_war_graceful", ok6, res6.get("message", "")))


# ── Test 7: happy path — correct docker run command + success dict ───────────
captured: dict[str, list] = {}
fake_war = libs / "app.war"


async def _build_ok(_root, _profile):
    return fake_war


async def _run_capture(cmd, cwd, timeout_sec, tool, extra_env=None):
    captured[tool] = cmd
    return {"exit_code": 0, "output": "containerid123\n", "output_tail": ""}


async def _ready(_base_url, _timeout_sec, settle_sec=3.0):
    return True


svc._is_docker_available = _yes_docker      # type: ignore[assignment]
svc._build_war_file = _build_ok             # type: ignore[assignment]
svc._run_command = _run_capture             # type: ignore[assignment]
svc._wait_for_http_ready = _ready           # type: ignore[assignment]

profile7 = {"runtime": {"allocatedPort": 23456}}
res7 = asyncio.run(svc._start_war_in_tomcat_container(proj, profile7))
run_cmd = captured.get("TOMCAT_RUN", [])
ok7 = (
    res7.get("started") is True
    and bool(res7.get("_container_id"))
    and "-p" in run_cmd
    and "23456:8080" in run_cmd
    and any("ROOT.war" in str(x) for x in run_cmd)
    and any(str(fake_war) in str(x) for x in run_cmd)
    and res7.get("baseUrl") == "http://localhost:23456"
    and run_cmd[:3] == ["docker", "run", "-d"]
)
results.append(("tomcat_happy_path_cmd", ok7, f"image={run_cmd[-1] if run_cmd else '-'}"))


# ── Report ───────────────────────────────────────────────────────────────────
print()
passed = 0
for name, ok, detail in results:
    status = "PASS" if ok else "FAIL"
    if ok:
        passed += 1
    print(f"[{status}] {name}\n        {detail}")

print()
if passed == len(results):
    print(f"ALL {len(results)} CASES PASSED")
    raise SystemExit(0)
print(f"{len(results) - passed} of {len(results)} CASES FAILED")
raise SystemExit(1)
