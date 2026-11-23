from __future__ import annotations

import csv
import json
from pathlib import Path
import tempfile

from .domain import Batch, Well, taipei_now


class SessionStore:
    def __init__(self, root: Path, batch: Batch):
        self.batch = batch
        stamp = batch.started_at[:19].replace("-", "").replace(":", "").replace("T", "")
        self.stamp = stamp
        self.path = Path(root) / f"{stamp}_{batch.mode}_{batch.id}"
        self.path.mkdir(parents=True, exist_ok=False)
        self.journal = (self.path / "uart.jsonl").open("x", encoding="utf-8", buffering=1)
        try:
            self.checkpoint()
        except OSError:
            self.journal.close()
            raise

    def record(self, direction: str, line: str):
        self.journal.write(json.dumps({
            "host_time": taipei_now().isoformat(), "direction": direction, "line": line,
        }, ensure_ascii=False) + "\n")
        self.journal.flush()

    def checkpoint(self):
        target = self.path / "metadata.json"
        temporary = self.path / "metadata.tmp"
        temporary.write_text(json.dumps(self.batch.metadata(), ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(target)

    def export(self, destination: Path | None = None, wells: set[Well] | None = None) -> Path:
        root = Path(destination) if destination is not None else self.path
        root.mkdir(parents=True, exist_ok=True)
        output = Path(tempfile.mkdtemp(prefix=f"{self.stamp}_export_", dir=root))
        for well in sorted(self.batch.samples):
            if wells is not None and well not in wells:
                continue
            with (output / f"{self.stamp}_{well.label}.csv").open("x", encoding="utf-8-sig", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["well", "x", "y", "cycle", "total_cycles", "vre_raw", "avg_raw", "t_raw", "raw_line"])
                for s in self.batch.samples[well]:
                    writer.writerow([well.label, well.x, well.y, s.cycle, s.total_cycles, s.vre, s.avg, s.tick, s.raw])
        (output / "metadata.json").write_text(
            json.dumps(self.batch.metadata(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return output

    def close(self):
        self.journal.close()
