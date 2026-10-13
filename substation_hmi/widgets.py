"""Points table, element properties panel and operator control dialogs."""
from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QColorDialog, QComboBox, QDialog, QDoubleSpinBox, QFormLayout, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMenu, QPushButton, QSpinBox, QStyledItemDelegate, QTableView,
    QToolButton, QVBoxLayout, QWidget,
)

from .controller import HmiController
from .elements import (
    C_CLOSED, C_OPEN, C_UNKNOWN, VOLTAGE_COLORS, Element, LineElement, StatusElement,
    TextElement, TransformerElement,
)
from .points import AI, AO, BI, BO, COLUMNS, CONTROL_MODELS, HEADERS, POINT_TYPES, Point

TYPE_NAMES = {BI: "Binary input", BO: "Binary output", AI: "Analog input", AO: "Analog output"}


# =============================================================================
# Points table
# =============================================================================
class PointsModel(QAbstractTableModel):
    editError = Signal(str)

    def __init__(self, ctl: HmiController):
        super().__init__()
        self.ctl = ctl
        ctl.pointsReset.connect(self._reset)
        ctl.pointChanged.connect(self._value_changed)

    def _reset(self):
        self.beginResetModel()
        self.endResetModel()

    def _value_changed(self, name):
        for row, p in enumerate(self.ctl.points):
            if p.name == name:
                col = COLUMNS.index("value")
                self.dataChanged.emit(self.index(row, col), self.index(row, col))

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.ctl.points)

    def columnCount(self, parent=QModelIndex()):
        return len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return HEADERS[COLUMNS[section]]
        return None

    def _applies(self, p, field) -> bool:
        return {
            "control_model": p.type == BO,
            "feedback": p.type in (BO, AO),
            "min": p.type == AO, "max": p.type == AO,
            "units": p.type in (AI, AO),
        }.get(field, True)

    def data(self, index, role=Qt.DisplayRole):
        p = self.ctl.points.points[index.row()]
        field = COLUMNS[index.column()]
        value = getattr(p, field)
        if role == Qt.DisplayRole:
            if not self._applies(p, field):
                return ""
            if field == "value":
                return f"{p.value:g}  {self.ctl.points.state_text(p)}" if p.is_binary else f"{p.value:g}"
            if value is None:
                return ""
            if isinstance(value, float):
                return f"{value:g}"
            return str(value)
        if role == Qt.EditRole:
            return "" if value is None else value
        if role == Qt.ToolTipRole and field == "type":
            return TYPE_NAMES[p.type]
        if role == Qt.ForegroundRole and field == "value" and p.is_binary:
            return C_CLOSED if p.state else C_OPEN
        if role == Qt.ForegroundRole and not self._applies(p, field):
            return QColor("#555")
        return None

    def flags(self, index):
        p = self.ctl.points.points[index.row()]
        f = Qt.ItemIsSelectable | Qt.ItemIsEnabled
        if self._applies(p, COLUMNS[index.column()]):
            f |= Qt.ItemIsEditable
        return f

    def setData(self, index, value, role=Qt.EditRole):
        if role != Qt.EditRole:
            return False
        err = self.ctl.edit_point(index.row(), COLUMNS[index.column()], value)
        if err:
            self.editError.emit(err)
            return False
        return True


class ComboDelegate(QStyledItemDelegate):
    """Drop-down editor for constrained columns."""

    def __init__(self, ctl: HmiController, parent=None):
        super().__init__(parent)
        self.ctl = ctl

    def options(self, index) -> list[tuple[str, object]] | None:
        p = self.ctl.points.points[index.row()]
        field = COLUMNS[index.column()]
        if field == "type":
            return [(f"{t}  {TYPE_NAMES[t]}", t) for t in POINT_TYPES]
        if field == "control_model":
            return [(f"{m}  ({' / '.join(c)})", m) for m, c in CONTROL_MODELS.items()]
        if field == "event_class":
            return [("0  (static only)", 0), ("1", 1), ("2", 2), ("3", 3)]
        if field == "feedback":
            want = {BO: BI, AO: AI}.get(p.type)
            return [("(none)", "")] + [(n, n) for n in self.ctl.points.names(want)] if want else None
        if field == "value" and p.is_binary:
            probe = Point.from_dict({**p.to_dict(), "value": 0.0})
            off = self.ctl.points.state_text(probe)
            probe.value = 1.0
            return [(f"0  {off}", 0.0), (f"1  {self.ctl.points.state_text(probe)}", 1.0)]
        return None

    def createEditor(self, parent, option, index):
        opts = self.options(index)
        if opts is None:
            return super().createEditor(parent, option, index)
        cb = QComboBox(parent)
        for text, data in opts:
            cb.addItem(text, data)
        cb.activated.connect(lambda _: self.commitData.emit(cb))
        return cb

    def setEditorData(self, editor, index):
        if isinstance(editor, QComboBox):
            i = editor.findData(index.data(Qt.EditRole))
            editor.setCurrentIndex(max(i, 0))
            editor.showPopup()
        else:
            super().setEditorData(editor, index)

    def setModelData(self, editor, model, index):
        if isinstance(editor, QComboBox):
            model.setData(index, editor.currentData(), Qt.EditRole)
        else:
            model.setData(index, editor.text() if isinstance(editor, QLineEdit) else editor.property("value"))


