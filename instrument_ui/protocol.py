"""FW 028 grammar backed by RefTxt1006.txt; unknown lines remain journalled."""
from __future__ import annotations

from dataclasses import dataclass
import math
import re

from .domain import Sample, Well

FLOAT = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
DATA = re.compile(
    rf"^XS_FUD\s+\((\d+)/(\d+)\):\s*(\d+)\s*,\s*(\d+)\s+"
    rf"VRE=({FLOAT})\s+AVG=({FLOAT})\s+T:(\d+)\s*$"
)
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


@dataclass(frozen=True)
class Event:
    kind: str
    value: object = None


class LineFramer:
    """Accept fragmented LF/CRLF ASCII lines, bound unterminated input."""
    def __init__(self, limit: int = 16384):
        self.buffer = bytearray()
        self.limit = limit

    def feed(self, data: bytes) -> list[str]:
        self.buffer.extend(data)
        result = []
        while b"\n" in self.buffer:
            end = self.buffer.index(10)
            if end > self.limit:
                self.buffer.clear()
                raise ValueError("UART 訊息超過長度限制")
            result.append(bytes(self.buffer[:end]).rstrip(b"\r").decode("ascii", "replace"))
            del self.buffer[:end + 1]
        if len(self.buffer) > self.limit:
            self.buffer.clear()
            raise ValueError("UART 未收到換行或訊息過長")
        return result


def parse_line(raw: str) -> Event:
    # Existing evidence includes human annotations; raw is preserved unchanged.
    line = ANSI.sub("", raw).split("<--", 1)[0].strip()
    m = DATA.fullmatch(line)
    if m:
        cycle, total, x, y = map(int, m.groups()[:4])
        vre, avg = map(float, m.groups()[4:6])
        if not 1 <= cycle <= total or not all(math.isfinite(v) for v in (vre, avg)):
            return Event("invalid", raw)
        try:
            sample = Sample(Well(x, y), cycle, total, vre, avg, int(m[7]), raw)
        except ValueError:
            return Event("invalid", raw)
        return Event("sample", sample)
    if line.startswith("XS_FUD ("):
        return Event("invalid", raw)
    m = re.fullmatch(r"FW_VERSION:\s*(\S+)", line)
    if m:
        return Event("firmware", m[1])
    if line.startswith("ESP-ROM:") or re.match(r"rst:0x", line):
        return Event("boot", line)
    if line == "APPCFG_RST OK":
        return Event("config_ok")
    if re.fullmatch(r"(?:SLOPE|REAL_STEP|APPVREF_RST)=.*", line):
        pairs = re.findall(r"([A-Z][A-Z0-9_]*)=(-?\d+)", line)
        return Event("settings", {k: int(v) for k, v in pairs})
    if line == "VRE_XSCAN_FUD OK":
        return Event("scan_ok")
    m = re.fullmatch(r"XSCAN_FUD START T:(\d+)", line)
    if m:
        return Event("start", int(m[1]))
    m = re.fullmatch(r"XSCAN_FUD END T:(\d+) ELAPSED:(\d+)", line)
    if m:
        return Event("end", {"T": int(m[1]), "ELAPSED": int(m[2])})
    if re.search(r"\b(?:ERROR|ERR|FAIL|FAILED|BUSY|INVALID)\b", line, re.I):
        return Event("error", line)
    return Event("log", raw)


def scan_command(x: int, rgb) -> str:
    Well(x, 0)
    # Fixed repeat=1 follows the only observed FW 028 run (N14 assumption).
    # VREF/INCR are deliberately omitted; firmware owns automatic settings.
    return f"VRE_XSCAN_FUD {x} {rgb.r} {rgb.g} {rgb.b} 1"
