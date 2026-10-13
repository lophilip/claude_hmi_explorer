"""Diagram canvas: drag-and-drop target, edit/operate modes, persistence."""
from __future__ import annotations

from PySide6.QtCore import QMimeData, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QIcon, QPainter, QPen
from PySide6.QtWidgets import QGraphicsItem, QGraphicsScene, QGraphicsView, QListWidget, QListWidgetItem, QAbstractItemView

from .elements import C_BG, C_GRID, ELEMENT_CLASSES, GRID, Element, create_element, render_icon, snap
from .points import PointList

MIME = "application/x-sld-element"
PALETTE_ORDER = ["busbar", "line", "breaker", "switch", "transformer",
                 "status", "analog", "control", "setpoint", "text"]


class DiagramScene(QGraphicsScene):
    operateRequested = Signal(object)   # Element clicked in operate mode
    elementDropped = Signal(object)     # new Element dropped from the palette
    modified = Signal()

    def __init__(self, points: PointList, parent=None):
        super().__init__(parent)
        self.points = points
        self.edit_mode = True
        self.setSceneRect(QRectF(0, 0, 1600, 1000))
        self._loading = False

    def changed_by_user(self):
        if not self._loading:
            self.modified.emit()

    def set_edit_mode(self, on: bool):
        self.edit_mode = on
        if not on:
            self.clearSelection()
        for it in self.elements():
            it.setFlag(QGraphicsItem.ItemIsMovable, on)
            it.setFlag(QGraphicsItem.ItemIsSelectable, on)
            it.setCursor(Qt.ArrowCursor if on or not it.operable() else Qt.PointingHandCursor)
        self.update()

    def elements(self) -> list[Element]:
        return [it for it in self.items() if isinstance(it, Element)]

    def add_element(self, el: Element):
        self.addItem(el)
        el.setFlag(QGraphicsItem.ItemIsMovable, self.edit_mode)
        el.setFlag(QGraphicsItem.ItemIsSelectable, self.edit_mode)
        if not self.edit_mode and el.operable():
            el.setCursor(Qt.PointingHandCursor)

    def rename_point(self, old: str, new: str):
        for el in self.elements():
            for role in el.BINDINGS:
                if el.props.get(role) == old:
                    el.props[role] = new
        self.update()

    # --- persistence -------------------------------------------------------
    def to_list(self) -> list[dict]:
        els = sorted(self.elements(), key=lambda e: e.zValue())
        return [e.to_dict() for e in els]

    def load_list(self, data: list[dict]):
        self._loading = True
        self.clear()
        for i, d in enumerate(data):
            el = create_element(d)
            el.setZValue(i)
            self.add_element(el)
        self._loading = False
        self._grow_to_fit()

    def _grow_to_fit(self):
        r = self.itemsBoundingRect().adjusted(-40, -40, 400, 400)
        self.setSceneRect(self.sceneRect().united(r).united(QRectF(0, 0, 1600, 1000)))

    # --- background grid -----------------------------------------------------
    def drawBackground(self, painter: QPainter, rect: QRectF):
        painter.fillRect(rect, C_BG)
        if not self.edit_mode:
            return
        painter.setPen(QPen(C_GRID, 1.2))
        step = GRID * 2
        left, top = int(rect.left()) - int(rect.left()) % step, int(rect.top()) - int(rect.top()) % step
        pts = [QPointF(x, y) for x in range(left, int(rect.right()) + 1, step)
               for y in range(top, int(rect.bottom()) + 1, step)]
        painter.drawPoints(pts)

    # --- drag & drop from the palette ---------------------------------------
    def dragEnterEvent(self, event):
        if self.edit_mode and event.mimeData().hasFormat(MIME):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if self.edit_mode and event.mimeData().hasFormat(MIME):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        if not (self.edit_mode and event.mimeData().hasFormat(MIME)):
            return event.ignore()
        kind = bytes(event.mimeData().data(MIME)).decode()
        el = ELEMENT_CLASSES[kind]()
        el.setPos(snap(event.scenePos()))
        el.setZValue(max([e.zValue() for e in self.elements()], default=0) + 1)
        self.add_element(el)
        self.clearSelection()
        el.setSelected(True)
        event.acceptProposedAction()
        self._grow_to_fit()
        self.elementDropped.emit(el)
        self.modified.emit()

    # --- operate mode clicks ------------------------------------------------------
    def mousePressEvent(self, event):
        if self.edit_mode:
            return super().mousePressEvent(event)
        for it in self.items(event.scenePos()):
            if isinstance(it, Element) and it.operable():
                self.operateRequested.emit(it)
                break
        event.accept()


class DiagramView(QGraphicsView):
    def __init__(self, scene: DiagramScene):
        super().__init__(scene)
        self.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        self.setAcceptDrops(True)
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)

    def wheelEvent(self, event):
        if event.modifiers() & Qt.ControlModifier:
            f = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
            self.scale(f, f)
        else:
            super().wheelEvent(event)


class Palette(QListWidget):
    """Element palette: drag an entry onto the diagram to place it."""

    def __init__(self):
        super().__init__()
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragOnly)
        self.setIconSize(render_icon("breaker").size())
        self.setSpacing(2)
        for kind in PALETTE_ORDER:
            cls = ELEMENT_CLASSES[kind]
            item = QListWidgetItem(QIcon(render_icon(kind)), cls.TITLE)
            item.setData(Qt.UserRole, kind)
            item.setToolTip(f"Drag onto the diagram to add a {cls.TITLE.lower()}")
            self.addItem(item)

    def mimeTypes(self):
        return [MIME]

    def mimeData(self, items):
        md = QMimeData()
        md.setData(MIME, items[0].data(Qt.UserRole).encode())
        return md