class PointsPanel(QWidget):
    """The configurable DNP3 points list."""
    message = Signal(str)
    importRequested = Signal()
    exportRequested = Signal()

    def __init__(self, ctl: HmiController):
        super().__init__()
        self.ctl = ctl
        self.model = PointsModel(ctl)
        self.model.editError.connect(self.message)

        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setItemDelegate(ComboDelegate(ctl, self.table))
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed
                                   | QAbstractItemView.AnyKeyPressed)
        self.table.verticalHeader().setDefaultSectionSize(22)
        self.table.verticalHeader().hide()
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.Interactive)
        hdr.setStretchLastSection(True)
        for col, w in {"name": 150, "type": 50, "index": 50, "description": 220, "units": 50,
                       "event_class": 45, "control_model": 100, "feedback": 140, "value": 80}.items():
            self.table.setColumnWidth(COLUMNS.index(col), w)

        add = QToolButton()
        add.setText("Add point")
        add.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(add)
        for t in POINT_TYPES:
            menu.addAction(f"{t}  {TYPE_NAMES[t]}", lambda t=t: self._add(t))
        add.setMenu(menu)
        delete = QPushButton("Delete selected")
        delete.clicked.connect(self._delete)
        imp = QPushButton("Import spreadsheet…")
        imp.clicked.connect(self.importRequested)
        exp = QPushButton("Export spreadsheet…")
        exp.clicked.connect(self.exportRequested)
        self.summary = QLabel()
        self.summary.setStyleSheet("color: #8A96A3")
        ctl.pointsReset.connect(self._update_summary)
        self._update_summary()

        bar = QHBoxLayout()
        for w in (add, delete, imp, exp):
            bar.addWidget(w)
        bar.addStretch()
        bar.addWidget(self.summary)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.addLayout(bar)
        lay.addWidget(self.table)

    def _update_summary(self):
        counts = {t: 0 for t in POINT_TYPES}
        for p in self.ctl.points:
            counts[p.type] += 1
        self.summary.setText("   ".join(f"{t} {n}" for t, n in counts.items()) + "   (double-click a cell to edit)")

    def _add(self, ptype):
        p = self.ctl.add_point(ptype)
        row = self.ctl.points.points.index(p)
        self.table.selectRow(row)
        self.table.edit(self.model.index(row, COLUMNS.index("name")))

    def _delete(self):
        rows = sorted({i.row() for i in self.table.selectionModel().selectedRows()})
        if rows:
            self.ctl.remove_points([self.ctl.points.points[r].name for r in rows])


# =============================================================================
# Element properties
# =============================================================================
ROLE_TITLES = {"status": "Status point", "control": "Control point", "value": "Value point"}


