#!/usr/bin/env bash
# scenarios.sh — setup_<scenario> / teardown_<scenario> / SRV resolution.
# Sourced by run.sh.  Each setup sets the exported SRV variable.

SRV=""

# ---------------------------------------------------------------------------
# no-vpn — raw inter-DC baseline; no tunnel
# ---------------------------------------------------------------------------

setup_no_vpn() {
    log "pre-flight [no-vpn]: checking reachability to 81.27.101.178"
    if ! ping -c 1 -W 2 81.27.101.178 >/dev/null 2>&1; then
        die "no-vpn pre-flight failed: cannot reach 81.27.101.178"
    fi
    SRV="81.27.101.178"
    export SRV
    log "no-vpn ready, SRV=$SRV"
}

teardown_no_vpn() {
    SRV=""
}

# ---------------------------------------------------------------------------
# wg-plain — kernel WireGuard, no auth
# ---------------------------------------------------------------------------

setup_wg_plain() {
    wg-quick down wg-bench 2>/dev/null || true

    local start_ns
    start_ns=$(date +%s%N)

    log "pre-flight [wg-plain]: bringing up wg-bench"
    if ! wg-quick up wg-bench; then
        die "wg-plain: wg-quick up wg-bench failed"
    fi

    # Trigger initial handshake; ignore failure (peer may not reply to first ping)
    ping -c 1 -W 5 10.99.0.1 >/dev/null 2>&1 || true

    local hs_ts now age
    hs_ts=$(wg show wg-bench latest-handshakes | awk 'NR==1 {print $2}')
    now=$(date +%s)
    age=$(( now - ${hs_ts:-0} ))
    if [[ ${hs_ts:-0} -eq 0 || $age -gt 60 ]]; then
        wg-quick down wg-bench 2>/dev/null || true
        die "wg-plain pre-flight failed: no fresh handshake (age=${age}s)"
    fi

    local end_ns
    end_ns=$(date +%s%N)
    ONBOARD_MS=$(( (end_ns - start_ns) / 1000000 ))
    SRV="10.99.0.1"
    export SRV ONBOARD_MS
    log "wg-plain ready, SRV=$SRV, ONBOARD_MS=${ONBOARD_MS}ms"
}

teardown_wg_plain() {
    wg-quick down wg-bench 2>/dev/null || true
    SRV=""
}

# ---------------------------------------------------------------------------
# wg-2fa — this thesis's stack (WG + 2FA via vpncli)
# ---------------------------------------------------------------------------

setup_wg_2fa() {
    echo "STUB: setup_wg_2fa not yet implemented" >&2
    return 1
}

teardown_wg_2fa() {
    echo "STUB: teardown_wg_2fa not yet implemented" >&2
    return 0
}

# ---------------------------------------------------------------------------
# openvpn — static-key AES-256-CBC + SHA256, UDP 1194
# ---------------------------------------------------------------------------

setup_openvpn() {
    pkill -f 'openvpn.*bench' 2>/dev/null || true
    sleep 1

    local ovpn_conf="/etc/openvpn/bench.conf"
    if [[ ! -f "$ovpn_conf" ]]; then
        die "openvpn: config not found: $ovpn_conf"
    fi

    local start_ns
    start_ns=$(date +%s%N)

    log "pre-flight [openvpn]: starting openvpn with $ovpn_conf"
    openvpn --config "$ovpn_conf" --daemon --log /tmp/openvpn-bench.log \
        || die "openvpn: failed to start daemon"

    local i
    for i in $(seq 1 30); do
        if ip -4 addr show tun0 2>/dev/null | grep -q '10\.99\.1\.2'; then
            break
        fi
        sleep 1
    done

    if ! ip -4 addr show tun0 2>/dev/null | grep -q '10\.99\.1\.2'; then
        pkill -f 'openvpn.*bench' 2>/dev/null || true
        die "openvpn pre-flight failed: tun0 10.99.1.2 not assigned after 30s"
    fi

    if ! ping -c 1 -W 5 10.99.1.1 >/dev/null 2>&1; then
        pkill -f 'openvpn.*bench' 2>/dev/null || true
        die "openvpn pre-flight failed: cannot ping 10.99.1.1"
    fi

    local end_ns
    end_ns=$(date +%s%N)
    ONBOARD_MS=$(( (end_ns - start_ns) / 1000000 ))
    SRV="10.99.1.1"
    export SRV ONBOARD_MS
    log "openvpn ready, SRV=$SRV, ONBOARD_MS=${ONBOARD_MS}ms"
}

teardown_openvpn() {
    pkill -f 'openvpn.*bench' 2>/dev/null || true
    sleep 1
    SRV=""
}

# ---------------------------------------------------------------------------
# Dispatcher helpers (called from run.sh to avoid hyphens in function names)
# ---------------------------------------------------------------------------

setup_scenario() {
    case "$1" in
        no-vpn)   setup_no_vpn ;;
        wg-plain) setup_wg_plain ;;
        wg-2fa)   setup_wg_2fa ;;
        openvpn)  setup_openvpn ;;
        *) die "unknown scenario: $1" ;;
    esac
}

teardown_scenario() {
    case "$1" in
        no-vpn)   teardown_no_vpn ;;
        wg-plain) teardown_wg_plain ;;
        wg-2fa)   teardown_wg_2fa ;;
        openvpn)  teardown_openvpn ;;
        *) log "WARN: teardown unknown scenario: $1"; return 0 ;;
    esac
}
