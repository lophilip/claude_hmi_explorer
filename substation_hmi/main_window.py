"""Main window: palette, diagram, properties, points list and DNP3 controls."""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QActionGroup, QKeySequence, QColor, QPalette
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QDockWidget, QFileDialog, QLabel, QMainWindow, QMessageBox,
    QPlainTextEdit, QSpinBox, QTabWidget, QToolBar, QWidget, QSizePolicy,
)

from .controller import HmiController
from .elements import Element
from .outstation import OutstationConfig
from .points import PointList
from .sample import sample_project
from .scene import DiagramScene, DiagramView, Palette
from .widgets import ControlDialog, PointsPanel, PropertiesPanel, SetpointDialog
from .points import AO, BO

LINK_STYLES = {
    "Stopped": "background:#3A444E; color:#C9D1D9",
    "Listening": "background:#8A6A1F; color:#FFF4D6",
    "Master connected": "background:#1E7A45; color:#E6FFEF",
}


class MainWindow(QMainWindow):
    def __init__(self, project_path: str | None = None):
        super().__init__()
        self.ctl = HmiController()
        self.path: Path | None = None
        self.dirty = False

        self.scene = DiagramScene(self.ctl.points)
        self.view = DiagramView(self.scene)
        self.setCentralWidget(self.view)

        self.palette_list = Palette()
        self._dock("Elements", self.palette_list, Qt.LeftDockWidgetArea).setMaximumWidth(210)

        self.props = PropertiesPanel(self.ctl)
        self._dock("Properties", self.props, Qt.RightDockWidgetArea).setMinimumWidth(270)

        self.points_panel = PointsPanel(self.ctl)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(2000)
        self.tabs = QTabWidget()
        self.tabs.addTab(self.points_panel, "DNP3 points list")
        self.tabs.addTab(self.log_view, "Event log")
        self._dock("Outstation", self.tabs, Qt.BottomDockWidgetArea)

        self._build_toolbar()
        self.statusBar()

        # Wiring
        self.scene.selectionChanged.connect(self._selection_changed)
        self.scene.operateRequested.connect(self._operate)
        self.scene.elementDropped.connect(lambda el: self.props.show_element(el))
        self.scene.modified.connect(self._mark_dirty)
        self.props.changed.connect(self._mark_dirty)
        self.props.changed.connect(self.scene.update)
        self.ctl.pointChanged.connect(lambda _: self.scene.update())
        self.ctl.pointsReset.connect(self.scene.update)
        self.ctl.pointsReset.connect(self._mark_dirty)
        self.ctl.pointRenamed.connect(self.scene.rename_point)
        self.ctl.log.connect(self.log_view.appendPlainText)
        self.ctl.linkState.connect(self._link_state)
        self.points_panel.message.connect(lambda m: self.statusBar().showMessage(m, 6000))
        self.points_panel.importRequested.connect(self.import_points)
        self.points_panel.exportRequested.connect(self.export_points)

        if project_path:
            self.load_project(project_path)
        else:
            self._apply_project(sample_project())
            self.ctl.emit_log("Loaded the sample substation. Switch to Operate mode to control it.")
        self.resize(1500, 950)

    def _dock(self, title, widget, area) -> QDockWidget:
        d = QDockWidget(title, self)
        d.setObjectName(title)
        d.setWidget(widget)
        d.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable)
        self.addDockWidget(area, d)
        return d

    # --- toolbar ------------------------------------------------------------
    def _build_toolbar(self):
        tb = QToolBar("Main")
        tb.setObjectName("main")
        tb.setMovable(False)
        self.addToolBar(tb)

        def act(text, slot, shortcut=None, tip=None):
            a = QAction(text, self)
            a.triggered.connect(slot)
            if shortcut:
                a.setShortcut(shortcut)
            a.setToolTip(tip or text)
            tb.addAction(a)
            return a

        act("New", self.new_project, QKeySequence.New)
        act("Open…", self.open_project, QKeySequence.Open)
        act("Save", self.save_project, QKeySequence.Save)
        act("Save as…", lambda: self.save_project(ask=True), QKeySequence.SaveAs)
        tb.addSeparator()

        group = QActionGroup(self)
        self.act_edit = QAction("Edit", self, checkable=True, checked=True)
        self.act_operate = QAction("Operate", self, checkable=True)
        self.act_edit.setToolTip("Edit mode: drag elements from the palette, move and configure them")
        self.act_operate.setToolTip("Operate mode: click breakers, switches, controls and setpoints to operate them")
        for a in (self.act_edit, self.act_operate):
            group.addAction(a)
            tb.addAction(a)
        self.act_operate.toggled.connect(self._set_operate)
        self.act_rotate = act("Rotate", self._rotate_selected, "R", "Rotate the selected element 90° (R)")
        self.act_delete = act("Delete", self._delete_selected, QKeySequence.Delete, "Delete the selected elements (Del)")
        tb.addSeparator()

        tb.addWidget(QLabel(" Port "))
        self.port = self._spin(1, 65535, self.ctl.config.port)
        tb.addWidget(self.port)
        tb.addWidget(QLabel(" Outstation addr "))
        self.local_addr = self._spin(0, 65519, self.ctl.config.local_addr)
        tb.addWidget(self.local_addr)
        tb.addWidget(QLabel(" Master addr "))
        self.remote_addr = self._spin(0, 65519, self.ctl.config.remote_addr)
        tb.addWidget(self.remote_addr)
        self.act_start = act("Start outstation", self.toggle_outstation)
        self.link = QLabel()
        self.link.setMargin(4)
        tb.addWidget(self.link)
        self._link_state("Stopped")
        tb.addSeparator()
        sim = QCheckBox("Simulate analog noise")
        sim.setToolTip("Adds small random changes to analog inputs every 2 s so the master sees events")
        sim.toggled.connect(self.ctl.set_simulation)
        tb.addWidget(sim)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        tb.addWidget(spacer)

    def _spin(self, lo, hi, value):
        s = QSpinBox()
        s.setRange(lo, hi)
        s.setValue(value)
        s.valueChanged.connect(self._mark_dirty)
        return s

    def _link_state(self, state):
        self.link.setText(f"  {state}  ")
        self.link.setStyleSheet(LINK_STYLES.get(state, "") + "; border-radius:3px; font-weight:bold")
        running = self.ctl.running
        self.act_start.setText("Stop outstation" if running else "Start outstation")
        for w in (self.port, self.local_addr, self.remote_addr):
            w.setEnabled(not running)

    # --- modes and selection -----------------------------------------------------
    def _set_operate(self, operate: bool):
        self.scene.set_edit_mode(not operate)
        self.view.setDragMode(DiagramView.NoDrag if operate else DiagramView.RubberBandDrag)
        self.palette_list.setEnabled(not operate)
        self.act_rotate.setEnabled(not operate)
        self.act_delete.setEnabled(not operate)
        self.props.show_element(None)
        self.statusBar().showMessage("Operate mode: click a breaker, disconnector, control or setpoint"
                                     if operate else "Edit mode", 5000)

    def _selection_changed(self):
        sel = [i for i in self.scene.selectedItems() if isinstance(i, Element)]
        self.props.show_element(sel[0] if len(sel) == 1 else None)

    def _rotate_selected(self):
        for el in self.scene.selectedItems():
            if isinstance(el, Element):
                el.rotate()
        self._mark_dirty()

    def _delete_selected(self):
        if self.points_panel.table.hasFocus():
            return
        for el in self.scene.selectedItems():
            self.scene.removeItem(el)
        self.props.show_element(None)
        self._mark_dirty()

    def _operate(self, el: Element):
        role_type = el.BINDINGS.get("control")
        point = self.ctl.points.get(el.props.get("control", ""))
        if point is None:
            self.statusBar().showMessage(f"{el.props.get('label') or el.TITLE}: its control point is missing "
                                         "from the points list", 6000)
            return
        if role_type == BO:
            ControlDialog(self.ctl, el, self).exec()
        elif role_type == AO:
            SetpointDialog(self.ctl, el, self).exec()

    # --- outstation -------------------------------------------------------------
    def toggle_outstation(self):
        if self.ctl.running:
            self.ctl.stop()
            return
        self.ctl.config = OutstationConfig(port=self.port.value(), local_addr=self.local_addr.value(),
                                           remote_addr=self.remote_addr.value())
        err = self.ctl.start()
        if err:
            QMessageBox.warning(self, "Outstation", err)
        self._link_state("Listening" if self.ctl.running else "Stopped")

    # --- project files --------------------------------------------------------------
    def _mark_dirty(self, *_):
        self.dirty = True
        self._update_title()

    def _update_title(self):
        name = self.path.name if self.path else "Untitled"
        self.setWindowTitle(f"{'• ' if self.dirty else ''}{name} - Substation HMI")

    def _project_dict(self) -> dict:
        return {
            "version": 1,
            "dnp3": {"port": self.port.value(), "local_addr": self.local_addr.value(),
                     "remote_addr": self.remote_addr.value()},
            "points": self.ctl.points.to_list(),
            "elements": self.scene.to_list(),
        }

    def _apply_project(self, data: dict):
        if self.ctl.running:
            self.ctl.stop()
        self.ctl.replace_points(PointList.from_list(data.get("points", [])))
        self.scene.load_list(data.get("elements", []))
        d = data.get("dnp3", {})
        self.port.setValue(d.get("port", 20000))
        self.local_addr.setValue(d.get("local_addr", 1))
        self.remote_addr.setValue(d.get("remote_addr", 2))
        self.props.show_element(None)
        self.view.ensureVisible(self.scene.itemsBoundingRect().topLeft().x(), 0, 1, 1)
        self.view.horizontalScrollBar().setValue(self.view.horizontalScrollBar().minimum())
        self.view.verticalScrollBar().setValue(self.view.verticalScrollBar().minimum())
        self.dirty = False
        self._update_title()

    def _confirm_discard(self) -> bool:
        if not self.dirty:
            return True
        r = QMessageBox.question(self, "Unsaved changes", "Save changes to the current project first?",
                                 QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        if r == QMessageBox.Save:
            return self.save_project()
        return r == QMessageBox.Discard

    def new_project(self):
        if self._confirm_discard():
            self.path = None
            self._apply_project({"points": [], "elements": []})

    def open_project(self):
        if not self._confirm_discard():
            return
        path, _ = QFileDialog.getOpenFileName(self, "Open project", "", "HMI project (*.json)")
        if path:
            self.load_project(path)

    def load_project(self, path):
        try:
            data = json.loads(Path(path).read_text())
        except (OSError, ValueError) as e:
            QMessageBox.warning(self, "Open project", f"Could not open {path}:\n{e}")
            return
        self.path = Path(path)
        self._apply_project(data)
        self.ctl.emit_log(f"Opened {self.path}")

    def save_project(self, ask=False) -> bool:
        if ask or self.path is None:
            path, _ = QFileDialog.getSaveFileName(self, "Save project", str(self.path or "substation.json"),
                                                  "HMI project (*.json)")
            if not path:
                return False
            self.path = Path(path if path.endswith(".json") else path + ".json")
        self.path.write_text(json.dumps(self._project_dict(), indent=2, ensure_ascii=False))
        self.dirty = False
        self._update_title()
        self.statusBar().showMessage(f"Saved {self.path}", 4000)
        return True

    # --- spreadsheet import/export ------------------------------------------------------
    def import_points(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import points list", "",
                                              "Spreadsheets (*.xlsx *.csv);;Excel (*.xlsx);;CSV (*.csv)")
        if not path:
            return
        try:
            points, problems = PointList.import_file(path)
        except Exception as e:
            QMessageBox.warning(self, "Import points", f"Could not read {path}:\n{e}")
            return
        if problems and not points.points:
            QMessageBox.warning(self, "Import points", "Nothing was imported:\n" + "\n".join(problems[:20]))
            return
        msg = f"Replace the current {len(self.ctl.points)} points with {len(points)} points from the file?"
        if problems:
            msg += f"\n\n{len(problems)} problem(s) found:\n" + "\n".join(problems[:15])
        if QMessageBox.question(self, "Import points", msg) != QMessageBox.Yes:
            return
        self.ctl.replace_points(points)
        self.ctl.emit_log(f"Imported {len(points)} points from {path}")

    def export_points(self):
        path, selected = QFileDialog.getSaveFileName(self, "Export points list", "points.xlsx",
                                                     "Excel (*.xlsx);;CSV (*.csv)")
        if not path:
            return
        if not path.lower().endswith((".xlsx", ".csv")):
            path += ".csv" if "CSV" in selected else ".xlsx"
        try:
            self.ctl.points.export_file(path)
        except Exception as e:
            QMessageBox.warning(self, "Export points", f"Could not write {path}:\n{e}")
            return
        self.ctl.emit_log(f"Exported {len(self.ctl.points)} points to {path}")

    def closeEvent(self, event):
        if not self._confirm_discard():
            event.ignore()
            return
        self.ctl.stop()
        # The scene emits selectionChanged while it is being destroyed.
        self.scene.selectionChanged.disconnect(self._selection_changed)
        event.accept()


def apply_dark_palette(app: QApplication):
    app.setStyle("Fusion")
    p = QPalette()
    roles = {
        QPalette.Window: "#1B2127", QPalette.WindowText: "#D5DCE3", QPalette.Base: "#151A1F",
        QPalette.AlternateBase: "#1F262D", QPalette.Text: "#D5DCE3", QPalette.Button: "#262E36",
        QPalette.ButtonText: "#D5DCE3", QPalette.Highlight: "#2F6E9E", QPalette.HighlightedText: "#FFFFFF",
        QPalette.ToolTipBase: "#262E36", QPalette.ToolTipText: "#D5DCE3", QPalette.PlaceholderText: "#6B7682",
    }
    for role, color in roles.items():
        p.setColor(role, QColor(color))
    p.setColor(QPalette.Disabled, QPalette.Text, QColor("#56616C"))
    p.setColor(QPalette.Disabled, QPalette.ButtonText, QColor("#56616C"))
    app.setPalette(p)
