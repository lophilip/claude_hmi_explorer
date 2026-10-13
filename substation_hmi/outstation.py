"""DNP3 TCP outstation (slave) built on OpenDNP3 via pydnp3.

The database layout is taken from a PointList at start-up. Commands from the
master are validated against that layout on the DNP3 thread, then handed to
`on_binary_command` / `on_analog_command` callbacks, which are also called from
the DNP3 thread: GUI code must marshal them to its own thread.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

from pydnp3 import asiodnp3, asiopal, opendnp3, openpal

from .points import AI, AO, BI, BO, PointList

log = logging.getLogger(__name__)

# CROB codes accepted per control model, mapped to the resulting state.
_ON_CODES = {opendnp3.ControlCode.LATCH_ON, opendnp3.ControlCode.CLOSE_PULSE_ON, opendnp3.ControlCode.PULSE_ON}
_OFF_CODES = {opendnp3.ControlCode.LATCH_OFF, opendnp3.ControlCode.TRIP_PULSE_ON, opendnp3.ControlCode.PULSE_OFF}
_CLASSES = {0: opendnp3.PointClass.Class0, 1: opendnp3.PointClass.Class1,
            2: opendnp3.PointClass.Class2, 3: opendnp3.PointClass.Class3}


@dataclass
class OutstationConfig:
    port: int = 20000
    local_addr: int = 1    # outstation link address
    remote_addr: int = 2   # master link address
    bind_ip: str = "0.0.0.0"


class _CommandHandler(opendnp3.ICommandHandler):
    # pydnp3 trampolines crash if this subclass defines __init__, so the owner
    # is attached after construction.
    owner: "Outstation" = None

    def Start(self):
        pass

    def End(self):
        pass

    def Select(self, command, index):
        return self.owner._handle(command, index, execute=False)

    def Operate(self, command, index, op_type):
        return self.owner._handle(command, index, execute=True)


class _Application(opendnp3.IOutstationApplication):
    def __init__(self):
        super().__init__()


class _ChannelListener(asiodnp3.IChannelListener):
    def __init__(self, owner: "Outstation"):
        super().__init__()
        self.owner = owner

    def OnStateChange(self, state):
        name = str(state).split(".")[-1]
        if self.owner.on_state:
            self.owner.on_state(name)


class Outstation:
    def __init__(self, config: OutstationConfig, points: PointList):
        self.config = config
        self.points = points
        # Callbacks (called on the DNP3 thread).
        self.on_binary_command: Callable[[str, bool], None] | None = None
        self.on_analog_command: Callable[[str, float], None] | None = None
        self.on_state: Callable[[str], None] | None = None
        self.on_log: Callable[[str], None] | None = None
        self._manager = None
        self._channel = None
        self._outstation = None
        # Index snapshot taken at start: the database layout is fixed while running.
        self._layout: dict[tuple[str, int], object] = {}

    @property
    def running(self) -> bool:
        return self._outstation is not None

    def start(self) -> None:
        if self.running:
            return
        problems = self.points.validate()
        if problems:
            raise ValueError("Points list is invalid:\n" + "\n".join(problems))
        self._layout = {(p.type, p.index): p for p in self.points}
        sizes = self.points.sizes()
        db_sizes = opendnp3.DatabaseSizes(
            numBinary=sizes[BI], numDoubleBinary=0, numAnalog=sizes[AI], numCounter=0,
            numFrozenCounter=0, numBinaryOutputStatus=sizes[BO],
            numAnalogOutputStatus=sizes[AO], numTimeAndInterval=0,
        )
        stack = asiodnp3.OutstationStackConfig(db_sizes)
        stack.outstation.eventBufferConfig = opendnp3.EventBufferConfig().AllTypes(100)
        stack.outstation.params.allowUnsolicited = True
        stack.link.LocalAddr = self.config.local_addr
        stack.link.RemoteAddr = self.config.remote_addr
        stack.link.KeepAliveTimeout = openpal.TimeDuration().Max()
        self._configure_db(stack.dbConfig)

        if self._manager is None:
            self._manager = asiodnp3.DNP3Manager(1, asiodnp3.ConsoleLogger().Create())
        # Keep Python-side handler objects alive for as long as the stack uses them.
        self._listener = _ChannelListener(self)
        self._handler = _CommandHandler()
        self._handler.owner = self
        self._application = _Application()
        self._channel = self._manager.AddTCPServer(
            "hmi-server", opendnp3.levels.NORMAL, asiopal.ChannelRetry().Default(),
            self.config.bind_ip, self.config.port, self._listener,
        )
        self._outstation = self._channel.AddOutstation(
            "hmi-outstation", self._handler, self._application, stack,
        )
        for p in self.points:
            self.update(p, event=False)
        self._outstation.Enable()
        self._log(f"Outstation listening on {self.config.bind_ip}:{self.config.port} "
                  f"(outstation addr {self.config.local_addr}, master addr {self.config.remote_addr}); "
                  f"BI={sizes[BI]} BO={sizes[BO]} AI={sizes[AI]} AO={sizes[AO]}")

    def stop(self) -> None:
        if not self.running:
            return
        self._outstation.Shutdown()
        self._channel.Shutdown()
        self._outstation = None
        self._channel = None
        self._log("Outstation stopped")

    def update(self, point, event: bool = True) -> None:
        """Push a point's current value into the outstation database."""
        if not self.running or (point.type, point.index) not in self._layout:
            return
        meas = {
            BI: lambda v: opendnp3.Binary(bool(v)),
            BO: lambda v: opendnp3.BinaryOutputStatus(bool(v)),
            AI: lambda v: opendnp3.Analog(float(v)),
            AO: lambda v: opendnp3.AnalogOutputStatus(float(v)),
        }[point.type](point.value)
        mode = opendnp3.EventMode.Detect if event else opendnp3.EventMode.Suppress
        self._outstation.Apply(asiodnp3.UpdateBuilder().Update(meas, point.index, mode).Build())

    # --- internals ------------------------------------------------------
    def _configure_db(self, db) -> None:
        for p in self.points:
            cls = _CLASSES.get(p.event_class, opendnp3.PointClass.Class1)
            if p.type == BI:
                cfg = db.binary[p.index]
                cfg.svariation = opendnp3.StaticBinaryVariation.Group1Var2
                cfg.evariation = opendnp3.EventBinaryVariation.Group2Var2
            elif p.type == BO:
                cfg = db.boStatus[p.index]
                cfg.svariation = opendnp3.StaticBinaryOutputStatusVariation.Group10Var2
                cfg.evariation = opendnp3.EventBinaryOutputStatusVariation.Group11Var2
            elif p.type == AI:
                cfg = db.analog[p.index]
                cfg.svariation = opendnp3.StaticAnalogVariation.Group30Var5
                cfg.evariation = opendnp3.EventAnalogVariation.Group32Var7
            else:
                cfg = db.aoStatus[p.index]
                cfg.svariation = opendnp3.StaticAnalogOutputStatusVariation.Group40Var3
                cfg.evariation = opendnp3.EventAnalogOutputStatusVariation.Group42Var7
            cfg.clazz = cls

    def _handle(self, command, index: int, execute: bool):
        verb = "Operate" if execute else "Select"
        try:
            if isinstance(command, opendnp3.ControlRelayOutputBlock):
                point = self._layout.get((BO, index))
                if point is None:
                    self._log(f"{verb} CROB index {index}: no such BO point")
                    return opendnp3.CommandStatus.NOT_SUPPORTED
                code = command.functionCode
                if code in _ON_CODES:
                    state = True
                elif code in _OFF_CODES:
                    state = False
                else:
                    self._log(f"{verb} {point.name}: unsupported control code {code}")
                    return opendnp3.CommandStatus.NOT_SUPPORTED
                self._log(f"Master {verb} {point.name} (BO {index}) -> {point.captions()[int(state)]}")
                if execute and self.on_binary_command:
                    self.on_binary_command(point.name, state)
                return opendnp3.CommandStatus.SUCCESS

            # Analog output: Int16 / Int32 / Float32 / Double64 all expose .value
            point = self._layout.get((AO, index))
            if point is None:
                self._log(f"{verb} AO index {index}: no such AO point")
                return opendnp3.CommandStatus.NOT_SUPPORTED
            value = float(command.value)
            if (point.min is not None and value < point.min) or (point.max is not None and value > point.max):
                self._log(f"Master {verb} {point.name} = {value}: rejected, outside {point.min}..{point.max}")
                return opendnp3.CommandStatus.OUT_OF_RANGE
            self._log(f"Master {verb} {point.name} (AO {index}) = {value}")
            if execute and self.on_analog_command:
                self.on_analog_command(point.name, value)
            return opendnp3.CommandStatus.SUCCESS
        except Exception as e:  # never let an exception escape into the C++ stack
            log.exception("command handling failed")
            self._log(f"Command error: {e}")
            return opendnp3.CommandStatus.HARDWARE_ERROR

    def _log(self, msg: str) -> None:
        log.info(msg)
        if self.on_log:
            self.on_log(msg)
