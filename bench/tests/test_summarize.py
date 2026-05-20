import pytest
from summarize import parse_ping_rtts, compute_stats


def make_ping_output(rtts):
    lines = ["PING 10.0.0.1 (10.0.0.1) 56(84) bytes of data."]
    for i, rtt in enumerate(rtts, 1):
        lines.append(
            f"64 bytes from 10.0.0.1: icmp_seq={i} ttl=64 time={rtt} ms"
        )
    lines.extend([
        "",
        "--- 10.0.0.1 ping statistics ---",
        f"{len(rtts)} packets transmitted, {len(rtts)} received, 0% packet loss",
        "rtt min/avg/max/mdev = 23.500/24.000/24.500/0.150 ms",
    ])
    return "\n".join(lines)


KNOWN_RTTS = [23.9, 24.1, 24.0, 23.8, 24.2]
PING_SAMPLE = make_ping_output(KNOWN_RTTS)

PING_ALL_LOST = "\n".join([
    "PING 10.0.0.1 (10.0.0.1) 56(84) bytes of data.",
    "",
    "--- 10.0.0.1 ping statistics ---",
    "5 packets transmitted, 0 received, 100% packet loss",
])


def test_parse_ping_rtts_extracts_known_values():
    rtts = parse_ping_rtts(PING_SAMPLE)
    assert rtts == pytest.approx(KNOWN_RTTS)


def test_parse_ping_rtts_count_matches_lines():
    output = make_ping_output(list(range(1, 301)))
    rtts = parse_ping_rtts(output)
    assert len(rtts) == 300


def test_parse_ping_rtts_all_lost_returns_empty():
    rtts = parse_ping_rtts(PING_ALL_LOST)
    assert rtts == []


def test_compute_stats_mean():
    stats = compute_stats([1.0, 2.0, 3.0, 4.0, 5.0])
    assert stats["mean"] == pytest.approx(3.0)


def test_compute_stats_median_odd_count():
    stats = compute_stats([5.0, 1.0, 3.0, 2.0, 4.0])
    assert stats["median"] == pytest.approx(3.0)


def test_compute_stats_median_even_count():
    stats = compute_stats([1.0, 2.0, 3.0, 4.0])
    assert stats["median"] == pytest.approx(2.5)


def test_compute_stats_stddev_zero_for_uniform():
    stats = compute_stats([5.0] * 10)
    assert stats["stddev"] == pytest.approx(0.0)


def test_compute_stats_p95_bounds():
    values = list(range(1, 21))
    stats = compute_stats(values)
    assert 18.0 <= stats["p95"] <= 20.0


def test_compute_stats_p95_all_same():
    stats = compute_stats([7.0] * 50)
    assert stats["p95"] == pytest.approx(7.0)


def test_compute_stats_empty_raises_value_error():
    with pytest.raises(ValueError):
        compute_stats([])


def test_parse_ping_rtts_skips_malformed_lines():
    output = make_ping_output(KNOWN_RTTS) + \
        "\nFrom 10.0.0.99 icmp_seq=99 Destination Net Unreachable\n"
    rtts = parse_ping_rtts(output)
    assert rtts == pytest.approx(KNOWN_RTTS)
