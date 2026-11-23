"""Reference artwork and code-drawn previews for the 800 x 600 display."""
from pathlib import Path
from math import exp

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QPolygonF
from PyQt6.QtWidgets import QLabel, QPushButton, QWidget


ASSETS = Path(__file__).resolve().parent / "assets"


def home_icon():
    pixmap = QPixmap(24, 24)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor("#8b80b5"), 1.7))
    painter.drawLine(3, 11, 12, 3)
    painter.drawLine(12, 3, 21, 11)
    painter.drawLine(6, 9, 6, 21)
    painter.drawLine(18, 9, 18, 21)
    painter.drawLine(6, 21, 18, 21)
    painter.drawRect(10, 15, 4, 6)
    painter.end()
    return QIcon(pixmap)


class BootScreen(QWidget):
    mode_selected = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.background = QPixmap(str(ASSETS / "boot-background.png"))
        self.logo = QLabel(self)
        self.logo.setPixmap(QPixmap(str(ASSETS / "pimex-logo.png")).scaled(
            124, 43, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        self.title = QLabel("96-well PIMEX", self)
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title.setStyleSheet("color:white; background:transparent; font-size:36px; font-weight:600;")
        self.mode_buttons = []
        for mode, text in (("CV", "Cyclic Voltammetry, CV"), ("CA", "Chronoamperometry, CA")):
            b = QPushButton(text, self)
            b.setObjectName("bootMode")
            b.clicked.connect(lambda checked=False, m=mode: self.mode_selected.emit(m))
            b.setStyleSheet("""
                QPushButton { color:white; background:rgba(8,10,31,110); border:4px solid #7863ce;
                    border-radius:9px; font-size:18px; font-weight:700; padding:8px; }
                QPushButton:hover { background:rgba(87,64,157,180); border-color:#a697ed; }
                QPushButton:pressed { background:rgba(113,87,191,210); }
                QPushButton:disabled { color:#aaa; border-color:#5b566f; }
            """)
            self.mode_buttons.append(b)
        self.demo_btn = QPushButton("模擬操作", self)
        self.replay_btn = QPushButton("紀錄重播", self)
        self.connect_btn = QPushButton("連線設定", self)
        self.log_btn = QPushButton("通訊紀錄", self)
        self.tools = [self.demo_btn, self.replay_btn, self.connect_btn, self.log_btn]
        for b in self.tools:
            b.setStyleSheet("""
                QPushButton { color:#dad9ec; background:rgba(6,10,24,145); border:1px solid #57526e;
                    border-radius:4px; font-size:11px; min-height:18px; padding:4px; }
                QPushButton:hover { color:white; border-color:#b0a3ef; }
            """)
        self.credit = QLabel("NTHU Lab428-1 & NCU IR3-202", self)
        self.credit.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.credit.setStyleSheet("color:#c6c7d8; background:transparent; font-size:10px;")
        self.connection_label = QLabel("未連線", self)
        self.connection_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.connection_label.setStyleSheet("color:white; background:rgba(6,10,24,185); border-radius:4px; font-size:12px;")

    def resizeEvent(self, event):
        w, h = self.width(), self.height()
        self.logo.setGeometry(18, 17, 124, 43)
        self.title.setGeometry(150, int(h * 0.05), w - 300, 56)
        margin, gap = int(w * 0.055), int(w * 0.055)
        width = (w - 2 * margin - gap) // 2
        for i, b in enumerate(self.mode_buttons):
            b.setGeometry(margin + i * (width + gap), int(h * 0.72), width, max(70, int(h * 0.14)))
        for i, b in enumerate(self.tools):
            b.setGeometry(18 + i * 82, h - 38, 76, 28)
        self.credit.setGeometry(w - 285, h - 38, 267, 28)
        self.connection_label.setGeometry(18, h - 64, w - 36, 22)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.fillRect(self.rect(), QColor("#090c20"))
        if not self.background.isNull():
            # Fit the complete artwork without stretching the instruments.
            scaled = self.background.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                            Qt.TransformationMode.SmoothTransformation)
            p.drawPixmap((self.width() - scaled.width()) // 2, (self.height() - scaled.height()) // 2, scaled)
        shade = QLinearGradient(0, 0, 0, self.height())
        shade.setColorAt(0, QColor(4, 6, 20, 130))
        shade.setColorAt(0.22, QColor(4, 6, 20, 0))
        shade.setColorAt(0.65, QColor(4, 6, 20, 0))
        shade.setColorAt(1, QColor(4, 6, 20, 140))
        p.fillRect(self.rect(), shade)


class OutlineArrows(QWidget):
    """Outlined scan direction symbols from the CV settings reference."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(126, 68)
        self.setMaximumHeight(80)
        self.setToolTip("掃描方向示意")

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor("#26292e"), 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        for x, down in ((24, False), (88, True)):
            points = [(-17, -4), (-7, -4), (-7, 21), (7, 21), (7, -4), (17, -4), (0, -23)]
            p.drawPolygon(QPolygonF([QPointF(x + dx, self.height() / 2 + (-dy if down else dy))
                                    for dx, dy in points]))


class SweepPreview(QWidget):
    """Illustrative only; does not derive ESP32 timing or measured units."""
    def __init__(self, mode="CV", parent=None):
        super().__init__(parent)
        self.mode = mode
        self.setMinimumSize(240, 165)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), Qt.GlobalColor.white)
        r = QRectF(30, 22, self.width() - 46, self.height() - 45)
        p.setPen(QPen(QColor("#c8cdd5"), 1))
        p.drawRect(self.rect().adjusted(1, 1, -2, -2))
        if self.mode == "CV":
            p.setPen(QPen(QColor("#555555"), 1))
            p.drawLine(QPointF(r.left(), r.top()), QPointF(r.left(), r.bottom()))
            for fraction, text, color in ((0.10, "+5V", "#de6868"), (0.30, "E1", "#90b1c9"),
                                          (0.55, "Ei", "#90b1c9"), (0.80, "E2", "#90b1c9"),
                                          (0.93, "GND", "#333333")):
                y = r.top() + r.height() * fraction
                pen = QPen(QColor(color), 1.5)
                if text in ("E1", "E2"):
                    pen.setStyle(Qt.PenStyle.DotLine)
                p.setPen(pen)
                p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
                p.setPen(QColor("#59616e"))
                p.drawText(QRectF(0, y - 9, 27, 18), Qt.AlignmentFlag.AlignRight, text)
            path = QPainterPath()
            vertices = ((0, .8), (.125, .55), (.25, .3), (.375, .55), (.5, .8),
                        (.625, .55), (.75, .3), (.875, .55), (1, .8))
            for i, (x, y) in enumerate(vertices):
                point = QPointF(r.left() + x * r.width(), r.top() + y * r.height())
                path.moveTo(point) if i == 0 else path.lineTo(point)
            p.setPen(QPen(QColor("#93cbb3"), 2))
            p.drawPath(path)
            p.setPen(QColor("#66726f"))
            for name, (x, y) in zip("ABCDEFGHI", vertices):
                p.drawText(QRectF(r.left() + x * r.width() - 8, r.top() + y * r.height() + (2 if y > .7 else -17), 16, 16),
                           Qt.AlignmentFlag.AlignCenter, name)
        else:
            p.setPen(QPen(QColor("#333333"), 1.5))
            p.drawLine(r.bottomLeft(), r.topLeft())
            p.drawLine(r.bottomLeft(), r.bottomRight())
            for n, color in enumerate(("#242424", "#279f58", "#388bc7", "#ce5c97", "#db5656")):
                path = QPainterPath()
                for i in range(101):
                    t = i / 100
                    response = (0.78 - n * .12) * exp(-t * (7 + n * 4)) + .05 + n * .015
                    point = QPointF(r.left() + t * r.width(), r.bottom() - response * r.height())
                    path.moveTo(point) if i == 0 else path.lineTo(point)
                p.setPen(QPen(QColor(color), 1.6, Qt.PenStyle.DotLine))
                p.drawPath(path)
            p.setPen(QColor("#59616e"))
            p.drawText(QRectF(r.left(), r.bottom() + 4, r.width(), 22), Qt.AlignmentFlag.AlignCenter, "Time")
