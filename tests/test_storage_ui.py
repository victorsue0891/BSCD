import csv
import json
import pytest

from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QFileDialog, QPushButton

from instrument_ui.app import MainWindow, STYLE
from instrument_ui.domain import Batch, CVConfig, RGB, Sample, Well, demo_ranking
from instrument_ui.storage import SessionStore
from instrument_ui.widgets import ResultPage


def test_export_keeps_cycles_raw_values_and_unique_names(tmp_path):
    well = Well(0, 0)
    batch = Batch("CV", "serial", {well}, CVConfig(), RGB(), firmware="028")
    batch.samples[well] = [Sample(well, cycle, 2, 1, -0.2, 42, f"raw {cycle}") for cycle in (1, 2)]
    store = SessionStore(tmp_path, batch)
    first, second = store.export(), store.export()
    assert first != second
    rows = list(csv.DictReader(next(first.glob("*.csv")).open(encoding="utf-8-sig")))
    assert [r["cycle"] for r in rows] == ["1", "2"]
    assert rows[0]["avg_raw"] == "-0.2"
    assert rows[0]["raw_line"] == "raw 1"
    assert json.loads((first / "metadata.json").read_text(encoding="utf-8"))["units"]["AVG"] is None
    store.close()


def test_demo_ranking_has_no_hardware_claims():
    wells = {Well(0, y) for y in range(5)}
    batch = Batch("CV", "demo", wells, CVConfig(), RGB())
    for w in wells:
        batch.samples[w] = [Sample(w, 1, 1, 0, w.y, 0, "")]
        batch.well_states[w] = "complete"
    ranks = demo_ranking(batch)
    assert list(ranks.values()) == [0, 0, 1, 2, 3]
    batch.source = "serial"
    assert demo_ranking(batch) == {}


@pytest.mark.parametrize("height", [480, 600])
def test_touch_layout_rgb_mapping_and_full_workflow(qapp, tmp_path, height):
    qapp.setStyle("Fusion")
    qapp.setStyleSheet(STYLE)
    w = MainWindow(tmp_path)
    if height == 480:
        w.resize(800, height)
    w.show()
    w.connect_demo()
    boot = w.pages.widget(0)
    assert not boot.background.isNull()
    assert not w.header.isVisible()
    boot.mode_buttons[0].click()
    assert w.pages.currentIndex() == 1
    assert w.header.isVisible()
    w.resolution.setCurrentText("256")
    w.settings_next()
    w.rgb_spins["R"].setValue(11)
    w.rgb_spins["B"].setValue(22)
    w.rgb_spins["G"].setValue(33)
    assert w.rgb() == RGB(11, 33, 22)
    w.show_page(4)
    w.plate.selected = {Well(5, y) for y in range(8)}
    w.start_measurement()
    for _ in range(100):
        QTest.qWait(20)
        if not w.controller.busy:
            break
    assert w.size().width() == 800 and w.size().height() == height
    assert w.controller.batch.state == "complete"
    assert sum(len(s) for s in w.controller.batch.samples.values()) == 2064
    assert all(w.controller.batch.well_states[s] == "complete" for s in w.plate.selected)
    assert w.save_btn.isEnabled()
    assert not w.start_btn.isEnabled()
    well = Well(5, 0)
    w.inspect_well(well)
    assert w.pages.currentWidget() is w.result_page
    assert w.result_page.plot.batch is w.display_batch
    assert w.result_page.plot.well == well
    exported = []
    w.export_data = exported.append
    next(b for b in w.result_page.findChildren(QPushButton) if b.text() == "Save data").click()
    assert exported == [{well}]
    next(b for b in w.result_page.findChildren(QPushButton) if b.text() == "Back").click()
    assert w.pages.currentIndex() == 4
    w.clear_plate()
    assert w.display_batch is None
    w.close()


def test_result_repeat_controls_preserve_all_cycles(qapp):
    well = Well(0, 0)
    batch = Batch("CV", "demo", {well}, CVConfig(), RGB())
    samples = [Sample(well, cycle, 2, 1, -0.2, 42, "raw") for cycle in (1, 2, 3)]
    batch.samples[well] = samples
    page = ResultPage()
    page.set_batch(batch, well)
    controls = {b.text(): b for b in page.findChildren(QPushButton)}
    for _ in range(5):
        controls["−"].click()
    assert page.plot.visible_cycles == 1
    for _ in range(5):
        controls["+"].click()
    assert page.plot.visible_cycles == 3
    assert page.counter.text() == "3 / 3"
    assert batch.samples[well] is samples and len(samples) == 3
    page.close()


def test_cv_reference_fields_keep_command_and_profile_values(qapp, tmp_path, monkeypatch):
    w = MainWindow(tmp_path / "data")
    w.choose_mode("CV")
    assert all(not field.isEnabled() for field in w.cv_legacy_fields)
    w.slope.setCurrentIndex(w.slope.findData(20))
    w.upper.setValue(1)
    w.lower.setValue(-1)
    w.resolution.setCurrentText("512")
    assert w.slope.currentText() == "20.000"
    assert w.cv_config().command == "APPCFG_RST 20 1000 -1000 512"
    profile = tmp_path / "profile.json"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (str(profile), ""))
    w.save_profile()
    w.cv_reset_btn.click()
    assert w.cv_config() == CVConfig()
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args: (str(profile), ""))
    w.load_profile()
    assert w.cv_config().command == "APPCFG_RST 20 1000 -1000 512"
    assert all(not field.isEnabled() for field in w.cv_legacy_fields)
    w.cv_next_btn.click()
    assert w.pages.currentIndex() == 3
    w.close()
