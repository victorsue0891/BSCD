"""PyQt layouts following UI/UI 的圖片; measurement semantics stay in Controller."""
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QFormLayout, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QProgressBar, QPushButton, QSizePolicy, QSpinBox, QStackedWidget, QVBoxLayout, QWidget,
)
from .visuals import ASSETS, BootScreen, OutlineArrows, SweepPreview, home_icon
from .widgets import PlateWidget, ResultPage


STYLE = """
QWidget { font-family:'Noto Sans CJK TC','Microsoft JhengHei',sans-serif; font-size:13px; color:#23272d; }
QMainWindow, QDialog, QWidget#shell { background:white; }
QFrame#card { background:white; border:1px solid #d6d9df; border-radius:6px; }
QFrame#sidePanel { background:white; border:2px solid #bec2cb; border-radius:5px; }
QLabel#pageTitle { font-size:23px; font-weight:600; }
QLabel#muted { color:#7b808b; }
QLabel#notice { color:#7f75b8; font-size:11px; padding:3px; }
QPushButton { background:white; border:1px solid #aaaeb7; border-radius:4px;
    padding:5px 12px; min-height:24px; }
QPushButton:hover { background:#f0edfc; border-color:#8174c8; }
QPushButton:pressed { background:#dfd9f6; }
QPushButton#primary { background:#8175cc; color:white; border:1px solid #8175cc; }
QPushButton#start { background:#19ce55; color:white; border:none; }
QPushButton#stop { background:#d96970; color:white; border:none; }
QPushButton#dark { background:#191c21; color:white; border:none; }
QPushButton#home { color:#877acb; border:none; font-weight:600; }
QPushButton:disabled, QPushButton#primary:disabled, QPushButton#start:disabled, QPushButton#stop:disabled {
    background:#f0f1f4; color:#a5a9b2; border-color:#e2e4e9; }
QSpinBox, QDoubleSpinBox, QComboBox { background:#e1e3e8; border:1px solid #d1d4db;
    border-radius:4px; padding:4px 6px; min-height:22px; }
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button { width:24px; }
QProgressBar { border:none; background:#eef0f3; max-height:5px; }
QProgressBar::chunk { background:#8175cc; }
QPlainTextEdit { background:white; border:1px solid #d9dfeb; }
"""


def button(text, action, name=None):
    b = QPushButton(text)
    if name:
        b.setObjectName(name)
    b.clicked.connect(action)
    return b


def label(text, name=None):
    item = QLabel(text)
    item.setWordWrap(True)
    if name:
        item.setObjectName(name)
    return item


def card(name="card"):
    box = QFrame()
    box.setObjectName(name)
    layout = QVBoxLayout(box)
    layout.setContentsMargins(12, 10, 12, 10)
    layout.setSpacing(8)
    return box, layout


