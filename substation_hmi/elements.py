"""Single line diagram elements drawn on a QGraphicsScene.

Each element stores its configuration in `props` (label, point bindings,
colours) and looks its point values up by name from the scene's PointList at
paint time, so a value change only needs a repaint.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPainterPathStroker, QPen
from PySide6.QtWidgets import QGraphicsItem, QStyleOptionGraphicsItem

from .points import AI, AO, BI, BO

GRID = 10

C_BG = QColor("#151A1F")
C_GRID = QColor("#252C33")
C_FG = QColor("#D5DCE3")
C_DIM = QColor("#6B7682")
C_CLOSED = QColor("#E0413A")   # red = closed / energised (North American convention)
C_OPEN = QColor("#2FB463")     # green = open / de-energised
C_UNKNOWN = QColor("#D946EF")  # magenta = unbound or missing point
C_SELECT = QColor("#4FA3E0")
C_PANEL = QColor("#1F262D")

VOLTAGE_COLORS = {
    "400 kV": "#5B8DEF",
    "220 kV": "#E8A33D",
    "132 kV": "#C76BE0",
    "66 kV": "#3FC1C9",
    "33 kV": "#F2D544",
    "11 kV": "#F08A5D",
    "LV": "#C9D1D9",
}


def snap(p: QPointF) -> QPointF:
    return QPointF(round(p.x() / GRID) * GRID, round(p.y() / GRID) * GRID)


def label_font(size: int = 9, bold: bool = False) -> QFont:
    f = QFont("DejaVu Sans Mono")
    f.setStyleHint(QFont.Monospace)
    f.setPointSize(size)
    f.setBold(bold)
    return f


class Element(QGraphicsItem):
    KIND = ""
    TITLE = ""
    BINDINGS: dict[str, str] = {}  # role -> required point type
    DEFAULTS: dict = {}
    ROTATABLE = False

    def __init__(self, props: dict | None = None):
        super().__init__()
        self.props = {"label": "", **{r: "" for r in self.BINDINGS}, **self.DEFAULTS}
        if self.ROTATABLE:
            self.props.setdefault("orient", "v")
        self.props.update(props or {})
        self.setFlags(QGraphicsItem.ItemIsSelectable | QGraphicsItem.ItemIsMovable
                      | QGraphicsItem.ItemSendsGeometryChanges)
        self.setAcceptHoverEvents(True)

    # --- points ----------------------------------------------------------
    def point(self, role: str):
        scene = self.scene()
        name = self.props.get(role)
        if scene is None or not name:
            return None
        return scene.points.get(name)

    def binary_state(self, role: str) -> bool | None:
        """True/False from the bound point, None if unbound or missing.

        Elements outside a scene (palette icons) draw as closed."""
        if self.scene() is None:
            return True
        p = self.point(role)
        return None if p is None else p.state

    def operable(self) -> bool:
        return False

    @property
    def horizontal(self) -> bool:
        return self.props.get("orient") == "h"

    def rotate(self) -> None:
        if self.ROTATABLE:
            self.prepareGeometryChange()
            self.props["orient"] = "v" if self.horizontal else "h"
            self.update()

    # --- geometry helpers -----------------------------------------------
    def symbol_rect(self) -> QRectF:
        """Bounding box of the symbol in its vertical orientation."""
        return QRectF(-20, -30, 40, 60)

    def oriented(self, r: QRectF) -> QRectF:
        if not self.horizontal:
            return r
        # painter.rotate(-90) maps (x, y) -> (y, -x)
        return QRectF(r.top(), -r.right(), r.height(), r.width())

    def label_rect(self) -> QRectF:
        s = self.oriented(self.symbol_rect())
        if self.horizontal:
            return QRectF(s.left() - 40, s.bottom() + 2, s.width() + 80, 34)
        return QRectF(s.right() + 6, -17, 150, 34)

    def boundingRect(self) -> QRectF:
        return self.oriented(self.symbol_rect()).united(self.label_rect()).adjusted(-3, -3, 3, 3)

    def shape(self) -> QPainterPath:
        path = QPainterPath()
        path.addRect(self.oriented(self.symbol_rect()).adjusted(-4, -4, 4, 4))
        return path

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange and self.scene():
            return snap(value)
        if change == QGraphicsItem.ItemPositionHasChanged and self.scene():
            self.scene().changed_by_user()
        return super().itemChange(change, value)

    # --- painting ----------------------------------------------------------
    def paint(self, painter: QPainter, option, widget=None):
        painter.setRenderHint(QPainter.Antialiasing)
        painter.save()
        if self.horizontal:
            painter.rotate(-90)
        self.paint_symbol(painter)
        painter.restore()
        self.paint_label(painter)
        if self.isSelected():
            painter.setPen(QPen(C_SELECT, 1, Qt.DashLine))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(self.oriented(self.symbol_rect()).adjusted(-5, -5, 5, 5))

    def paint_symbol(self, painter: QPainter):
        pass

    def label_lines(self) -> list[str]:
        return [self.props.get("label", "")]

    def paint_label(self, painter: QPainter):
        lines = [t for t in self.label_lines() if t]
        if not lines:
            return
        painter.setPen(C_FG)
        painter.setFont(label_font())
        align = Qt.AlignHCenter | Qt.AlignTop if self.horizontal else Qt.AlignLeft | Qt.AlignVCenter
        painter.drawText(self.label_rect(), align, "\n".join(lines))

    # --- persistence -------------------------------------------------------
    def to_dict(self) -> dict:
        return {"kind": self.KIND, "x": self.pos().x(), "y": self.pos().y(), "props": dict(self.props)}


def _state_color(state: bool | None) -> QColor:
    if state is None:
        return C_UNKNOWN
    return C_CLOSED if state else C_OPEN


class LineElement(Element):
    """A conductor between two snapped endpoints. Optional BI status: when the
    bound point is 0 the line is drawn dashed and dimmed (de-energised)."""
    KIND = "line"
    TITLE = "Line"
    BINDINGS = {"status": BI}
    DEFAULTS = {"color": VOLTAGE_COLORS["132 kV"], "width": 3, "dx": 0, "dy": 80}
    HANDLE = 6

    def __init__(self, props=None):
        super().__init__(props)
        self._drag = None

    def end(self) -> QPointF:
        return QPointF(self.props["dx"], self.props["dy"])

    def boundingRect(self) -> QRectF:
        r = QRectF(QPointF(0, 0), self.end()).normalized()
        pad = max(self.props["width"], self.HANDLE) + 4
        r = r.adjusted(-pad, -pad, pad, pad)
        if self.props.get("label"):
            r = r.united(self.label_rect())
        return r

    def label_rect(self) -> QRectF:
        mid = self.end() / 2
        return QRectF(mid.x() + 8, mid.y() - 9, 160, 18)

    def shape(self) -> QPainterPath:
        path = QPainterPath(QPointF(0, 0))
        path.lineTo(self.end())
        stroker = QPainterPathStroker()
        stroker.setWidth(max(12, self.props["width"] + 8))
        return stroker.createStroke(path)

    def paint(self, painter: QPainter, option, widget=None):
        painter.setRenderHint(QPainter.Antialiasing)
        color = QColor(self.props["color"])
        pen = QPen(color, self.props["width"], Qt.SolidLine, Qt.FlatCap)
        if self.props.get("status") and self.binary_state("status") is False:
            color.setAlphaF(0.45)
            pen.setColor(color)
            pen.setStyle(Qt.DashLine)
        painter.setPen(pen)
        painter.drawLine(QPointF(0, 0), self.end())
        if self.props.get("label"):
            painter.setPen(C_FG)
            painter.setFont(label_font())
            painter.drawText(self.label_rect(), Qt.AlignLeft | Qt.AlignVCenter, self.props["label"])
        if self.isSelected():
            painter.setPen(QPen(C_SELECT, 1.5))
            painter.setBrush(C_BG)
            h = self.HANDLE
            for p in (QPointF(0, 0), self.end()):
                painter.drawRect(QRectF(p.x() - h / 2, p.y() - h / 2, h, h))

    # Endpoint handles: drag an end of a selected line to reshape it.
    def _hit_end(self, pos: QPointF):
        for which, p in (("p2", self.end()), ("p1", QPointF(0, 0))):
            if (pos - p).manhattanLength() <= self.HANDLE + 4:
                return which
        return None

    def mousePressEvent(self, event):
        if self.scene() and self.scene().edit_mode and self.isSelected():
            self._drag = self._hit_end(event.pos())
            if self._drag:
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not self._drag:
            return super().mouseMoveEvent(event)
        target = snap(event.scenePos())
        self.prepareGeometryChange()
        if self._drag == "p2":
            d = target - self.pos()
        else:
            far = self.pos() + self.end()
            self.setPos(target)
            d = far - target
        self.props["dx"], self.props["dy"] = d.x(), d.y()
        self.update()
        self.scene().changed_by_user()

    def mouseReleaseEvent(self, event):
        self._drag = None
        super().mouseReleaseEvent(event)

    def hoverMoveEvent(self, event):
        editing = self.scene() and self.scene().edit_mode and self.isSelected()
        self.setCursor(Qt.SizeAllCursor if editing and self._hit_end(event.pos()) else Qt.ArrowCursor)


class BusbarElement(LineElement):
    KIND = "busbar"
    TITLE = "Busbar"
    DEFAULTS = {"color": VOLTAGE_COLORS["132 kV"], "width": 7, "dx": 240, "dy": 0}


class BreakerElement(Element):
    """Circuit breaker: a box filled red (closed) or green (open)."""
    KIND = "breaker"
    TITLE = "Circuit breaker"
    BINDINGS = {"status": BI, "control": BO}
    ROTATABLE = True

    def operable(self):
        return bool(self.props.get("control"))

    def label_lines(self):
        p = self.point("status")
        text = "" if self.scene() is None else ("NO POINT" if p is None else p.state_text("OpenClose"))
        return [self.props.get("label", ""), text]

    def paint_symbol(self, painter):
        state = self.binary_state("status")
        painter.setPen(QPen(C_FG, 2))
        painter.drawLine(QPointF(0, -30), QPointF(0, -14))
        painter.drawLine(QPointF(0, 14), QPointF(0, 30))
        color = _state_color(state)
        painter.setPen(QPen(color.lighter(130), 2))
        painter.setBrush(color if state is not None else Qt.NoBrush)
        painter.drawRect(QRectF(-14, -14, 28, 28))
        if state is None:
            painter.setPen(C_UNKNOWN)
            painter.setFont(label_font(11, True))
            painter.drawText(QRectF(-14, -14, 28, 28), Qt.AlignCenter, "?")


class SwitchElement(Element):
    """Disconnector / isolator: blade in line when closed, angled when open."""
    KIND = "switch"
    TITLE = "Disconnector"
    BINDINGS = {"status": BI, "control": BO}
    ROTATABLE = True

    def operable(self):
        return bool(self.props.get("control"))

    def label_lines(self):
        p = self.point("status")
        text = "" if self.scene() is None else ("NO POINT" if p is None else p.state_text("OpenClose"))
        return [self.props.get("label", ""), text]

    def paint_symbol(self, painter):
        state = self.binary_state("status")
        color = _state_color(state)
        painter.setPen(QPen(C_FG, 2))
        painter.drawLine(QPointF(0, -30), QPointF(0, -14))
        painter.drawLine(QPointF(0, 14), QPointF(0, 30))
        painter.drawLine(QPointF(-7, -14), QPointF(7, -14))  # fixed contact
        painter.setPen(QPen(color, 3, Qt.SolidLine, Qt.RoundCap))
        if state is False:
            painter.drawLine(QPointF(0, 14), QPointF(-16, -10))
        else:
            painter.drawLine(QPointF(0, 14), QPointF(0, -14))
        painter.setBrush(C_FG)
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(QPointF(0, 14), 3, 3)


class TransformerElement(Element):
    """Two-winding transformer: two overlapping circles, HV on top."""
    KIND = "transformer"
    TITLE = "Transformer"
    DEFAULTS = {"hv_color": VOLTAGE_COLORS["132 kV"], "lv_color": VOLTAGE_COLORS["33 kV"]}
    ROTATABLE = True

    def symbol_rect(self):
        return QRectF(-22, -40, 44, 80)

    def paint_symbol(self, painter):
        hv, lv = QColor(self.props["hv_color"]), QColor(self.props["lv_color"])
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(hv, 2.5))
        painter.drawLine(QPointF(0, -40), QPointF(0, -30))
        painter.drawEllipse(QPointF(0, -11), 19, 19)
        painter.setPen(QPen(lv, 2.5))
        painter.drawEllipse(QPointF(0, 11), 19, 19)
        painter.drawLine(QPointF(0, 30), QPointF(0, 40))


class StatusElement(Element):
    """On/off status lamp for any binary input."""
    KIND = "status"
    TITLE = "Status (BI)"
    BINDINGS = {"status": BI}
    DEFAULTS = {"on_color": "#E0413A", "off_color": "#3A444E"}

    def symbol_rect(self):
        return QRectF(-10, -10, 20, 20)

    def label_rect(self):
        return QRectF(16, -17, 170, 34)

    def label_lines(self):
        p = self.point("status")
        if self.scene() is None:
            return [self.props.get("label", "")]
        return [self.props.get("label", ""), "NO POINT" if p is None else ("ON" if p.state else "OFF")]

    def paint_symbol(self, painter):
        state = self.binary_state("status")
        if state is None:
            color = C_UNKNOWN
        else:
            color = QColor(self.props["on_color"] if state else self.props["off_color"])
        painter.setPen(QPen(color.lighter(140), 1.5))
        painter.setBrush(color)
        painter.drawEllipse(QPointF(0, 0), 9, 9)


class _PanelElement(Element):
    """Base for rectangular readouts and buttons."""
    WIDTH, HEIGHT = 150, 44

    def symbol_rect(self):
        return QRectF(0, 0, self.WIDTH, self.HEIGHT)

    def label_rect(self):
        return QRectF()

    def boundingRect(self):
        return self.symbol_rect().adjusted(-6, -6, 6, 6)

    def paint_label(self, painter):
        pass

    def draw_panel(self, painter, title, value, value_color, border=C_DIM, raised=False):
        r = self.symbol_rect()
        painter.setPen(QPen(border, 1.5 if raised else 1))
        painter.setBrush(QColor("#2A333C") if raised else C_PANEL)
        painter.drawRoundedRect(r, 4 if raised else 2, 4 if raised else 2)
        painter.setPen(C_DIM)
        painter.setFont(label_font(8))
        painter.drawText(r.adjusted(8, 4, -8, 0), Qt.AlignLeft | Qt.AlignTop, title)
        painter.setPen(value_color)
        painter.setFont(label_font(12, True))
        painter.drawText(r.adjusted(8, 0, -8, -4), Qt.AlignRight | Qt.AlignBottom, value)


class AnalogElement(_PanelElement):
    """Analog input readout with units."""
    KIND = "analog"
    TITLE = "Analog value (AI)"
    BINDINGS = {"value": AI}

    def paint_symbol(self, painter):
        p = self.point("value")
        if self.scene() is None:
            value, color = "132.0 kV", C_FG
        elif p is None:
            value, color = "NO POINT", C_UNKNOWN
        else:
            value, color = p.display_value(), C_FG
        self.draw_panel(painter, self.props.get("label") or (p.name if p else "Analog"), value, color)


class ControlElement(_PanelElement):
    """Generic binary control button (trip/close, open/close, on/off)."""
    KIND = "control"
    TITLE = "Control (BO)"
    BINDINGS = {"control": BO, "status": BI}

    def operable(self):
        return bool(self.props.get("control"))

    def paint_symbol(self, painter):
        ctrl = self.point("control")
        status = self.point("status") or ctrl
        if self.scene() is None:
            value, color = "ON", C_CLOSED
        elif status is None:
            value, color = "NO POINT", C_UNKNOWN
        else:
            value, color = self.scene().points.state_text(status), _state_color(status.state)
        self.draw_panel(painter, (self.props.get("label") or "Control") + "  ▸", value, color,
                        border=C_SELECT, raised=True)


class SetpointElement(_PanelElement):
    """Analog output setpoint: shows the current AO value, click to send a new one."""
    KIND = "setpoint"
    TITLE = "Setpoint (AO)"
    BINDINGS = {"control": AO}

    def operable(self):
        return bool(self.props.get("control"))

    def paint_symbol(self, painter):
        p = self.point("control")
        if self.scene() is None:
            value, color = "SP 9", C_SELECT
        elif p is None:
            value, color = "NO POINT", C_UNKNOWN
        else:
            value, color = "SP " + p.display_value(), C_SELECT
        self.draw_panel(painter, (self.props.get("label") or "Setpoint") + "  ▸", value, color,
                        border=C_SELECT, raised=True)


class TextElement(Element):
    KIND = "text"
    TITLE = "Text"
    DEFAULTS = {"label": "Text", "size": 11}

    def _rect(self):
        return QRectF(0, 0, max(40, len(self.props.get("label", "")) * self.props["size"] * 0.9),
                      self.props["size"] * 2.2)

    def boundingRect(self):
        return self._rect().adjusted(-4, -4, 4, 4)

    def shape(self):
        path = QPainterPath()
        path.addRect(self._rect())
        return path

    def paint(self, painter, option, widget=None):
        painter.setPen(C_FG)
        painter.setFont(label_font(self.props["size"], True))
        painter.drawText(self._rect(), Qt.AlignLeft | Qt.AlignVCenter, self.props.get("label", ""))
        if self.isSelected():
            painter.setPen(QPen(C_SELECT, 1, Qt.DashLine))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(self._rect())


ELEMENT_CLASSES: dict[str, type[Element]] = {
    cls.KIND: cls for cls in (
        BusbarElement, LineElement, BreakerElement, SwitchElement, TransformerElement,
        StatusElement, AnalogElement, ControlElement, SetpointElement, TextElement,
    )
}


def create_element(data: dict) -> Element:
    cls = ELEMENT_CLASSES[data["kind"]]
    el = cls(data.get("props"))
    el.setPos(data.get("x", 0), data.get("y", 0))
    return el


def render_icon(kind: str, size: int = 44):
    """Draw an element into a pixmap for the palette."""
    from PySide6.QtGui import QPixmap
    el = ELEMENT_CLASSES[kind]({"label": ""})
    if isinstance(el, _PanelElement):
        return _panel_icon(el, size)
    if isinstance(el, LineElement):
        el.props.update({"dx": 50, "dy": 0} if kind == "busbar" else {"dx": 36, "dy": 36})
    pm = QPixmap(size, size)
    pm.fill(C_BG)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing)
    br = el.boundingRect() if not isinstance(el, LineElement) else QRectF(QPointF(0, 0), el.end()).normalized().adjusted(-4, -4, 4, 4)
    if isinstance(el, (StatusElement, BreakerElement, SwitchElement, TransformerElement)):
        br = el.oriented(el.symbol_rect()).adjusted(-3, -3, 3, 3)
    scale = min((size - 6) / max(br.width(), 1), (size - 6) / max(br.height(), 1))
    painter.translate(size / 2, size / 2)
    painter.scale(scale, scale)
    painter.translate(-br.center())
    if isinstance(el, (StatusElement, BreakerElement, SwitchElement, TransformerElement)):
        el.paint_symbol(painter)
    else:
        el.paint(painter, QStyleOptionGraphicsItem(), None)
    painter.end()
    return pm


def _panel_icon(el: "_PanelElement", size: int):
    from PySide6.QtGui import QPixmap
    pm = QPixmap(size, size)
    pm.fill(C_BG)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing)
    r = QRectF(3, size * 0.25, size - 6, size * 0.5)
    raised = not isinstance(el, AnalogElement)
    painter.setPen(QPen(C_SELECT if raised else C_DIM, 1.5))
    painter.setBrush(QColor("#2A333C") if raised else C_PANEL)
    painter.drawRoundedRect(r, 3, 3)
    text, color = {"analog": ("kV", C_FG), "control": ("ON", C_CLOSED), "setpoint": ("SP", C_SELECT)}[el.KIND]
    painter.setPen(color)
    painter.setFont(label_font(8, True))
    painter.drawText(r, Qt.AlignCenter, text)
    painter.end()
    return pm
