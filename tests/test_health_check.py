import json
import subprocess
import sys
import os
import time
import tempfile


def _run_healthcheck(env: dict[str, str]) -> subprocess.CompletedProcess:
    # Run the health-check via module invocation using the current python executable
    cmd = [sys.executable, "-m", "src.main", "--health-check"]
    merged = os.environ.copy()
    merged.update(env)
    return subprocess.run(cmd, env=merged, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def test_health_check_pass(tmp_path):
    status_file = tmp_path / "status.json"
    now = time.time()
    data = {
        "last_maintenance": now,
        "last_reconnect_ok": now,
        "consecutive_reconnect_failures": 0,
    }
    status_file.write_text(json.dumps(data))

    res = _run_healthcheck({"TWITCH_HEALTH_STATUS_FILE": str(status_file)})
    assert res.returncode == 0, f"healthcheck failed unexpectedly: {res.stderr.decode()!r}"


def test_health_check_fail_on_failures(tmp_path):
    status_file = tmp_path / "status.json"
    data = {"consecutive_reconnect_failures": 5}
    status_file.write_text(json.dumps(data))

    # Set threshold low to ensure failure
    res = _run_healthcheck(
        {
            "TWITCH_HEALTH_STATUS_FILE": str(status_file),
            "TWITCH_HEALTH_MAX_RECONNECT_FAILURES": "3",
        }
    )
    assert res.returncode != 0, "healthcheck unexpectedly passed despite failures"


def test_health_check_fail_on_stale_maintenance(tmp_path):
    status_file = tmp_path / "status.json"
    now = time.time()
    data = {"last_maintenance": now - 3600}
    status_file.write_text(json.dumps(data))

    res = _run_healthcheck(
        {"TWITCH_HEALTH_STATUS_FILE": str(status_file), "TWITCH_HEALTH_STALE_SECONDS": "10"}
    )
    assert res.returncode != 0, "healthcheck unexpectedly passed despite stale maintenance"


def test_health_check_fail_on_stale_last_ok(tmp_path):
    status_file = tmp_path / "status.json"
    now = time.time()
    data = {"last_reconnect_ok": now - 3600}
    status_file.write_text(json.dumps(data))

    res = _run_healthcheck(
        {"TWITCH_HEALTH_STATUS_FILE": str(status_file), "TWITCH_HEALTH_STALE_SECONDS": "10"}
    )
    assert res.returncode != 0, "healthcheck unexpectedly passed despite stale last_reconnect_ok"
