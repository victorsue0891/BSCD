from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone, timedelta
from math import isfinite
from uuid import uuid4


def taipei_now() -> datetime:
    # The operating system must be synchronised to the DS3231 by Linux.
    return datetime.now(timezone(timedelta(hours=8)))


@dataclass(frozen=True, order=True)
class Well:
    x: int
    y: int

    def __post_init__(self):
        if not 0 <= self.x < 12 or not 0 <= self.y < 8:
            raise ValueError("孔位超出 12 × 8 範圍")

    @property
    def label(self) -> str:
        return f"{self.x + 1}{chr(65 + self.y)}"


ALL_WELLS = frozenset(Well(x, y) for x in range(12) for y in range(8))


@dataclass(frozen=True)
class CVConfig:
    slope: int = 15
    upper_mv: int = 2500
    lower_mv: int = -2500
    resolution: int = 1024

    def validate(self):
        if any(type(v) is not int for v in (self.slope, self.upper_mv, self.lower_mv, self.resolution)):
            raise ValueError("CV 參數必須是整數（電壓使用 mV）")
        if self.slope not in range(10, 51, 5):
            raise ValueError("掃描速率應為 10～50 mV/s，間隔 5")
        if not -2500 <= self.lower_mv < self.upper_mv <= 2500:
            raise ValueError("電壓範圍應在 −2.5～2.5 V，且下限必須小於上限")
        if self.lower_mv % 100 or self.upper_mv % 100:
            raise ValueError("電壓設定間隔為 0.1 V")
        if self.resolution not in (256, 512, 1024):
            raise ValueError("階數選項為 256、512、1024（待韌體驗證）")

    @property
    def command(self) -> str:
        self.validate()
        return f"APPCFG_RST {self.slope} {self.upper_mv} {self.lower_mv} {self.resolution}"


@dataclass(frozen=True)
class CAConfig:
    duration_s: float = 30.0
    interval_s: float = 0.1
    initial_v: float = 0.0
    target_v: float = 1.0

    def validate(self):
        values = (self.duration_s, self.interval_s, self.initial_v, self.target_v)
        if not all(isfinite(v) for v in values):
            raise ValueError("CA 參數必須為有限值")
        if not 0.1 <= self.duration_s <= 3600 or not 0.05 <= self.interval_s <= self.duration_s:
            raise ValueError("模擬持續時間為 0.1～3600 s，取樣間隔應在 0.05 s 與持續時間之間")
        if not all(-2.5 <= v <= 2.5 for v in (self.initial_v, self.target_v)):
            raise ValueError("模擬電壓應在 −2.5～2.5 V")


@dataclass(frozen=True)
class RGB:
    r: int = 0
    g: int = 0
    b: int = 0

    def __post_init__(self):
        if any(type(v) is not int or not 0 <= v <= 255 for v in (self.r, self.g, self.b)):
            raise ValueError("R、G、B 必須是 0～255 的整數")


@dataclass(frozen=True)
class Sample:
    well: Well
    cycle: int
    total_cycles: int
    vre: float
    avg: float
    tick: int
    raw: str


@dataclass
class Batch:
    mode: str
    source: str
    selected: set[Well]
    config: CVConfig | CAConfig
    rgb: RGB
    started_at: str = field(default_factory=lambda: taipei_now().isoformat())
    id: str = field(default_factory=lambda: uuid4().hex[:10])
    firmware: str = "unknown"
    state: str = "idle"
    reason: str = ""
    settings_reply: dict = field(default_factory=dict)
    samples: dict[Well, list[Sample]] = field(default_factory=dict)
    well_states: dict[Well, str] = field(default_factory=dict)

    def metadata(self) -> dict:
        return {
            "schema_version": 1, "batch_id": self.id, "mode": self.mode,
            "source": self.source, "started_at": self.started_at,
            "firmware": self.firmware, "state": self.state, "reason": self.reason,
            "selected": [w.label for w in sorted(self.selected)],
            "well_states": {w.label: s for w, s in self.well_states.items()},
            "sample_counts": {w.label: len(s) for w, s in self.samples.items()},
            "config": asdict(self.config), "rgb": asdict(self.rgb),
            "settings_reply": self.settings_reply,
            "repeat_command_value": 1,
            "units": {"VRE": None, "AVG": None, "T": None},
            "note": "原始值未校正；END 僅代表收到批次結束，未保證資料完整性。模擬曲線及分色僅供展示。",
        }


RANK_COLORS = ("#71dba2", "#ffd19d", "#f3abc5", "#f17d82")


def demo_ranking(batch: Batch) -> dict[Well, int]:
    """Provisional demo only: ascending VRE branch, signed maximum per cycle.

    No clipping or outlier removal. Equal peaks use column/row order. Remainders
    go to earlier groups. Never call this for uncalibrated hardware data.
    """
    if batch.source != "demo" or batch.mode != "CV":
        return {}
    scores = []
    for well, samples in batch.samples.items():
        if batch.well_states.get(well) != "complete":
            continue
        peaks = []
        for cycle in sorted({s.cycle for s in samples}):
            branch = []
            previous = None
            for sample in (s for s in samples if s.cycle == cycle):
                if previous is not None and sample.vre < previous:
                    break
                branch.append(sample.avg)
                previous = sample.vre
            if branch:
                peaks.append(max(branch))
        if peaks:
            scores.append((sum(peaks) / len(peaks), well))
    scores.sort()
    quotient, remainder = divmod(len(scores), 4)
    result = {}
    offset = 0
    for group in range(4):
        count = quotient + (group < remainder)
        for _, well in scores[offset:offset + count]:
            result[well] = group
        offset += count
    return result
