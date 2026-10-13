"""Ties the points list, the DNP3 outstation and the GUI together.

All point changes go through here, whether they come from the HMI operator,
the points table or the DNP3 master, so the diagram, the table and the
outstation database stay in step.
"""
from __future__ import annotations

import random
from datetime import datetime

from PySide6.QtCore import QObject, QTimer, Signal

from .outstation import Outstation, OutstationConfig
from .points import AI, AO, BI, BO, CONTROL_MODELS, Point, PointList, coerce_point

LAYOUT_FIELDS = {"name", "type", "index", "event_class"}


class _Bridge(QObject):
    """Carries outstation callbacks from the DNP3 thread to the GUI thread."""
    binary = Signal(str, bool)
    analog = Signal(str, float)
    state = Signal(str)
    log = Signal(str)


class HmiController(QObject):
    pointChanged = Signal(str)      # a value changed
    pointsReset = Signal()          # list structure changed (add/remove/import/edit)
    pointRenamed = Signal(str, str)
    log = Signal(str)
    linkState = Signal(str)         # Stopped / Listening / Master connected

    def __init__(self, points: PointList | None = None, config: OutstationConfig | None = None):
        super().__init__()
        self.points = points or PointList()
        self.config = config or OutstationConfig()
        self.outstation: Outstation | None = None
        self._restart_needed = False

        self._bridge = _Bridge()
        self._bridge.binary.connect(lambda n, s: self.operate_binary(n, s, source="Master"))
        self._bridge.analog.connect(lambda n, v: self.operate_analog(n, v, source="Master"))
        self._bridge.state.connect(self._on_channel_state)
        self._bridge.log.connect(self.emit_log)

        self._sim = QTimer(self)
        self._sim.setInterval(2000)
        self._sim.timeout.connect(self._simulate_step)

    # --- logging ------------------------------------------------------------
    def emit_log(self, msg: str):
        self.log.emit(f"{datetime.now():%H:%M:%S}  {msg}")

    # --- values -----------------------------------------------------------------
    def set_value(self, name: str, value: float, push: bool = True):
        p = self.points.get(name)
        if p is None:
            return
        p.value = float(value)
        if push and self.outstation and self.outstation.running:
            self.outstation.update(p)
        self.pointChanged.emit(name)

    def operate_binary(self, name: str, state: bool, source: str = "HMI") -> str | None:
        """Operate a BO and drive its feedback BI. Returns an error or None."""
        p = self.points.get(name)
        if p is None or p.type != BO:
            return f"'{name}' is not a binary output point"
        self.set_value(name, 1.0 if state else 0.0)
        if p.feedback:
            self.set_value(p.feedback, 1.0 if state else 0.0)
        verb = p.captions()[int(state)].upper()
        fb = self.points.get(p.feedback) if p.feedback else None
        self.emit_log(f"{source}: {verb} {name}" + (f" -> {fb.name} = {self.points.state_text(fb)}" if fb else ""))
        return None

    def operate_analog(self, name: str, value: float, source: str = "HMI") -> str | None:
        p = self.points.get(name)
        if p is None or p.type != AO:
            return f"'{name}' is not an analog output point"
        if (p.min is not None and value < p.min) or (p.max is not None and value > p.max):
            lo = "no minimum" if p.min is None else f"{p.min:g}"
            hi = "no maximum" if p.max is None else f"{p.max:g}"
            return f"{value:g} is outside the allowed range ({lo} to {hi})"
        self.set_value(name, value)
        if p.feedback:
            self.set_value(p.feedback, value)
        self.emit_log(f"{source}: set {name} = {value:g} {p.units}".rstrip())
        return None

    # --- points list editing ---------------------------------------------------
    def add_point(self, ptype: str) -> Point:
        prefix = {BI: "STATUS", BO: "CONTROL", AI: "ANALOG", AO: "SETPOINT"}[ptype]
        p = Point(self.points.unique_name(prefix), ptype, self.points.next_index(ptype),
                  control_model="OpenClose" if ptype == BO else "")
        self.points.points.append(p)
        self._structure_changed()
        return p

    def remove_points(self, names: list[str]):
        self.points.points = [p for p in self.points if p.name not in names]
        for p in self.points:
            if p.feedback in names:
                p.feedback = ""
        self._structure_changed()

    def edit_point(self, row: int, field: str, raw) -> str | None:
        """Apply a points-table edit. Returns an error message or None."""
        p = self.points.points[row]
        if field == "value":
            try:
                value = float(raw)
            except (TypeError, ValueError):
                return "Value must be a number"
            if p.type == AO and ((p.min is not None and value < p.min) or (p.max is not None and value > p.max)):
                return f"{value:g} is outside {p.name}'s range"
            self.set_value(p.name, value)
            self.emit_log(f"Table: {p.name} = {p.display_value()}")
            return None

        candidate = p.to_dict()
        candidate[field] = raw
        try:
            new = coerce_point(candidate)
        except (ValueError, TypeError) as e:
            return str(e)
        old_name = p.name
        trial = PointList([new if q is p else q for q in self.points])
        errors = [e for e in trial.validate() if "Duplicate" in e]
        if errors:
            return errors[0]
        if field == "type" and new.type != p.type:
            new.index = self.points.next_index(new.type)
            new.feedback = ""
            new.control_model = "OpenClose" if new.type == BO else ""
        for k, v in new.to_dict().items():
            setattr(p, k, v)
        if field == "name" and old_name != p.name:
            for q in self.points:
                if q.feedback == old_name:
                    q.feedback = p.name
            self.pointRenamed.emit(old_name, p.name)
        if field in LAYOUT_FIELDS:
            self._structure_changed()
        else:
            self.pointsReset.emit()
        return None

    def replace_points(self, new: PointList):
        # Mutate in place: the scene and outstation hold a reference to self.points.
        self.points.points = new.points
        self._structure_changed()

    def create_points_for(self, kind: str, label: str) -> dict[str, str]:
        """Create a sensible set of points for a diagram element. Returns role -> name."""
        base = "".join(c if c.isalnum() else "_" for c in (label or kind).upper()).strip("_") or kind.upper()
        created = {}

        def make(role, ptype, suffix, **kw):
            p = Point(self.points.unique_name(f"{base}_{suffix}"), ptype, self.points.next_index(ptype),
                      description=f"{label or kind} {suffix.lower()}", **kw)
            self.points.points.append(p)
            created[role] = p.name
            return p

        if kind in ("breaker", "switch", "control"):
            st = make("status", BI, "POS" if kind != "control" else "STATUS", value=1.0)
            make("control", BO, "CTRL", control_model={"breaker": "TripClose", "switch": "OpenClose"}.get(kind, "OnOff"),
                 feedback=st.name, value=1.0)
        elif kind in ("line", "busbar", "status"):
            make("status", BI, "STATUS", value=1.0)
        elif kind == "analog":
            make("value", AI, "VALUE")
        elif kind == "setpoint":
            fb = make("_fb", AI, "FB")
            make("control", AO, "SP", feedback=fb.name, min=0.0, max=100.0)
            created.pop("_fb")
        self._structure_changed()
        return created

    def _structure_changed(self):
        if self.outstation and self.outstation.running and not self._restart_needed:
            self._restart_needed = True
            self.emit_log("Points list changed. Restart the outstation to apply the new DNP3 database layout.")
        self.pointsReset.emit()

    # --- outstation -----------------------------------------------------------------
    @property
    def running(self) -> bool:
        return bool(self.outstation and self.outstation.running)

    def start(self) -> str | None:
        if self.running:
            return None
        problems = self.points.validate()
        if problems:
            return "Fix the points list first:\n" + "\n".join(problems)
        if self.outstation is None:
            self.outstation = Outstation(self.config, self.points)
            self.outstation.on_binary_command = self._bridge.binary.emit
            self.outstation.on_analog_command = self._bridge.analog.emit
            self.outstation.on_state = self._bridge.state.emit
            self.outstation.on_log = self._bridge.log.emit
        self.outstation.config = self.config
        try:
            self.outstation.start()
        except Exception as e:
            return f"Could not start the outstation: {e}"
        self._restart_needed = False
        self.linkState.emit("Listening")
        return None

    def stop(self):
        if self.running:
            self.outstation.stop()
        self.linkState.emit("Stopped")

    def _on_channel_state(self, state: str):
        if not self.running:
            return
        if state == "OPEN":
            self.emit_log("Master connected")
            self.linkState.emit("Master connected")
        elif state in ("OPENING", "CLOSED"):
            self.linkState.emit("Listening")

    # --- analog simulation ----------------------------------------------------------
    def set_simulation(self, on: bool):
        self._sim.start() if on else self._sim.stop()

    def _simulate_step(self):
        fed = {p.feedback for p in self.points if p.feedback}
        for p in self.points:
            if p.type == AI and p.name not in fed and p.value:
                self.set_value(p.name, round(p.value * (1 + random.uniform(-0.004, 0.004)), 3))


__all__ = ["HmiController", "CONTROL_MODELS"]
