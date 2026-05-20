#!/usr/bin/env bash
# remote_cpu_capture.sh — deployed to /opt/bench/ on VPS A by lead.
#
# Called from VPS B during tcp_t / tcp_p runs (one call per run):
#   ssh root@VPS_A /opt/bench/remote_cpu_capture.sh <scenario> <metric> <run>
#
# Output file: ${BENCH_CPU_TMP_DIR:-/tmp}/cpu-<scenario>-<metric>-run<N>.txt
# VPS B rsyncs these back after each scenario completes.
# BENCH_CPU_TMP_DIR can be set to a writable path for local testing.

set -euo pipefail

scenario="${1:?Usage: remote_cpu_capture.sh <scenario> <metric> <run>}"
metric="${2:?}"
run="${3:?}"
out="${BENCH_CPU_TMP_DIR:-/tmp}/cpu-${scenario}-${metric}-run${run}.txt"

case "$scenario" in
    wg-plain|wg-2fa)
        mpstat -P ALL 1 60 > "$out"
        ;;
    openvpn)
        # Pattern keys on '--config ovpn-bench.conf' arg, not the systemd unit name.
        # The unit is 'openvpn-server@ovpn-bench' but the process cmdline is:
        #   /usr/sbin/openvpn --status .../status-ovpn-bench.log ... --config ovpn-bench.conf
        # 'ovpn-bench\.conf' is the narrowest correct match: the .conf suffix
        # distinguishes '--config ovpn-bench.conf' from '--status ...ovpn-bench.log'.
        _pgrep_out=$(pgrep -f 'ovpn-bench\.conf' 2>/dev/null || true)
        if [[ -z "$_pgrep_out" ]]; then
            echo "ERROR: openvpn process not found (pgrep -f 'ovpn-bench\\.conf' returned no PIDs)" >&2
            echo "Diagnostic: run 'ps -ef | grep openvpn' on VPS A to confirm openvpn-server@ovpn-bench is up" >&2
            exit 1
        fi
        _pid_count=$(echo "$_pgrep_out" | wc -l)
        if [[ $_pid_count -gt 1 ]]; then
            echo "ERROR: expected exactly one process matching 'ovpn-bench\\.conf', found ${_pid_count}:" >&2
            echo "$_pgrep_out" | while read -r p; do echo "  PID $p" >&2; done
            exit 1
        fi
        pid="$_pgrep_out"
        pidstat -p "$pid" 1 60 > "$out"
        ;;
    no-vpn)
        ;;
    *)
        echo "ERROR: unknown scenario: $scenario" >&2
        exit 1
        ;;
esac
