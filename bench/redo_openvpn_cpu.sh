#!/usr/bin/env bash
# redo_openvpn_cpu.sh — targeted re-run to capture the 10 missing openvpn
# CPU sidecar files (5 x tcp_t + 5 x tcp_p) caused by the pgrep defect in
# remote_cpu_capture.sh (pattern 'openvpn-bench' vs actual 'ovpn-bench.conf').
#
# Writes ONLY cpu-openvpn-{tcp_t,tcp_p}-run{1..N}.txt to data/benchmarks/.
# Does NOT overwrite any existing throughput rows in results.csv.
# iperf3 is called directly (NOT via run_tcp_t/run_tcp_p) to prevent those
# metric-function side-effects (primary-raw files, JSON sidecars, CSV rows).
#
# Usage (from VPS B, after deploying the patched remote_cpu_capture.sh):
#   ./bench/redo_openvpn_cpu.sh
#
# Env overrides:
#   BENCH_N       number of runs per metric (default 5)
#   BENCH_N=1     useful as a 2-metric dry-run before the full 10-run campaign

set -uo pipefail

BENCH_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$BENCH_DIR/.." && pwd)"
DATA_DIR="$REPO_DIR/data/benchmarks"
RESULTS_CSV="$DATA_DIR/results.csv"
VPS_A="root@81.27.101.178"
N="${BENCH_N:-5}"
PYTHON3="${BENCH_PYTHON3:-python3}"

SRV=""

source "$BENCH_DIR/lib/scenarios.sh"

log()  { printf '[%s] %s\n' "$(date -u +%H:%M:%S)" "$*" >&2; }
die()  { log "ERROR: $*"; exit 1; }

CURRENT_SCENARIO=""

cleanup_on_exit() {
    if [[ -n "$CURRENT_SCENARIO" ]]; then
        log "EXIT trap: tearing down $CURRENT_SCENARIO"
        teardown_scenario "$CURRENT_SCENARIO" 2>/dev/null || true
        CURRENT_SCENARIO=""
    fi
}
trap cleanup_on_exit EXIT

run_cpu_only() {
    local metric="$1" run="$2" parallel="$3"
    log "  openvpn / $metric / run $run"

    local cpu_raw="$DATA_DIR/cpu-openvpn-${metric}-run${run}.txt"
    if [[ -f "$cpu_raw" ]]; then
        log "  SKIP: $cpu_raw already exists — not overwriting"
        return 0
    fi

    local ssh_pid
    ssh "$VPS_A" "/opt/bench/remote_cpu_capture.sh openvpn ${metric} ${run}" &
    ssh_pid=$!

    # iperf3 called directly — stdout discarded so no primary-raw file is
    # written and run_tcp_t/run_tcp_p side-effects (JSON sidecar, CSV row)
    # cannot fire.  This is the load generator; the CPU capture is on VPS A.
    iperf3 -c "$SRV" -t 60 -P "$parallel" >/dev/null 2>&1 \
        || log "  WARN: iperf3 exited non-zero for $metric run $run"

    if ! wait "$ssh_pid"; then
        die "remote_cpu_capture.sh failed for openvpn $metric run $run — check VPS A"
    fi
}

main() {
    mkdir -p "$DATA_DIR"

    log "=== redo_openvpn_cpu: setting up openvpn tunnel ==="
    setup_openvpn || die "setup_openvpn failed"
    CURRENT_SCENARIO="openvpn"

    local run
    for run in $(seq 1 "$N"); do
        run_cpu_only "tcp_t" "$run" 1
    done
    for run in $(seq 1 "$N"); do
        run_cpu_only "tcp_p" "$run" 4
    done

    log "=== redo_openvpn_cpu: rsyncing CPU files from VPS A ==="
    rsync "${VPS_A}:/tmp/cpu-openvpn-*.txt" "$DATA_DIR/" 2>/dev/null \
        || log "WARN: rsync returned non-zero — check VPS A /tmp/ for cpu-openvpn-*.txt"

    teardown_scenario "openvpn"
    CURRENT_SCENARIO=""

    log "=== redo_openvpn_cpu: summarizing CPU files ==="
    local cpu_metric cpu_raw
    for cpu_metric in cpu_tcp_t cpu_tcp_p; do
        for run in $(seq 1 "$N"); do
            cpu_raw="$DATA_DIR/cpu-openvpn-${cpu_metric#cpu_}-run${run}.txt"
            if [[ -f "$cpu_raw" ]]; then
                if ! $PYTHON3 "$BENCH_DIR/lib/summarize.py" \
                        "$cpu_raw" "openvpn" "$cpu_metric" "$run" \
                        >> "$RESULTS_CSV"; then
                    log "WARN: summarize failed for openvpn/$cpu_metric run $run"
                fi
            else
                log "WARN: $cpu_raw not found after rsync"
            fi
        done
    done

    log "Done. openvpn CPU rows appended to $RESULTS_CSV"
}

main "$@"