class PropertiesPanel(QWidget):
    changed = Signal()

    def __init__(self, ctl: HmiController):
        super().__init__()
        self.ctl = ctl
        self.element: Element | None = None
        self.outer = QVBoxLayout(self)
        self.outer.setContentsMargins(8, 8, 8, 8)
        self.body = None
        self.outer.addStretch()
        ctl.pointsReset.connect(lambda: self.show_element(self.element))
        self.show_element(None)

    def show_element(self, el: Element | None):
        self.element = el
        if self.body:
            self.body.deleteLater()
        self.body = QWidget()
        form = QFormLayout(self.body)
        form.setContentsMargins(0, 0, 0, 0)
        self.outer.insertWidget(0, self.body)

        if el is None:
            hint = QLabel("Drag elements from the palette onto the diagram.\n\n"
                          "Select an element to configure its label, colour and "
                          "the DNP3 points it shows or controls.\n\n"
                          "Drag the square handles at a selected line's ends to reshape it.\n\n"
                          "Del deletes, R rotates. Ctrl+wheel zooms.")
            hint.setWordWrap(True)
            hint.setStyleSheet("color: #8A96A3")
            form.addRow(hint)
            return

        title = QLabel(el.TITLE)
        title.setStyleSheet("font-weight: bold; font-size: 13px")
        form.addRow(title)

        label = QLineEdit(el.props.get("label", ""))
        label.textEdited.connect(lambda t: self._set("label", t))
        form.addRow("Label", label)

        for role, ptype in el.BINDINGS.items():
            cb = QComboBox()
            cb.addItem("(none)", "")
            for p in self.ctl.points:
                if p.type == ptype:
                    cb.addItem(f"{p.name}   [{p.type} {p.index}]", p.name)
            current = el.props.get(role, "")
            i = cb.findData(current)
            if i < 0 and current:
                cb.addItem(f"{current}   (missing)", current)
                i = cb.count() - 1
            cb.setCurrentIndex(max(i, 0))
            cb.activated.connect(lambda _, cb=cb, role=role: self._set(role, cb.currentData()))
            form.addRow(f"{ROLE_TITLES[role]} ({ptype})", cb)

        if el.BINDINGS:
            create = QPushButton("Create points for this element")
            create.setToolTip("Adds suitable points to the points list and binds them here")
            create.clicked.connect(self._create_points)
            form.addRow(create)

        if isinstance(el, LineElement):
            form.addRow("Colour", self._color_picker("color"))
            width = QSpinBox()
            width.setRange(1, 14)
            width.setValue(el.props["width"])
            width.valueChanged.connect(lambda v: self._set("width", v, geometry=True))
            form.addRow("Width", width)
        if isinstance(el, TransformerElement):
            form.addRow("HV winding", self._color_picker("hv_color"))
            form.addRow("LV winding", self._color_picker("lv_color"))
        if isinstance(el, StatusElement):
            form.addRow("On colour", self._color_picker("on_color", presets=False))
            form.addRow("Off colour", self._color_picker("off_color", presets=False))
        if isinstance(el, TextElement):
            size = QSpinBox()
            size.setRange(6, 40)
            size.setValue(el.props["size"])
            size.valueChanged.connect(lambda v: self._set("size", v, geometry=True))
            form.addRow("Font size", size)
        if el.ROTATABLE:
            rot = QPushButton("Rotate 90°")
            rot.clicked.connect(lambda: (el.rotate(), self.changed.emit()))
            form.addRow(rot)

    def _color_picker(self, key, presets=True):
        cb = QComboBox()
        if presets:
            for name, hexv in VOLTAGE_COLORS.items():
                cb.addItem(self._swatch(hexv), name, hexv)
        current = self.element.props[key]
        if cb.findData(current) < 0:
            cb.addItem(self._swatch(current), current, current)
        cb.addItem("Custom…", "custom")
        cb.setCurrentIndex(cb.findData(current))

        def picked(_):
            value = cb.currentData()
            if value == "custom":
                c = QColorDialog.getColor(QColor(self.element.props[key]), self, "Choose colour")
                if not c.isValid():
                    cb.setCurrentIndex(cb.findData(self.element.props[key]))
                    return
                value = c.name()
            self._set(key, value)
            self.show_element(self.element)
        cb.activated.connect(picked)
        return cb

    @staticmethod
    def _swatch(hexv):
        from PySide6.QtGui import QIcon, QPixmap
        pm = QPixmap(14, 14)
        pm.fill(QColor(hexv))
        return QIcon(pm)

    def _set(self, key, value, geometry=False):
        el = self.element
        if el is None:
            return
        if geometry or key == "label":
            el.prepareGeometryChange()
        el.props[key] = value
        el.update()
        self.changed.emit()

    def _create_points(self):
        el = self.element
        created = self.ctl.create_points_for(el.KIND, el.props.get("label", ""))
        el.props.update(created)
        el.update()
        self.changed.emit()
        self.show_element(el)


# =============================================================================
# Operator dialogs
# =============================================================================
DIALOG_STYLE = """
QDialog { background: #1F262D; color: #D5DCE3; }
QLabel { color: #D5DCE3; }
QPushButton { padding: 8px 16px; font-weight: bold; border-radius: 3px; border: 1px solid #3A444E;
              background: #2A333C; color: #D5DCE3; }
QPushButton:disabled { color: #56616C; }
QPushButton:checked { border: 2px solid #4FA3E0; }
QPushButton#exec:enabled { background: #4FA3E0; color: #0E1216; }
"""


