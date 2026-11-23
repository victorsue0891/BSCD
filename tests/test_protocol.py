from collections import Counter
from pathlib import Path

import pytest

from instrument_ui.domain import CVConfig, RGB, Well
from instrument_ui.protocol import LineFramer, parse_line, scan_command


ROOT = Path(__file__).resolve().parents[1]


def test_real_fw028_recording():
    samples = []
    counts = Counter()
    for line in (ROOT / "RefTxt1006.txt").read_text(encoding="utf-8-sig").splitlines():
        event = parse_line(line)
        counts[event.kind] += 1
        if event.kind == "sample":
            samples.append(event.value)
    assert len(samples) == 8208
    assert counts["invalid"] == 0
    assert counts["end"] == 1
    assert counts["start"] == 1
    assert {s.well for s in samples} == {Well(5, y) for y in range(8)}
    for y in range(8):
        series = [s.vre for s in samples if s.well == Well(5, y)]
        assert series == list(range(513)) + list(range(512, -1, -1))
    assert samples[0].well.label == "6A"
    assert samples[0].avg == 3.526562
    assert samples[0].tick == 42324


def test_ascii_fragments_and_multiple_lines():
    framer = LineFramer()
    assert framer.feed(b"APPCFG_RST O") == []
    assert framer.feed(b"K\r\nXS_FUD (1/1): 5,0 VRE=0 AVG=-1.2e-3 T:42\n") == [
        "APPCFG_RST OK", "XS_FUD (1/1): 5,0 VRE=0 AVG=-1.2e-3 T:42"
    ]
    assert parse_line("XS_FUD (1/1): 5,0 VRE=0 AVG=-1.2e-3 T:42").value.avg == -0.0012
    with pytest.raises(ValueError):
        LineFramer(5).feed(b"123456")


@pytest.mark.parametrize("line", [
    "XS_FUD (0/1): 5,0 VRE=0 AVG=1 T:42",
    "XS_FUD (2/1): 5,0 VRE=0 AVG=1 T:42",
    "XS_FUD (1/1): 12,0 VRE=0 AVG=1 T:42",
    "XS_FUD (1/1): 5,8 VRE=0 AVG=1 T:42",
    "XS_FUD (1/1): 5,0 VRE=0 AVG=nan T:42",
    "XS_FUD (1/1): 5,0 VRE=0 AVG=1e999 T:42",
])
def test_bad_samples_are_not_silently_accepted(line):
    assert parse_line(line).kind == "invalid"


def test_debug_average_is_not_a_sample():
    assert parse_line("Step 42 :: OK = 3, Average = 1283670 (0x139656)").kind == "log"
    assert parse_line(" VRE_XSCAN_FUD OK <-- 人工註解").kind == "scan_ok"
    assert parse_line("BSCD_XCA 30 1 0").kind == "log"


def test_command_coordinates_and_rgb():
    assert Well(0, 0).label == "1A"
    assert Well(11, 7).label == "12H"
    assert CVConfig().command == "APPCFG_RST 15 2500 -2500 1024"
    assert scan_command(5, RGB(10, 20, 30)) == "VRE_XSCAN_FUD 5 10 20 30 1"
    with pytest.raises(ValueError):
        CVConfig(lower_mv=1000, upper_mv=1000).validate()