class ReferenceScreens:
    def construct_shell(self):
        central = QWidget()
        central.setObjectName("shell")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.header = QWidget()
        h = QHBoxLayout(self.header)
        h.setContentsMargins(10, 5, 10, 5)
        h.setSpacing(8)
        logo = QLabel()
        logo.setPixmap(QPixmap(str(ASSETS / "pimex-logo.png")).scaled(
            165, 53, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        logo.setFixedSize(165, 53)
        h.addWidget(logo)
        self.header_title = label("CV Settings", "pageTitle")
        h.addWidget(self.header_title)
        self.home_btn = button("Home page", lambda: self.show_page(0), "home")
        self.home_btn.setIcon(home_icon())
        h.addWidget(self.home_btn)
        h.addStretch()
        self.repeat_label = label("Repeat  1", "muted")
        self.repeat_label.setWordWrap(False)
        h.addWidget(self.repeat_label)
        self.connect_btn = button("連線", self.connection_dialog)
        self.log_btn = button("紀錄", self.log_dialog)
        h.addWidget(self.connect_btn)
        h.addWidget(self.log_btn)
        root.addWidget(self.header)
        self.divider = QFrame()
        self.divider.setFrameShape(QFrame.Shape.HLine)
        self.divider.setStyleSheet("color:#e1e3e8;")
        root.addWidget(self.divider)
        self.pages = QStackedWidget()
        root.addWidget(self.pages, 1)
        for build in (self.build_home, self.build_cv, self.build_ca, self.build_rgb, self.build_plate, self.build_result):
            self.pages.addWidget(build())
        self.footer = QWidget()
        footer = QHBoxLayout(self.footer)
        footer.setContentsMargins(10, 2, 10, 3)
        self.connection_status = label("未連線", "muted")
        self.connection_status.setWordWrap(False)
        self.connection_status.setMaximumWidth(270)
        footer.addWidget(self.connection_status)
        self.status_text = label("請選擇量測模式", "muted")
        self.status_text.setWordWrap(False)
        footer.addWidget(self.status_text, 1)
        root.addWidget(self.footer)
        self.pages.currentChanged.connect(self.update_chrome)
        self.update_chrome(0)

    def update_chrome(self, index):
        for widget in (self.header, self.divider, self.footer):
            widget.setVisible(index != 0)
        names = {1: f"{self.mode} Settings", 2: "CA Settings", 3: f"{self.mode} 96-well",
                 4: f"{self.mode} 96-well", 5: f"{self.mode} results"}
        self.header_title.setText(names.get(index, "PIMEX"))
        self.repeat_label.setVisible(index in (3, 4))

    def build_home(self):
        page = BootScreen()
        page.mode_selected.connect(self.choose_mode)
        self.controls.extend(page.mode_buttons)
        self.controls.extend((page.connect_btn, page.log_btn))
        self.demo_btn, self.replay_btn = page.demo_btn, page.replay_btn
        self.demo_btn.clicked.connect(self.connect_demo)
        self.replay_btn.clicked.connect(self.open_replay)
        page.connect_btn.clicked.connect(self.connection_dialog)
        page.log_btn.clicked.connect(self.log_dialog)
        return page

    def build_cv(self):
        page = QWidget()
        page.setObjectName("cvSettings")
        page.setStyleSheet("""
            QWidget#cvSettings { background:white; }
            QWidget#cvSettings QLabel { font-size:13px; }
            QWidget#cvSettings QLineEdit, QWidget#cvSettings QComboBox,
            QWidget#cvSettings QDoubleSpinBox {
                background:#dfe1e6; border:1px solid #ccd0d7; border-radius:3px;
                padding:1px 4px; min-height:19px; font-size:12px;
            }
            QWidget#cvSettings QLineEdit:disabled, QWidget#cvSettings QComboBox:disabled {
                color:#717680; background:#e3e5e9;
            }
            QWidget#cvSettings QAbstractSpinBox::up-button,
            QWidget#cvSettings QAbstractSpinBox::down-button { width:15px; }
        """)
        layout = QHBoxLayout(page)
        layout.setContentsMargins(14, 8, 14, 10)
        layout.setSpacing(9)
        left, right = QVBoxLayout(), QVBoxLayout()
        left.setSpacing(9)
        right.setSpacing(9)
        self.cv_legacy_fields = []

        def display(value, width=76, tooltip="本版暫不支援設定；不傳送此欄位。"):
            field = QLineEdit(value)
            field.setFixedWidth(width)
            field.setAlignment(Qt.AlignmentFlag.AlignCenter)
            field.setEnabled(False)
            field.setToolTip(tooltip)
            self.cv_legacy_fields.append(field)
            return field

        def field_row(title, field, suffix=""):
            row = QHBoxLayout()
            row.setSpacing(5)
            caption = QLabel(f"<span>{title}</span>")
            caption.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Preferred)
            row.addWidget(caption)
            row.addWidget(field)
            if suffix:
                row.addWidget(QLabel(suffix))
            row.addStretch()
            return row

        box, col = card()
        col.setContentsMargins(12, 10, 12, 10)
        col.setSpacing(10)
        self.cv_ei = display("Auto", 102, "初始電位由 ESP32 決定；本版不提供手動 Ei 設定。")
        col.addLayout(field_row("Set Ewe to Ei =", self.cv_ei, "V"))
        self.cv_range = QComboBox()
        self.cv_range.addItem("−2.5 V; 2.5 V")
        self.cv_range.setFixedWidth(126)
        self.cv_range.setEnabled(False)
        self.cv_range.setToolTip("固定的介面電壓範圍。")
        self.cv_legacy_fields.append(self.cv_range)
        col.addLayout(field_row("E Range =", self.cv_range))
        left.addWidget(box)

        box, col = card()
        col.setContentsMargins(12, 12, 12, 12)
        col.setSpacing(7)
        self.slope = QComboBox()
        for value in range(10, 51, 5):
            self.slope.addItem(f"{value:.3f}", value)
        self.slope.setCurrentIndex(self.slope.findData(15))
        self.slope.setFixedWidth(88)
        self.slope.setToolTip("掃描速率：mV/s。")
        self.upper, self.lower = self.voltage_spin(2.5), self.voltage_spin(-2.5)
        for spin in (self.upper, self.lower):
            spin.setDecimals(3)
            spin.setMinimumWidth(0)
            spin.setFixedWidth(78)
        self.resolution = QComboBox()
        self.resolution.addItems(["256", "512", "1024"])
        self.resolution.setCurrentText("1024")
        self.resolution.setFixedWidth(88)
        self.resolution.setToolTip("依目前韌體契約使用 256／512／1024；參考圖 2048 的對應待確認。")
        for title, field, suffix in (
            ("Scan Ewe with dE/dt =", self.slope, "mV/s"),
            ("Max. Sensing Voltage E<sub>1</sub> =", self.upper, "V  (Vertex potential)"),
            ("Min. Sensing Voltage E<sub>2</sub> =", self.lower, "V  (Reverse scan)"),
            ("Signal Digital Quantification =", self.resolution, ""),
        ):
            col.addLayout(field_row(title, field, suffix), 1)
        col.addLayout(field_row("Measure &lt;I&gt; over the last", display("—", 40), "% of the step duration"), 1)
        col.addLayout(field_row("Record &lt;I&gt; averaged over N =", display("—", 40), "voltage steps"), 1)
        col.addLayout(field_row("Repeat Times nc =", display("1", 40, "本版不提供 Repeat 設定；掃描命令固定傳送 1。"), "time(s)"), 1)
        left.addWidget(box, 1)

        box, col = card()
        col.setContentsMargins(9, 9, 9, 9)
        self.cv_preview = SweepPreview("CV")
        self.cv_preview.setMinimumHeight(130)
        col.addWidget(self.cv_preview, 1)
        col.addSpacing(12)
        duration = QHBoxLayout()
        duration.setSpacing(5)
        duration.addWidget(QLabel("Available Duration"))
        duration.addStretch()
        summary = QVBoxLayout()
        summary.setSpacing(4)
        for name in ("min", "max"):
            summary.addLayout(field_row(name, display("—", 60, "尚無已確認的韌體百分比對應。"), "%"))
        duration.addLayout(summary)
        col.addLayout(duration)
        accountable = QHBoxLayout()
        accountable.setSpacing(5)
        accountable.addWidget(QLabel("Max. Accountable"))
        value = QLabel("dynamic")
        value.setStyleSheet("border-bottom:1px solid #777; font-size:12px;")
        value.setToolTip("示意欄位；實際階數與時序由 ESP32 回覆。")
        accountable.addWidget(value)
        accountable.addWidget(QLabel("points per cycle"))
        col.addLayout(accountable)
        col.addSpacing(6)
        right.addWidget(box, 1)
        row = QHBoxLayout()
        row.setContentsMargins(8, 0, 24, 0)
        row.addWidget(OutlineArrows())
        row.addStretch()
        buttons = QVBoxLayout()
        buttons.setSpacing(8)
        self.cv_next_btn = button("Next", self.settings_next, "primary")
        self.cv_reset_btn = button("Reset", self.reset_cv)
        for item in (self.cv_next_btn, self.cv_reset_btn):
            item.setFixedWidth(86)
            buttons.addWidget(item)
        row.addLayout(buttons)
        right.addLayout(row)
        profile = QHBoxLayout()
        profile.addStretch()
        for text, action in (("載入參數", self.load_profile), ("儲存參數", self.save_profile)):
            item = button(text, action, "home")
            item.setStyleSheet("font-size:11px; min-height:16px; padding:1px 5px;")
            profile.addWidget(item)
        right.addLayout(profile)
        layout.addLayout(left, 54)
        layout.addLayout(right, 46)
        return page

    @staticmethod
    def voltage_spin(value):
        spin = QDoubleSpinBox()
        spin.setRange(-2.5, 2.5)
        spin.setDecimals(1)
        spin.setSingleStep(0.1)
        spin.setValue(value)
        spin.setMinimumWidth(90)
        return spin

    def build_ca(self):
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(14, 8, 14, 8)
        left, right = QVBoxLayout(), QVBoxLayout()
        box, col = card()
        col.addWidget(label("Sensing Column          本批選孔", "muted"))
        col.addWidget(label("Parameter Copied From       —", "muted"))
        left.addWidget(box)
        box, col = card()
        col.addWidget(label("E Range =  −2.5 V; +2.5 V", "muted"))
        self.ca_initial, self.ca_target = self.voltage_spin(0), self.voltage_spin(1)
        self.duration = QDoubleSpinBox()
        self.duration.setRange(0.1, 3600)
        self.duration.setDecimals(1)
        self.duration.setValue(30)
        self.interval = QDoubleSpinBox()
        self.interval.setRange(0.05, 3600)
        self.interval.setDecimals(2)
        self.interval.setSingleStep(0.05)
        self.interval.setValue(0.1)
        form = QFormLayout()
        form.setVerticalSpacing(16)
        for text, widget in (("Initial Voltage (V)", self.ca_initial), ("Apply Sensing Voltage (V)", self.ca_target),
                             ("Duration (s)", self.duration), ("Sensing Resolution dt (s)", self.interval)):
            form.addRow(text, widget)
        col.addLayout(form)
        col.addStretch()
        left.addWidget(box, 1)
        left.addWidget(label("CA 模擬操作；實機參數對應待確認。", "notice"))
        right.addWidget(SweepPreview("CA"), 1)
        row = QHBoxLayout()
        row.addWidget(label("↑    ↓", "pageTitle"))
        row.addStretch()
        buttons = QVBoxLayout()
        buttons.addWidget(button("Next", self.settings_next, "primary"))
        buttons.addWidget(button("Reset", self.reset_ca))
        row.addLayout(buttons)
        right.addLayout(row)
        layout.addLayout(left, 1)
        layout.addLayout(right, 1)
        return page

    def reset_ca(self):
        self.ca_initial.setValue(0)
        self.ca_target.setValue(1)
        self.duration.setValue(30)
        self.interval.setValue(0.1)

    def build_rgb(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(35, 12, 35, 14)
        title = label("Well Light Intensity Configuration", "pageTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        layout.addStretch()
        self.rgb_spins = {}
        for name, color in (("R", "#ff9da5"), ("B", "#9cc4fa"), ("G", "#72e2a0")):
            row = QHBoxLayout()
            row.addStretch()
            row.addWidget(QLabel(name))
            spin = QSpinBox()
            spin.setRange(0, 255)
            spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
            spin.setFixedSize(180, 56)
            spin.setStyleSheet(f"QSpinBox {{ background:{color}; border:none; font-size:28px; border-radius:5px; }}")
            spin.valueChanged.connect(self.update_rgb_preview)
            self.rgb_spins[name] = spin
            row.addWidget(spin)
            row.addStretch()
            layout.addLayout(row)
            layout.addSpacing(12)
        self.rgb_preview = QLabel()
        self.rgb_preview.hide()
        layout.addStretch()
        row = QHBoxLayout()
        row.addWidget(button("Back", lambda: self.show_page(1 if self.mode == "CV" else 2)))
        row.addStretch()
        reset = button("RESET", self.reset_rgb, "dark")
        reset.setFixedSize(140, 54)
        row.addWidget(reset)
        row.addSpacing(80)
        next_button = button("NEXT", lambda: self.show_page(4))
        next_button.setFixedSize(140, 54)
        row.addWidget(next_button)
        row.addStretch()
        layout.addLayout(row)
        self.update_rgb_preview()
        return page

    def build_plate(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 3, 12, 2)
        self.plate_title = label("CV 96-well")
        self.plate_title.hide()  # Common header carries the title as in the reference.
        row = QHBoxLayout()
        self.plate = PlateWidget()
        self.plate.selection_changed.connect(self.refresh)
        self.plate.inspect_well.connect(self.inspect_well)
        row.addWidget(self.plate, 1)
        sidebar = QWidget()
        sidebar.setFixedWidth(126)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(0, 0, 0, 0)
        side.setSpacing(6)
        heading = label("Well Selection")
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        side.addWidget(heading)
        box, col = card("sidePanel")
        col.setContentsMargins(8, 7, 8, 7)
        self.select_btn = button("Select all", self.select_all)
        self.clear_btn = button("CLR all", self.clear_plate)
        col.addWidget(self.select_btn)
        col.addWidget(self.clear_btn)
        side.addWidget(box)
        side.addWidget(label("Well Light Selection"))
        box, col = card("sidePanel")
        col.setContentsMargins(25, 7, 25, 7)
        self.plate_rgb = {}
        for name, color in (("R", "#ff9da5"), ("B", "#9cc4fa"), ("G", "#72e2a0")):
            block = QLabel("0")
            block.setAlignment(Qt.AlignmentFlag.AlignCenter)
            block.setMinimumHeight(33)
            block.setStyleSheet(f"background:{color}; border-radius:4px; font-size:18px;")
            block.setToolTip(name)
            self.plate_rgb[name] = block
            col.addWidget(block)
        side.addWidget(box)
        self.rgb_summary = label("")
        self.rgb_summary.hide()
        self.selection_label = label("0 / 96")
        self.selection_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        side.addWidget(self.selection_label)
        side.addStretch()
        self.back_btn = button("Back", lambda: self.show_page(3), "dark")
        self.save_btn = button("SAVE", lambda: self.export_data(), "primary")
        self.start_btn = button("Start", self.start_measurement, "start")
        self.stop_btn = button("Stop", self.controller.stop, "stop")
        for b in (self.back_btn, self.save_btn, self.start_btn, self.stop_btn):
            side.addWidget(b)
        row.addWidget(sidebar)
        layout.addLayout(row, 1)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        layout.addWidget(self.progress)
        self.measure_status = label("點欄號選整欄；完成後點孔位檢視曲線。", "muted")
        layout.addWidget(self.measure_status)
        return page

    def build_result(self):
        self.result_page = ResultPage()
        self.result_page.save_requested.connect(lambda well: self.export_data({well}))
        self.result_page.close_requested.connect(lambda: self.show_page(4))
        return self.result_page
