from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from .domain import ALL_WELLS, Batch, RANK_COLORS, Well, demo_ranking


class PlateWidget(QWidget):
    selection_changed = pyqtSignal()
    inspect_well = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.selected: set[Well] = set()
        self.batch: Batch | None = None
        self.locked = False
        self.blink = False
        self.setMinimumSize(420, 260)
        self.setMouseTracking(True)
        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self._blink)
        self.timer.start()

    def _blink(self):
        self.blink = not self.blink
        if self.batch and any(s == "running" for s in self.batch.well_states.values()):
            self.update()

    def geometry_values(self):
        left, top = 30.0, 30.0
        return left, top, (self.width() - left - 8) / 12, (self.height() - top - 8) / 8

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        left, top, cw, ch = self.geometry_values()
        p.setPen(QColor("#566174"))
        for x in range(12):
            p.drawText(QRectF(left + x * cw, 0, cw, top), Qt.AlignmentFlag.AlignCenter, str(x + 1))
        for y in range(8):
            p.drawText(QRectF(0, top + y * ch, left, ch), Qt.AlignmentFlag.AlignCenter, chr(65 + y))
        ranks = demo_ranking(self.batch) if self.batch else {}
        diameter = min(cw, ch) * 0.80
        for well in sorted(ALL_WELLS):
            color = "#d1d5db"
            state = self.batch.well_states.get(well) if self.batch else None
            if well in self.selected:
                color = "#b2c9ff"
            if state == "running":
                color = "#105974" if self.blink else "#b2c9ff"
            elif state == "complete":
                color = RANK_COLORS[ranks[well]] if well in ranks else "#93b9d3"
            elif state == "interrupted":
                color = "#efc281"
            p.setBrush(QColor(color))
            p.setPen(QPen(QColor("#ffffff"), 1.5))
            cx = left + (well.x + 0.5) * cw
            cy = top + (well.y + 0.5) * ch
            p.drawEllipse(QPointF(cx, cy), diameter / 2, diameter / 2)
            if state == "interrupted" and diameter >= 24:
                p.setPen(QPen(QColor("#324359"), 1.8))
                p.drawLine(QPointF(cx, cy - diameter * 0.20), QPointF(cx, cy + diameter * 0.06))
                p.drawPoint(QPointF(cx, cy + diameter * 0.20))

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        left, top, cw, ch = self.geometry_values()
        px, py = event.position().x(), event.position().y()
        x, y = int((px - left) // cw), int((py - top) // ch)
        if 0 <= x < 12 and 0 <= y < 8:
            well = Well(x, y)
            if self.batch and self.batch.samples.get(well):
                self.inspect_well.emit(well)
                return
            targets = {well}
        elif py < top and 0 <= x < 12:
            targets = {Well(x, r) for r in range(8)}
        elif px < left and 0 <= y < 8:
            targets = {Well(c, y) for c in range(12)}
        else:
            return
        if self.locked or self.batch:
            return
        if targets.issubset(self.selected):
            self.selected -= targets
        else:
            self.selected |= targets
        self.update()
        self.selection_changed.emit()

    def mouseMoveEvent(self, event):
        left, top, cw, ch = self.geometry_values()
        x = int((event.position().x() - left) // cw)
        y = int((event.position().y() - top) // ch)
        if 0 <= x < 12 and 0 <= y < 8:
            well = Well(x, y)
            count = len(self.batch.samples.get(well, [])) if self.batch else 0
            self.setToolTip(f"{well.label} · {count:,} 筆資料")
        else:
            self.setToolTip("點欄號選取整欄；點列名選取整列")


class CurveWidget(QWidget):
    """Offline Qt painter plot; raw hardware values never receive guessed units."""
    COLORS = ("#7566ca", "#28a5a3", "#e29a48", "#ce688f", "#4483c4")

    def __init__(self, batch: Batch | None = None, well: Well | None = None, parent=None):
        super().__init__(parent)
        self.batch = batch
        self.well = well
        self.visible_cycles = 10000
        self.setMinimumSize(320, 170)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor("#ffffff"))
        rect = QRectF(90, 20, max(20, self.width() - 115), max(20, self.height() - 72))
        p.setPen(QPen(QColor("#c9cbd0"), 1, Qt.PenStyle.DashLine))
        for i in range(6):
            x = rect.left() + rect.width() * i / 5
            y = rect.top() + rect.height() * i / 5
            p.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
            p.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
        p.setPen(QPen(QColor("#8993a2"), 1))
        p.drawRect(rect)
        samples = self.batch.samples.get(self.well, []) if self.batch else []
        cycles = sorted({s.cycle for s in samples})[:self.visible_cycles]
        samples = [s for s in samples if s.cycle in cycles]
        ca = self.batch and self.batch.mode == "CA"
        p.setPen(QColor("#596478"))
        p.drawText(QRectF(rect.left(), self.height() - 30, rect.width(), 24), Qt.AlignmentFlag.AlignCenter,
                   "T（原始值）" if ca else "VRE（原始值）")
        p.save()
        p.translate(16, rect.center().y())
        p.rotate(-90)
        p.drawText(QRectF(-80, -12, 160, 24), Qt.AlignmentFlag.AlignCenter, "AVG（原始值）")
        p.restore()
        if not samples:
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, "量測資料將顯示於此")
            return
        xs = [s.tick if ca else s.vre for s in samples]
        ys = [s.avg for s in samples]
        xmin, xmax, ymin, ymax = min(xs), max(xs), min(ys), max(ys)
        dx = xmax - xmin or 1
        dy = ymax - ymin or max(abs(ymin) * 0.1, 1e-6)
        ymin -= dy * 0.05
        ymax += dy * 0.05
        dy = ymax - ymin
        for i in range(6):
            xvalue = xmin + dx * i / 5
            yvalue = ymax - dy * i / 5
            p.drawText(QRectF(rect.left() + rect.width() * i / 5 - 35, rect.bottom() + 5, 70, 22),
                       Qt.AlignmentFlag.AlignCenter, f"{xvalue:.4g}")
            p.drawText(QRectF(24, rect.top() + rect.height() * i / 5 - 10, 61, 20),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, f"{yvalue:.3g}")
        p.save()
        p.setClipRect(rect.adjusted(-1, -1, 1, 1))
        for index, cycle in enumerate(cycles):
            path = QPainterPath()
            first = True
            previous_tick = None
            for sample in (s for s in samples if s.cycle == cycle):
                xvalue = sample.tick if ca else sample.vre
                point = QPointF(rect.left() + (xvalue - xmin) / dx * rect.width(),
                                rect.bottom() - (sample.avg - ymin) / dy * rect.height())
                if first or (previous_tick is not None and sample.tick < previous_tick):
                    path.moveTo(point)
                    first = False
                else:
                    path.lineTo(point)
                previous_tick = sample.tick
            p.setPen(QPen(QColor(self.COLORS[index % len(self.COLORS)]), 1.6))
            p.drawPath(path)
        p.restore()


class ResultPage(QWidget):
    save_requested = pyqtSignal(object)
    close_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.well = None
        self.maximum = 1
        self.count = 1
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 4, 12, 6)
        self.title = QLabel()
        top = QHBoxLayout()
        top.addWidget(self.title)
        top.addStretch()
        top.addWidget(QLabel("Repeat times"))
        minus, plus = QPushButton("−"), QPushButton("+")
        minus.clicked.connect(lambda: self._adjust(-1))
        plus.clicked.connect(lambda: self._adjust(1))
        self.counter = QLabel()
        top.addWidget(minus)
        top.addWidget(self.counter)
        top.addWidget(plus)
        layout.addLayout(top)
        row = QHBoxLayout()
        self.plot = CurveWidget()
        row.addWidget(self.plot, 1)
        side = QVBoxLayout()
        side.addStretch()
        close, save = QPushButton("Back"), QPushButton("Save data")
        close.setObjectName("dark")
        save.setObjectName("primary")
        close.clicked.connect(self.close_requested.emit)
        save.clicked.connect(lambda: self.save_requested.emit(self.well))
        side.addWidget(close)
        side.addSpacing(12)
        side.addWidget(save)
        row.addLayout(side)
        layout.addLayout(row, 1)

    def set_batch(self, batch: Batch, well: Well):
        self.well = well
        samples = batch.samples[well]
        self.maximum = len({s.cycle for s in samples})
        self.count = self.maximum
        self.title.setText(f"{well.label} · {len(samples):,} 筆 · {batch.source.upper()}")
        self.plot.batch, self.plot.well = batch, well
        self._adjust(0)

    def _adjust(self, delta):
        self.count = min(self.maximum, max(1, self.count + delta))
        self.counter.setText(f"{self.count} / {self.maximum}")
        self.plot.visible_cycles = self.count
        self.plot.update()
