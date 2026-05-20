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
    echo "STUB: setup_wg_plain not yet implemented" >&2
    return 1
}

teardown_wg_plain() {
    echo "STUB: teardown_wg_plain not yet implemented" >&2
    return 0
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
    echo "STUB: setup_openvpn not yet implemented" >&2
    return 1
}

teardown_openvpn() {
    echo "STUB: teardown_openvpn not yet implemented" >&2
    return 0
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