class ControlDialog(QDialog):
    """Select-before-operate dialog for a binary control point."""
    SELECT_TIMEOUT_S = 10

    def __init__(self, ctl: HmiController, el: Element, parent=None):
        super().__init__(parent)
        self.ctl = ctl
        self.ctl_point = ctl.points.get(el.props["control"])
        self.status_point = ctl.points.get(el.props.get("status", "")) or self.ctl_point
        self.selected = None
        self.setWindowTitle(f"Control: {el.props.get('label') or self.ctl_point.name}")
        self.setStyleSheet(DIALOG_STYLE)
        self.setMinimumWidth(340)

        head = QLabel(f"<b style='font-size:15px'>{el.props.get('label') or el.TITLE}</b><br>"
                      f"<span style='color:#8A96A3'>{self.ctl_point.name} · BO {self.ctl_point.index}"
                      f" · {self.ctl_point.control_model}</span>")
        self.status = QLabel()
        self.prompt = QLabel("Select an operation, then Execute.")
        self.prompt.setStyleSheet("color:#8A96A3")

        off, on = self.ctl_point.captions()
        self.btn_off = QPushButton(off.upper())
        self.btn_on = QPushButton(on.upper())
        for b, state, color in ((self.btn_off, False, C_OPEN), (self.btn_on, True, C_CLOSED)):
            b.setCheckable(True)
            b.setStyleSheet(f"color: {color.name()}; font-size: 14px;")
            b.clicked.connect(lambda _, s=state: self._select(s))
        self.execute = QPushButton("Execute")
        self.execute.setObjectName("exec")
        self.execute.setEnabled(False)
        self.execute.clicked.connect(self._execute)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)

        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._timeout)

        ops = QHBoxLayout()
        ops.addWidget(self.btn_off)
        ops.addWidget(self.btn_on)
        actions = QHBoxLayout()
        actions.addStretch()
        actions.addWidget(cancel)
        actions.addWidget(self.execute)
        lay = QVBoxLayout(self)
        lay.addWidget(head)
        lay.addWidget(self.status)
        lay.addSpacing(6)
        lay.addLayout(ops)
        lay.addWidget(self.prompt)
        lay.addSpacing(6)
        lay.addLayout(actions)
        self._refresh_status()
        ctl.pointChanged.connect(self._refresh_status)

    def _refresh_status(self, *_):
        p = self.status_point
        color = (C_CLOSED if p.state else C_OPEN).name()
        self.status.setText(f"Current state: <b style='color:{color}'>{self.ctl.points.state_text(p)}</b>"
                            f"  <span style='color:#8A96A3'>({p.name})</span>")

    def _select(self, state: bool):
        self.selected = state
        self.btn_on.setChecked(state)
        self.btn_off.setChecked(not state)
        self.execute.setEnabled(True)
        verb = self.ctl_point.captions()[int(state)].upper()
        self.prompt.setText(f"Selected {verb}. Press Execute within {self.SELECT_TIMEOUT_S} s.")
        self.prompt.setStyleSheet("color:#E8A33D")
        self.timer.start(self.SELECT_TIMEOUT_S * 1000)

    def _timeout(self):
        self.selected = None
        self.btn_on.setChecked(False)
        self.btn_off.setChecked(False)
        self.execute.setEnabled(False)
        self.prompt.setText("Selection timed out. Select again.")
        self.prompt.setStyleSheet("color:#8A96A3")

    def _execute(self):
        if self.selected is None:
            return
        err = self.ctl.operate_binary(self.ctl_point.name, self.selected)
        if err:
            self.prompt.setText(err)
            self.prompt.setStyleSheet(f"color:{C_UNKNOWN.name()}")
            return
        self.accept()


class SetpointDialog(QDialog):
    """Send a new value to an analog output point."""

    def __init__(self, ctl: HmiController, el: Element, parent=None):
        super().__init__(parent)
        self.ctl = ctl
        self.point = ctl.points.get(el.props["control"])
        p = self.point
        self.setWindowTitle(f"Setpoint: {el.props.get('label') or p.name}")
        self.setStyleSheet(DIALOG_STYLE + "QDoubleSpinBox { padding: 6px; font-size: 15px; }")
        self.setMinimumWidth(320)
        lo = -1e9 if p.min is None else p.min
        hi = 1e9 if p.max is None else p.max
        head = QLabel(f"<b style='font-size:15px'>{el.props.get('label') or el.TITLE}</b><br>"
                      f"<span style='color:#8A96A3'>{p.name} · AO {p.index}</span>")
        cur = QLabel(f"Current value: <b>{p.display_value()}</b>")
        self.spin = QDoubleSpinBox()
        self.spin.setDecimals(2)
        self.spin.setRange(lo, hi)
        self.spin.setValue(p.value)
        if p.units:
            self.spin.setSuffix(f" {p.units}")
        rng = QLabel(f"Allowed range: {'' if p.min is None else f'{p.min:g}'} to "
                     f"{'' if p.max is None else f'{p.max:g}'} {p.units}".strip())
        rng.setStyleSheet("color:#8A96A3")
        self.err = QLabel()
        self.err.setStyleSheet(f"color:{C_UNKNOWN.name()}")
        send = QPushButton("Send")
        send.setObjectName("exec")
        send.clicked.connect(self._send)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        actions = QHBoxLayout()
        actions.addStretch()
        actions.addWidget(cancel)
        actions.addWidget(send)
        lay = QVBoxLayout(self)
        for w in (head, cur, self.spin, rng, self.err):
            lay.addWidget(w)
        lay.addLayout(actions)

    def _send(self):
        err = self.ctl.operate_analog(self.point.name, self.spin.value())
        if err:
            self.err.setText(err)
            return
        self.accept()
