"""MQTT command validation and persistent edge runtime supervision."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable

from aiot.mqtt import payloads


class EdgeState(str, Enum):
    OFFLINE = "offline"
    STARTING = "starting"
    STREAMING = "streaming"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"


class CommandValidationError(ValueError):
    """Raised when an MQTT command does not match the control schema."""


ALLOWED_ACTIONS = frozenset({"status", "start", "stop", "restart"})
COMMAND_FIELDS = frozenset(
    {"schema_version", "ts_ms", "command_id", "requested_by", "target_device_id", "action", "parameters"}
)
ALLOWED_TRANSITIONS = {
    EdgeState.OFFLINE: {EdgeState.STARTING, EdgeState.STOPPED, EdgeState.ERROR},
    EdgeState.STARTING: {EdgeState.STREAMING, EdgeState.STOPPING, EdgeState.ERROR},
    EdgeState.STREAMING: {EdgeState.STOPPING, EdgeState.ERROR},
    EdgeState.STOPPING: {EdgeState.STOPPED, EdgeState.STARTING, EdgeState.ERROR},
    EdgeState.STOPPED: {EdgeState.STARTING, EdgeState.ERROR},
    EdgeState.ERROR: {EdgeState.STARTING, EdgeState.STOPPING, EdgeState.STOPPED},
}


@dataclass(frozen=True)
class EdgeCommand:
    command_id: str
    action: str
    requested_by: str
    parameters: dict[str, Any]


def validate_command(message: dict[str, Any], device_id: str) -> EdgeCommand:
    if not isinstance(message, dict):
        raise CommandValidationError("payload must be a JSON object")
    unknown_fields = set(message) - COMMAND_FIELDS
    if unknown_fields:
        raise CommandValidationError(f"unknown command fields: {', '.join(sorted(unknown_fields))}")
    if message.get("schema_version") != payloads.SCHEMA_VERSION:
        raise CommandValidationError("unsupported schema_version")
    if message.get("target_device_id") != device_id:
        raise CommandValidationError("target_device_id does not match this device")
    command_id = message.get("command_id")
    if not isinstance(command_id, str) or not command_id.strip() or len(command_id) > 128:
        raise CommandValidationError("command_id must be a non-empty string of at most 128 characters")
    action = message.get("action")
    if action not in ALLOWED_ACTIONS:
        raise CommandValidationError("action is not supported")
    requested_by = message.get("requested_by", "cloud")
    if not isinstance(requested_by, str) or not requested_by.strip() or len(requested_by) > 128:
        raise CommandValidationError("requested_by must be a non-empty string of at most 128 characters")
    parameters = message.get("parameters", {})
    if not isinstance(parameters, dict):
        raise CommandValidationError("parameters must be an object")
    if parameters:
        raise CommandValidationError("parameters are reserved and must be empty in the command MVP")
    return EdgeCommand(command_id.strip(), action, requested_by.strip(), dict(parameters))


class EdgeStateMachine:
    def __init__(self, state: EdgeState = EdgeState.OFFLINE) -> None:
        self.state = state

    def transition(self, state: EdgeState) -> EdgeState:
        if state == self.state:
            return state
        if state not in ALLOWED_TRANSITIONS[self.state]:
            raise ValueError(f"invalid edge transition: {self.state.value} -> {state.value}")
        self.state = state
        return state


class EdgeSupervisor:
    """State and command policy for a long-lived runtime owner.

    Runtime callbacks are deliberately injected so the MQTT/control behavior can
    be tested without starting MediaMTX or FFmpeg.
    """

    def __init__(
        self,
        *,
        device_id: str,
        start_runtime: Callable[[], None],
        stop_runtime: Callable[[], None],
        runtime_alive: Callable[[], bool],
        rtsp_healthy: Callable[[], bool],
        mode: str = "continuous",
        stream_active: Callable[[], bool] | None = None,
    ) -> None:
        self.device_id = device_id
        self.start_runtime = start_runtime
        self.stop_runtime = stop_runtime
        self.runtime_alive = runtime_alive
        self.rtsp_healthy = rtsp_healthy
        self.stream_active = stream_active
        self.mode = mode
        self.machine = EdgeStateMachine()
        self._handled_commands: dict[str, dict[str, Any]] = {}
        self._requested_stop = False

    @property
    def state(self) -> EdgeState:
        return self.machine.state

    def status(self) -> dict[str, Any]:
        status = {
            "state": self.state.value,
            "mode": self.mode,
            "runtime_alive": self.runtime_alive(),
            "rtsp_healthy": self.rtsp_healthy(),
        }
        if self.stream_active is not None:
            status["rtsp_stream_active"] = self.stream_active()
        return status

    def handle(self, command: EdgeCommand) -> dict[str, Any]:
        previous = self._handled_commands.get(command.command_id)
        if previous is not None:
            return previous
        self.observe_runtime()

        if command.action == "status":
            result = self._ack(command, "succeeded", "status returned")
        elif command.action == "stop":
            result = self._handle_stop(command)
        elif command.action == "start":
            result = self._handle_start(command)
        else:
            result = self._handle_restart(command)

        result["status"] = self.status()
        self._handled_commands[command.command_id] = result
        if len(self._handled_commands) > 256:
            del self._handled_commands[next(iter(self._handled_commands))]
        return result

    def _handle_stop(self, command: EdgeCommand) -> dict[str, Any]:
        if self.state in {EdgeState.OFFLINE, EdgeState.STOPPED, EdgeState.STOPPING}:
            if self.state == EdgeState.OFFLINE:
                self.machine.transition(EdgeState.STOPPED)
            return self._ack(command, "succeeded", "runtime is already stopped")
        self.machine.transition(EdgeState.STOPPING)
        self._requested_stop = True
        try:
            self.stop_runtime()
        except Exception as error:
            self.machine.transition(EdgeState.ERROR)
            return self._ack(command, "failed", str(error))
        self.machine.transition(EdgeState.STOPPED)
        return self._ack(command, "succeeded", "runtime stopped")

    def _handle_start(self, command: EdgeCommand) -> dict[str, Any]:
        if self.state in {EdgeState.STARTING, EdgeState.STREAMING}:
            return self._ack(command, "succeeded", "runtime is already started")
        self.machine.transition(EdgeState.STARTING)
        self._requested_stop = False
        try:
            self.start_runtime()
        except Exception as error:
            self.machine.transition(EdgeState.ERROR)
            return self._ack(command, "failed", str(error))
        self.machine.transition(EdgeState.STREAMING)
        return self._ack(command, "succeeded", "runtime started")

    def _handle_restart(self, command: EdgeCommand) -> dict[str, Any]:
        if self.state not in {EdgeState.OFFLINE, EdgeState.STOPPED, EdgeState.ERROR}:
            self.machine.transition(EdgeState.STOPPING)
            self._requested_stop = True
            try:
                self.stop_runtime()
            except Exception as error:
                self.machine.transition(EdgeState.ERROR)
                return self._ack(command, "failed", str(error))
            self.machine.transition(EdgeState.STOPPED)
        self.machine.transition(EdgeState.STARTING)
        self._requested_stop = False
        try:
            self.start_runtime()
        except Exception as error:
            self.machine.transition(EdgeState.ERROR)
            return self._ack(command, "failed", str(error))
        self.machine.transition(EdgeState.STREAMING)
        return self._ack(command, "succeeded", "runtime restarted")

    def observe_runtime(self) -> EdgeState:
        if self.state in {EdgeState.STARTING, EdgeState.STREAMING} and not self.runtime_alive():
            if self._requested_stop:
                self.machine.transition(EdgeState.STOPPED)
            else:
                self.machine.transition(EdgeState.ERROR)
        return self.state

    def _ack(self, command: EdgeCommand, result: str, message: str) -> dict[str, Any]:
        return payloads.command_ack(
            command_id=command.command_id,
            target_device_id=self.device_id,
            action=command.action,
            result=result,
            message=message,
            state=self.state.value,
        )
