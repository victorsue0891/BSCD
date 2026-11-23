"""Bounded, asynchronous diagnostics. No hardware commands are issued here."""
from __future__ import annotations

from concurrent.futures import Future
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import platform
from queue import Empty, Full, Queue
import shutil
import threading
import time
from uuid import uuid4
import zipfile

from .domain import taipei_now


SCHEMA = "pimex-diagnostics-v1"


def _file_lock(handle, acquire):
    handle.seek(0)
    if os.name == "nt":
        import msvcrt
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK if acquire else msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(handle, (fcntl.LOCK_EX | fcntl.LOCK_NB) if acquire else fcntl.LOCK_UN)


def _session_in_use(directory):
    path = directory / "active.lock"
    if not path.exists():
        return False
    try:
        with path.open("r+b") as handle:
            _file_lock(handle, True)
            _file_lock(handle, False)
        return False
    except OSError:
        return True


@dataclass
class Snapshot:
    directory: Path
    files: list[Path]
    manifest: dict


class Diagnostics:
    def __init__(self, root: Path, *, segment_bytes=20 * 1024**2,
                 budget_bytes=500 * 1024**2, queue_size=8192, startup=None):
        self.root = Path(root).resolve()
        self.session_id = f"session_{taipei_now():%Y%m%d_%H%M%S}_{uuid4().hex[:10]}"
        self.directory = self.root / self.session_id
        self.segment_bytes = segment_bytes
        self.budget_bytes = budget_bytes
        self._queue = Queue(maxsize=queue_size)
        self._lock = threading.RLock()
        self._files_lock = threading.RLock()
        self._submission_lock = threading.Lock()
        self._pins = set()
        self._closed = False
        self._failed = False
        self._warning = ""
        self._dropped = 0
        self._sequence = 0
        self._started = time.monotonic()
        self._handle = None
        self._session_lock = None
        self._segment = 0
        self._size = 0
        self._manifest = {
            "schema": SCHEMA, "session_id": self.session_id,
            "started_at": taipei_now().isoformat(), "ended_at": None,
            "clean_shutdown": False, "pruned_segments": 0,
            "python": platform.python_version(), "platform": platform.platform(),
            "hostname": platform.node(), "startup": startup or {},
            "segment_bytes": segment_bytes, "budget_bytes": budget_bytes,
        }
        self._thread = threading.Thread(target=self._run, name="pimex-diagnostics", daemon=True)
        self._thread.start()
        self.record("application_start", **(startup or {}))

    @property
    def warning(self):
        with self._lock:
            if self._dropped:
                return f"診斷紀錄不完整：{self._dropped} 筆未保存。{self._warning}"
            return self._warning

    def record(self, kind: str, **fields):
        """Freeze mutable metadata now; never wait for disk on the Qt thread."""
        with self._lock:
            if self._closed:
                return
            self._sequence += 1
            row = {"seq": self._sequence, "host_time": taipei_now().isoformat(),
                   "elapsed_s": round(time.monotonic() - self._started, 6), "kind": kind, **fields}
            if self._failed:
                self._dropped += 1
                return
            payload = (json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8")
            try:
                self._queue.put_nowait(payload)
            except Full:
                self._dropped += 1

    def _save_manifest(self):
        with self._lock:
            self._manifest.update(dropped_records=self._dropped, write_failed=self._failed,
                                  warning=self._warning, last_attempted_sequence=self._sequence)
            payload = json.dumps(self._manifest, ensure_ascii=False, indent=2)
        temporary = self.directory / "manifest.tmp"
        temporary.write_text(payload, encoding="utf-8")
        temporary.replace(self.directory / "manifest.json")

    def _rotate(self):
        if self._handle:
            self._handle.flush()
            self._handle.close()
        self._segment += 1
        self._handle = (self.directory / f"records-{self._segment:06d}.jsonl").open("xb")
        self._size = 0

    def _failure(self, exc):
        with self._lock:
            self._failed = True
            self._warning = f"診斷寫入失敗：{exc}；請修復儲存空間後重新啟動程式。"
        if self._handle:
            try:
                self._handle.close()
            except OSError:
                pass
            self._handle = None

    def _sessions(self):
        result = []
        if not self.root.is_dir():
            return result
        for directory in sorted(self.root.glob("session_*"), reverse=True):
            if directory.is_symlink() or not directory.is_dir():
                continue
            if directory != self.directory and _session_in_use(directory):
                continue
            try:
                manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
                if manifest.get("schema") == SCHEMA and manifest.get("session_id") == directory.name:
                    result.append((directory, manifest))
            except (OSError, ValueError):
                continue
        return result

    def sessions(self):
        with self._files_lock:
            return [manifest for _, manifest in self._sessions()]

    def _prune(self):
        """Only our marked sessions and known filenames; never touch measurement data."""
        sessions = self._sessions()
        segments = []
        for directory, manifest in sessions:
            for path in sorted(directory.glob("records-*.jsonl")):
                if not path.is_symlink() and path.is_file():
                    segments.append((path, manifest, path.stat().st_size))
        total = sum(size for _, _, size in segments)
        # Pins temporarily protect an export snapshot. Pruning resumes after export.
        for path, manifest, size in sorted(segments, key=lambda item: str(item[0])):
            if total <= self.budget_bytes:
                break
            if path in self._pins or (self._handle and path == Path(self._handle.name)):
                continue
            # Mark the gap before deletion; an exporter can never see silent truncation.
            if path.parent == self.directory:
                self._manifest["pruned_segments"] += 1
                self._save_manifest()
            else:
                manifest["pruned_segments"] = manifest.get("pruned_segments", 0) + 1
                temporary = path.parent / "manifest.tmp"
                temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
                temporary.replace(path.parent / "manifest.json")
            path.unlink()
            total -= size
        # Bound empty session metadata as well, retaining the newest 100 sessions.
        for directory, _ in sessions[100:]:
            if directory == self.directory or any(directory.glob("records-*.jsonl")):
                continue
            if any(p.parent == directory for p in self._pins):
                continue
            entries = list(directory.iterdir())
            if all(p.name in ("manifest.json", "manifest.tmp", "active.lock") and not p.is_symlink() for p in entries):
                for path in entries:
                    path.unlink()
                directory.rmdir()

    def _make_snapshot(self, session_id):
        with self._files_lock:
            if session_id == self.session_id:
                if not self.directory.is_dir():
                    raise OSError(self.warning or "本次診斷目錄無法建立")
                if not self._failed and self._thread.is_alive():
                    try:
                        self._rotate()  # Everything before the barrier is now immutable.
                        self._save_manifest()
                    except OSError as exc:
                        self._failure(exc)
                        raise
                manifest = dict(self._manifest)
                with self._lock:
                    manifest.update(dropped_records=self._dropped, write_failed=self._failed,
                                    warning=self._warning)
                directory = self.directory
            else:
                match = next(((d, m) for d, m in self._sessions() if d.name == session_id), None)
                if match is None:
                    raise OSError("所選歷史紀錄不存在或已被輪替清理")
                directory, manifest = match
            files = [p for p in sorted(directory.glob("records-*.jsonl"))
                     if p.is_file() and not p.is_symlink() and p.stat().st_size]
            if not files:
                raise OSError("此工作階段沒有可匯出的紀錄（可能已被輪替清理）")
            self._pins.update(files)
            manifest = dict(manifest, snapshot_at=taipei_now().isoformat())
            return Snapshot(directory, files, manifest)

    def snapshot(self, session_id):
        """Call only on a worker thread, never on the UI thread."""
        future = Future()
        with self._submission_lock:
            with self._lock:
                closed = self._closed
            if not closed:
                self._queue.put(("snapshot", session_id, future))
        if closed:
            self._thread.join()
            return self._make_snapshot(session_id)
        return future.result()

    def release(self, snapshot):
        with self._files_lock:
            self._pins.difference_update(snapshot.files)

    def close(self):
        with self._submission_lock:
            with self._lock:
                if self._closed:
                    return
                self.record("application_stop")
                self._closed = True
            self._queue.put(None)
        self._thread.join()

    def _run(self):
        try:
            self.directory.mkdir(parents=True, exist_ok=False)
            self._session_lock = (self.directory / "active.lock").open("w+b")
            self._session_lock.write(b"1")
            self._session_lock.flush()
            _file_lock(self._session_lock, True)
            source_hash = hashlib.sha256()
            for path in sorted(Path(__file__).parent.glob("*.py")):
                source_hash.update(path.name.encode())
                source_hash.update(path.read_bytes())
            self._manifest["source_sha256"] = source_hash.hexdigest()
            with self._files_lock:
                self._save_manifest()
                self._rotate()
                self._prune()
        except OSError as exc:
            self._failure(exc)
        last_flush = time.monotonic()
        while True:
            try:
                item = self._queue.get(timeout=0.25)
            except Empty:
                item = "flush"
            if item is None:
                break
            if isinstance(item, tuple):
                _, session_id, future = item
                try:
                    future.set_result(self._make_snapshot(session_id))
                except Exception as exc:
                    future.set_exception(exc)
                continue
            try:
                if isinstance(item, bytes):
                    if self._failed:
                        with self._lock:
                            self._dropped += 1
                    else:
                        with self._files_lock:
                            if self._size and self._size + len(item) > self.segment_bytes:
                                self._rotate()
                                self._prune()
                            self._handle.write(item)
                            self._size += len(item)
                if not self._failed and time.monotonic() - last_flush >= 1:
                    with self._files_lock:
                        self._handle.flush()
                        self._save_manifest()
                        self._prune()
                    last_flush = time.monotonic()
            except OSError as exc:
                with self._lock:
                    if isinstance(item, bytes):
                        self._dropped += 1
                self._failure(exc)
        with self._files_lock:
            try:
                if self._handle:
                    self._handle.flush()
                    self._handle.close()
                    self._handle = None
                self._manifest.update(ended_at=taipei_now().isoformat(), clean_shutdown=not self._failed)
                if self.directory.is_dir():
                    self._save_manifest()
                    self._prune()
            except OSError as exc:
                self._failure(exc)
            finally:
                if self._session_lock:
                    self._session_lock.close()


def export_diagnostics(recorder, session_id, destination, *, progress=lambda value: None,
                       check_destination=lambda: None, cancelled=lambda: False):
    """Stream an immutable snapshot to a verified ZIP. Keep source on all failures."""
    snapshot = recorder.snapshot(session_id)
    partial = None
    try:
        destination = Path(destination).resolve(strict=True)
        if not destination.is_dir():
            raise OSError("匯出位置不是資料夾")
        if destination == recorder.root or recorder.root in destination.parents:
            raise OSError("請選擇診斷紀錄目錄以外的匯出位置")
        check_destination()
        total = sum(p.stat().st_size for p in snapshot.files)
        if shutil.disk_usage(destination).free < total * 3 + 1024**2:
            raise OSError("目的地可用空間不足，請更換儲存裝置")
        name = f"PIMEX_debug_{taipei_now():%Y%m%d_%H%M%S}_{uuid4().hex[:8]}.zip"
        output = destination / name
        partial = destination / (name + ".partial")
        batches, hashes = {}, {}
        processed, malformed = 0, 0
        # Derived files are staged locally; they never enter the live recording queue.
        import tempfile
        with tempfile.TemporaryDirectory(prefix="pimex-export-") as staging:
            staging = Path(staging)
            with (staging / "uart.jsonl").open("wb") as uart, \
                 (staging / "uart.txt").open("w", encoding="utf-8") as readable, \
                 (staging / "events.log").open("w", encoding="utf-8") as events, \
                 partial.open("xb") as target:
                with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
                    for path in snapshot.files:
                        digest = hashlib.sha256()
                        with path.open("rb") as source, archive.open("raw/" + path.name, "w", force_zip64=True) as raw:
                            last_progress = processed
                            for line in source:
                                if cancelled():
                                    raise OSError("匯出已取消")
                                raw.write(line)
                                digest.update(line)
                                processed += len(line)
                                if processed - last_progress >= 256 * 1024:
                                    progress(min(80, int(processed * 80 / max(total, 1))))
                                    last_progress = processed
                                try:
                                    row = json.loads(line)
                                    kind = row["kind"]
                                except (ValueError, KeyError, TypeError):
                                    malformed += 1
                                    continue
                                prefix = f"{row.get('host_time', '')} +{row.get('elapsed_s', '')}s #{row.get('seq', '')} {kind}"
                                if kind.startswith("uart_"):
                                    uart.write(line)
                                    readable.write(prefix + " " + json.dumps({k: v for k, v in row.items()
                                                   if k not in ('seq', 'host_time', 'elapsed_s', 'kind')}, ensure_ascii=False) + "\n")
                                else:
                                    events.write(line.decode("utf-8", errors="replace"))
                                if kind in ("batch_start", "batch_end"):
                                    batches[row["batch_id"]] = row["metadata"]
                        hashes[path.name] = digest.hexdigest()
                        progress(min(80, int(processed * 80 / max(total, 1))))
                    for stream in (uart, readable, events):
                        stream.flush()
                    for filename in ("uart.jsonl", "uart.txt", "events.log"):
                        archive.write(staging / filename, filename)
                    manifest = dict(snapshot.manifest, raw_sha256=hashes, malformed_records=malformed)
                    archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
                    archive.writestr("batch_metadata.json", json.dumps(batches, ensure_ascii=False, indent=2))
                    summary = (
                        f"PIMEX 診斷包\n工作階段：{session_id}\n開始：{manifest.get('started_at')}\n"
                        f"快照時間：{manifest['snapshot_at']}\n軟體 SHA256：{manifest.get('source_sha256')}\n"
                        f"已輪替刪除的檔案：{manifest.get('pruned_segments', 0)}\n"
                        f"未保存紀錄：{manifest.get('dropped_records', 0)}\n"
                        f"寫入失敗：{manifest.get('write_failed', False)}\n無法解析的紀錄：{malformed}\n"
                        f"正常關閉：{manifest.get('clean_shutdown', False)}（本次執行中亦為 False）\n"
                        "raw/ 保留原始分段；uart.jsonl 包含 RX bytes、文字行及 TX 階段，不可重複計為樣本。\n"
                        "TX queued / written 不代表 ESP32 已收到或確認。未開啟串口前的資料無法補回。\n"
                        "UART 單位仍依韌體規格；本診斷包不驗證量測資料完整性。\n"
                    )
                    archive.writestr("summary.txt", summary)
                target.flush()
                os.fsync(target.fileno())
            progress(90)
            check_destination()
            if cancelled():
                raise OSError("匯出已取消")
            with zipfile.ZipFile(partial) as archive:
                for entry in archive.infolist():
                    with archive.open(entry) as content:
                        while content.read(1024 * 1024):
                            if cancelled():
                                raise OSError("匯出已取消")
            check_destination()
            partial.replace(output)
            progress(100)
            return output
    finally:
        recorder.release(snapshot)
        if partial is not None and partial.exists():
            try:
                partial.unlink()
            except OSError:
                pass
