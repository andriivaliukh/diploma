#!/usr/bin/env bash
# remote_cpu_capture.sh — deployed to /opt/bench/ on VPS A by lead.
#
# Called from VPS B during tcp_t runs (one call per run):
#   ssh root@VPS_A /opt/bench/remote_cpu_capture.sh <scenario> tcp_t <run>
#
# Output file: /tmp/cpu-<scenario>-tcp_t-run<N>.txt
# VPS B rsyncs these back after each scenario completes.

set -euo pipefail

scenario="${1:?Usage: remote_cpu_capture.sh <scenario> <metric> <run>}"
metric="${2:?}"
run="${3:?}"
out="/tmp/cpu-${scenario}-${metric}-run${run}.txt"

case "$scenario" in
    wg-plain|wg-2fa)
        mpstat -P ALL 1 60 > "$out"
        ;;
    openvpn)
        pid=$(pgrep -f "openvpn-bench" | head -1 || true)
        if [[ -z "$pid" ]]; then
            echo "ERROR: openvpn-bench process not found on VPS A" >&2
            exit 1
        fi
        pidstat -p "$pid" 1 60 > "$out"
        ;;
    no-vpn)
        ;;
    *)
        echo "ERROR: unknown scenario: $scenario" >&2
        exit 1
        ;;
esac
