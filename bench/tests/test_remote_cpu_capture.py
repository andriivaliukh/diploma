"""Tests for remote_cpu_capture.sh openvpn CPU capture pgrep pattern.

pgrep -f does ERE matching against the full /proc/<pid>/cmdline string.
These tests validate pattern correctness and script behaviour (happy / zero
/ multi-PID paths) against the known-good cmdline captured from VPS A while
openvpn-server@ovpn-bench was active:

  /usr/sbin/openvpn --status /run/openvpn-server/status-ovpn-bench.log
    --status-version 2 --suppress-timestamps --config ovpn-bench.conf

Root cause of the campaign defect: the pre-fix pattern 'openvpn-bench' does
not appear in that cmdline.  The correct pattern keys on '--config ovpn-bench.conf'.
"""

import os
import re
import subprocess
from pathlib import Path

import pytest

OPENVPN_BENCH_CMDLINE = (
    "/usr/sbin/openvpn "
    "--status /run/openvpn-server/status-ovpn-bench.log "
    "--status-version 2 --suppress-timestamps "
    "--config ovpn-bench.conf"
)
OTHER_OPENVPN_CMDLINE = "/usr/sbin/openvpn --config /etc/openvpn/other.conf"

_SCRIPT = Path(__file__).parent.parent / "remote" / "remote_cpu_capture.sh"


def _script_openvpn_pgrep_pattern() -> str:
    """Extract the pgrep -f pattern from the openvpn case in the script."""
    content = _SCRIPT.read_text()
    m = re.search(r"pgrep\s+-f\s+['\"]([^'\"]+)['\"]", content)
    assert m, f"No 'pgrep -f <pattern>' found in {_SCRIPT}"
    return m.group(1)


def _make_mock_env(tmp_path: Path, pgrep_stdout: str, pgrep_exit: int = 0) -> dict:
    """Return an env dict with PATH prepended by a bin/ dir containing mock tools.

    pgrep mock outputs pgrep_stdout verbatim and exits with pgrep_exit.
    pidstat and mpstat mocks are no-ops (exit 0).
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)

    escaped = pgrep_stdout.replace("'", "'\\''")
    (bin_dir / "pgrep").write_text(
        f"#!/usr/bin/env bash\nprintf '%s' '{escaped}'\nexit {pgrep_exit}\n"
    )
    (bin_dir / "pgrep").chmod(0o755)

    for cmd in ("pidstat", "mpstat"):
        (bin_dir / cmd).write_text("#!/usr/bin/env bash\nexit 0\n")
        (bin_dir / cmd).chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"
    return env


def _run_script(
    tmp_path: Path,
    scenario: str,
    metric: str,
    run: str,
    pgrep_stdout: str,
    pgrep_exit: int = 0,
) -> subprocess.CompletedProcess:
    env = _make_mock_env(tmp_path, pgrep_stdout, pgrep_exit)
    return subprocess.run(
        ["bash", str(_SCRIPT), scenario, metric, run],
        capture_output=True,
        text=True,
        env=env,
    )


# ---------------------------------------------------------------------------
# Pattern correctness — pure Python, no subprocess
# ---------------------------------------------------------------------------


def test_old_pattern_absent_from_script():
    """The broken 'openvpn-bench' literal must be gone from the script."""
    assert "openvpn-bench" not in _SCRIPT.read_text(), (
        "Script still uses the old 'openvpn-bench' pgrep pattern "
        "which does not appear in the actual openvpn-server@ovpn-bench cmdline"
    )


def test_pgrep_pattern_matches_actual_cmdline():
    """The script's pgrep -f pattern must hit the '--config ovpn-bench.conf' arg."""
    pattern = _script_openvpn_pgrep_pattern()
    assert re.search(pattern, OPENVPN_BENCH_CMDLINE), (
        f"Pattern '{pattern}' does not match actual cmdline: {OPENVPN_BENCH_CMDLINE}"
    )


def test_pgrep_pattern_does_not_match_other_openvpn():
    """Pattern must not match an unrelated openvpn instance."""
    pattern = _script_openvpn_pgrep_pattern()
    assert not re.search(pattern, OTHER_OPENVPN_CMDLINE), (
        f"Pattern '{pattern}' over-matches: {OTHER_OPENVPN_CMDLINE}"
    )


# ---------------------------------------------------------------------------
# Script behaviour — openvpn case
# ---------------------------------------------------------------------------


@pytest.mark.skip(
    reason="Script writes to /tmp/ which is sandbox-restricted locally. "
    "Enabled in the impl commit after BENCH_CPU_TMP_DIR support is added to the script."
)
def test_openvpn_happy_path_exits_zero(tmp_path):
    """One PID returned by pgrep → script exits 0 and runs pidstat."""
    result = _run_script(tmp_path, "openvpn", "tcp_t", "1",
                         pgrep_stdout="12345\n", pgrep_exit=0)
    assert result.returncode == 0, f"stderr: {result.stderr}"


@pytest.mark.skip(
    reason="Script writes to /tmp/ which is sandbox-restricted locally. "
    "Enabled in the impl commit after BENCH_CPU_TMP_DIR support is added to the script."
)
def test_openvpn_zero_pids_exits_nonzero_with_message(tmp_path):
    """No PID returned (pgrep exit 1) → script exits non-zero with diagnostic."""
    result = _run_script(tmp_path, "openvpn", "tcp_t", "1",
                         pgrep_stdout="", pgrep_exit=1)
    assert result.returncode != 0
    combined = result.stderr + result.stdout
    assert "not found" in combined.lower() or "expected" in combined.lower(), (
        f"Missing diagnostic message in output: {combined!r}"
    )


@pytest.mark.skip(
    reason="Script writes to /tmp/ which is sandbox-restricted locally. "
    "Enabled in the impl commit after BENCH_CPU_TMP_DIR support is added to the script."
)
def test_openvpn_multi_pids_exits_nonzero_listing_all_pids(tmp_path):
    """Multiple PIDs returned → script exits non-zero and lists all matched PIDs."""
    result = _run_script(tmp_path, "openvpn", "tcp_t", "1",
                         pgrep_stdout="12345\n67890\n", pgrep_exit=0)
    assert result.returncode != 0, (
        f"Expected non-zero exit for multi-PID case; returncode={result.returncode}"
    )
    assert "12345" in result.stderr, f"PID 12345 not listed in stderr: {result.stderr!r}"
    assert "67890" in result.stderr, f"PID 67890 not listed in stderr: {result.stderr!r}"
