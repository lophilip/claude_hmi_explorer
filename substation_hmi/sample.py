"""A small 132/33 kV substation used as the default project."""
from __future__ import annotations

from .elements import VOLTAGE_COLORS
from .points import Point, PointList

HV, LV = VOLTAGE_COLORS["132 kV"], VOLTAGE_COLORS["33 kV"]


def sample_points() -> PointList:
    P = Point
    return PointList([
        P("DS1_POS", "BI", 0, "Line 1 disconnector position", value=1),
        P("CB1_POS", "BI", 1, "Line 1 breaker position", value=1),
        P("CB2_POS", "BI", 2, "T1 HV breaker position", value=1),
        P("CB3_POS", "BI", 3, "T1 LV breaker position", value=1),
        P("CB4_POS", "BI", 4, "Feeder 1 breaker position", value=1),
        P("CB5_POS", "BI", 5, "Feeder 2 breaker position", value=0),
        P("L1_LIVE", "BI", 6, "Line 1 voltage present", value=1),
        P("PROT_HEALTHY", "BI", 7, "Protection relay healthy", value=1),
        P("BATT_ALARM", "BI", 8, "Battery charger alarm", value=0),
        P("AR_STATUS", "BI", 9, "Feeder auto-reclose in service", value=1),
        P("DS1_CTRL", "BO", 0, "Line 1 disconnector control", control_model="OpenClose", feedback="DS1_POS", value=1),
        P("CB1_CTRL", "BO", 1, "Line 1 breaker control", control_model="TripClose", feedback="CB1_POS", value=1),
        P("CB2_CTRL", "BO", 2, "T1 HV breaker control", control_model="TripClose", feedback="CB2_POS", value=1),
        P("CB3_CTRL", "BO", 3, "T1 LV breaker control", control_model="TripClose", feedback="CB3_POS", value=1),
        P("CB4_CTRL", "BO", 4, "Feeder 1 breaker control", control_model="TripClose", feedback="CB4_POS", value=1),
        P("CB5_CTRL", "BO", 5, "Feeder 2 breaker control", control_model="TripClose", feedback="CB5_POS", value=0),
        P("AR_CTRL", "BO", 6, "Feeder auto-reclose on/off", control_model="OnOff", feedback="AR_STATUS", value=1),
        P("L1_MW", "AI", 0, "Line 1 active power", "MW", 2, value=48.6),
        P("L1_KV", "AI", 1, "Line 1 voltage", "kV", 2, value=132.4),
        P("T1_MW", "AI", 2, "T1 active power", "MW", 2, value=31.2),
        P("T1_OIL_TEMP", "AI", 3, "T1 top oil temperature", "°C", 2, value=61.5),
        P("T1_TAP_POS", "AI", 4, "T1 tap position", "", 2, value=9),
        P("BUS33_KV", "AI", 5, "33 kV bus voltage", "kV", 2, value=33.1),
        P("F1_AMPS", "AI", 6, "Feeder 1 current", "A", 2, value=312),
        P("F2_AMPS", "AI", 7, "Feeder 2 current", "A", 2, value=0),
        P("T1_TAP_SP", "AO", 0, "T1 tap position setpoint", "", 1, feedback="T1_TAP_POS", value=9, min=1, max=17),
        P("AVR_SETPOINT", "AO", 1, "33 kV voltage regulator setpoint", "kV", 1, value=33, min=31, max=35),
    ])


def _line(x, y, dx, dy, color=HV, status="", width=3, label="", kind="line"):
    return {"kind": kind, "x": x, "y": y,
            "props": {"label": label, "status": status, "color": color, "width": width, "dx": dx, "dy": dy}}


def _el(kind, x, y, **props):
    return {"kind": kind, "x": x, "y": y, "props": props}


def sample_elements() -> list[dict]:
    return [
        _el("text", 40, 10, label="RIVERSIDE 132/33 kV SUBSTATION", size=14),
        # Line 1 incomer
        _line(200, 60, 0, 60, status="L1_LIVE", label="Line 1"),
        _el("switch", 200, 150, label="DS1", status="DS1_POS", control="DS1_CTRL"),
        _line(200, 180, 0, 40, status="L1_LIVE"),
        _el("breaker", 200, 250, label="CB1", status="CB1_POS", control="CB1_CTRL"),
        _line(200, 280, 0, 40, status="CB1_POS"),
        _line(120, 320, 480, 0, width=7, kind="busbar"),
        _el("text", 610, 310, label="132 kV BUS", size=10),
        # Transformer bay
        _line(440, 320, 0, 30),
        _el("breaker", 440, 380, label="CB2", status="CB2_POS", control="CB2_CTRL"),
        _line(440, 410, 0, 30, status="CB2_POS"),
        _el("transformer", 440, 480, label="T1 132/33 kV", hv_color=HV, lv_color=LV),
        _line(440, 520, 0, 30, color=LV, status="CB2_POS"),
        _el("breaker", 440, 580, label="CB3", status="CB3_POS", control="CB3_CTRL"),
        _line(440, 610, 0, 40, color=LV, status="CB3_POS"),
        _line(300, 650, 440, 0, color=LV, width=7, kind="busbar"),
        _el("text", 750, 640, label="33 kV BUS", size=10),
        # Feeders
        _line(360, 650, 0, 40, color=LV),
        _el("breaker", 360, 720, label="CB4", status="CB4_POS", control="CB4_CTRL"),
        _line(360, 750, 0, 70, color=LV, status="CB4_POS", label="Feeder 1"),
        _line(600, 650, 0, 40, color=LV),
        _el("breaker", 600, 720, label="CB5", status="CB5_POS", control="CB5_CTRL"),
        _line(600, 750, 0, 70, color=LV, status="CB5_POS", label="Feeder 2"),
        # Measurements
        _el("analog", 30, 120, label="Line 1 power", value="L1_MW"),
        _el("analog", 30, 170, label="Line 1 voltage", value="L1_KV"),
        _el("analog", 650, 420, label="T1 power", value="T1_MW"),
        _el("analog", 650, 470, label="T1 oil temp", value="T1_OIL_TEMP"),
        _el("analog", 650, 520, label="T1 tap position", value="T1_TAP_POS"),
        _el("setpoint", 650, 570, label="T1 tap setpoint", control="T1_TAP_SP"),
        _el("analog", 750, 675, label="33 kV bus", value="BUS33_KV"),
        _el("analog", 190, 780, label="Feeder 1 current", value="F1_AMPS"),
        _el("analog", 430, 780, label="Feeder 2 current", value="F2_AMPS"),
        # Station panel
        _el("text", 40, 380, label="STATION", size=10),
        _el("status", 50, 425, label="Protection healthy", status="PROT_HEALTHY", on_color="#2FB463", off_color="#3A444E"),
        _el("status", 50, 465, label="Battery charger alarm", status="BATT_ALARM", on_color="#E8A33D", off_color="#3A444E"),
        _el("control", 40, 500, label="Feeder auto-reclose", control="AR_CTRL", status="AR_STATUS"),
        _el("setpoint", 40, 555, label="AVR setpoint", control="AVR_SETPOINT"),
    ]


def sample_project() -> dict:
    return {
        "version": 1,
        "dnp3": {"port": 20000, "local_addr": 1, "remote_addr": 2},
        "points": sample_points().to_list(),
        "elements": sample_elements(),
    }
