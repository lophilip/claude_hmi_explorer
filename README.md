# Substation HMI
This was a test of claude, to see what it could do. It's not perfect, and it does
crash, but perhaps it's a good starting place for a project.

A small Python/Qt HMI for drawing and operating substation single line diagrams,
backed by a real DNP3 outstation (OpenDNP3 via `dnp3-python`) whose database is
built from a configurable points list.

## Run

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python run_hmi.py                      # opens the sample substation
.venv/bin/python run_hmi.py examples/sample_substation.json
```

`dnp3-python` ships Linux x86_64 wheels for Python 3.8–3.10.

## Using it

**Edit mode**
- Drag elements from the palette onto the diagram. Elements snap to a 10 px grid.
- Drag elements to move them. To reshape a selected line or busbar, drag the square handles at its ends.
- The Properties panel sets an element's label, colours (with voltage-level presets) and the points it is bound to.
- **Create points for this element** adds suitable points to the points list and binds them.
- `R` rotates breakers, disconnectors and transformers. `Del` deletes. Ctrl+wheel zooms.

**Operate mode**
- Click a breaker, disconnector or control button to open a select-before-operate dialog: choose Trip/Close, Open/Close or Off/On, then press Execute within 10 s.
- Click a setpoint to send an analog output value. Values outside the point's Min/Max are rejected.

**Outstation**
- Set the port and the link addresses, then press **Start outstation**.
- A master's commands drive the same points as the HMI controls.
- Changing the points list structure while the outstation is running needs a restart to take effect.

| Element | Binds to | Shows |
|---|---|---|
| Line / Busbar | optional BI | dashed and dimmed when the BI is 0 (de-energised) |
| Circuit breaker | BI status, BO control | box: red = closed, green = open, magenta = no point |
| Disconnector | BI status, BO control | blade closed / open |
| Transformer | none | two-winding symbol with HV/LV colours |
| Status (BI) | BI | on/off lamp |
| Analog value (AI) | AI | value and units |
| Control (BO) | BO, optional BI status | button for trip/close, open/close or on/off |
| Setpoint (AO) | AO | current value; click to send a new one |

## Points list

Import and export use `.xlsx` (with drop-downs) or `.csv`. See `examples/sample_points.xlsx`.

| Column | Meaning |
|---|---|
| Name | unique point name used by diagram elements |
| Type | `BI`, `BO`, `AI`, `AO` |
| Index | DNP3 point index (unique per type) |
| Class | event class 0–3 |
| Control Model | BO only: `TripClose`, `OpenClose`, `OnOff` |
| Feedback Point | BO → BI or AO → AI updated when the control operates (simulated plant feedback) |
| Value | initial / current value |
| Min, Max | AO limits |

DNP3 mapping:
- BI: g1v2 static, g2v2 events.
- BO: g10v2 status, g11v2 events. Accepts CROB codes LATCH_ON/OFF, PULSE_ON/OFF, CLOSE_PULSE_ON and TRIP_PULSE_ON.
- AI: g30v5 (float), g32v7 events.
- AO: g40v3 status, g42v7 events. Accepts g41 commands of any variation.

## Layout

```
run_hmi.py                  entry point
substation_hmi/points.py    points list model, validation, xlsx/csv import/export (no Qt)
substation_hmi/outstation.py DNP3 outstation on pydnp3 (no Qt)
substation_hmi/controller.py routes HMI, table and master changes; outstation lifecycle
substation_hmi/elements.py  SLD symbols
substation_hmi/scene.py     canvas, drag-and-drop, palette
substation_hmi/widgets.py   points table, properties panel, control dialogs
substation_hmi/main_window.py
```

Note: don't run an OpenDNP3 master and this outstation in the same Python
process. pydnp3 segfaults in that setup. Test with a master in a separate process
or on another machine.
