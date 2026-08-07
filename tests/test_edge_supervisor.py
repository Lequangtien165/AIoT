import unittest
from unittest.mock import Mock

from aiot.mqtt import payloads
from aiot.streaming.edge_supervisor import (
    CommandValidationError,
    EdgeState,
    EdgeStateMachine,
    EdgeSupervisor,
    validate_command,
)


class EdgeCommandValidationTests(unittest.TestCase):
    def command(self, **overrides):
        message = payloads.stream_control(
            action="start",
            target_device_id="edge-1",
            command_id="cmd-1",
        )
        message.update(overrides)
        return message

    def test_validates_whitelisted_command_and_target(self):
        command = validate_command(self.command(), "edge-1")
        self.assertEqual((command.command_id, command.action), ("cmd-1", "start"))

    def test_rejects_unknown_action_and_missing_command_id(self):
        with self.assertRaises(CommandValidationError):
            validate_command(self.command(action="exec"), "edge-1")
        with self.assertRaises(CommandValidationError):
            validate_command(self.command(command_id=""), "edge-1")
        with self.assertRaises(CommandValidationError):
            validate_command(self.command(parameters={"shell": "ignored"}), "edge-1")

    def test_rejects_commands_for_another_device(self):
        with self.assertRaises(CommandValidationError):
            validate_command(self.command(), "edge-2")


class EdgeStateMachineTests(unittest.TestCase):
    def test_valid_lifecycle(self):
        machine = EdgeStateMachine()
        for state in (EdgeState.STARTING, EdgeState.STREAMING, EdgeState.STOPPING, EdgeState.STOPPED):
            machine.transition(state)
        self.assertEqual(machine.state, EdgeState.STOPPED)

    def test_rejects_invalid_transition(self):
        machine = EdgeStateMachine(EdgeState.STREAMING)
        with self.assertRaises(ValueError):
            machine.transition(EdgeState.STARTING)


class EdgeSupervisorTests(unittest.TestCase):
    def setUp(self):
        self.start = Mock()
        self.stop = Mock()
        self.alive = Mock(return_value=True)
        self.healthy = Mock(return_value=True)
        self.supervisor = EdgeSupervisor(
            device_id="edge-1",
            start_runtime=self.start,
            stop_runtime=self.stop,
            runtime_alive=self.alive,
            rtsp_healthy=self.healthy,
        )
        self.supervisor.machine.transition(EdgeState.STARTING)
        self.supervisor.machine.transition(EdgeState.STREAMING)

    def command(self, action, command_id):
        return validate_command(
            payloads.stream_control(action=action, target_device_id="edge-1", command_id=command_id),
            "edge-1",
        )

    def test_stop_start_and_restart(self):
        stop_ack = self.supervisor.handle(self.command("stop", "stop-1"))
        self.assertEqual(stop_ack["result"], "succeeded")
        self.assertEqual(self.supervisor.state, EdgeState.STOPPED)
        start_ack = self.supervisor.handle(self.command("start", "start-1"))
        self.assertEqual(start_ack["result"], "succeeded")
        self.assertEqual(self.supervisor.state, EdgeState.STREAMING)
        restart_ack = self.supervisor.handle(self.command("restart", "restart-1"))
        self.assertEqual(restart_ack["result"], "succeeded")
        self.assertEqual(self.start.call_count, 2)
        self.assertEqual(self.stop.call_count, 2)

    def test_duplicate_command_is_idempotent(self):
        first = self.supervisor.handle(self.command("stop", "same-id"))
        second = self.supervisor.handle(self.command("stop", "same-id"))
        self.assertEqual(first, second)
        self.assertEqual(self.stop.call_count, 1)

    def test_runtime_exit_moves_to_error_unless_stop_was_requested(self):
        self.alive.return_value = False
        self.supervisor.observe_runtime()
        self.assertEqual(self.supervisor.state, EdgeState.ERROR)

    def test_status_returns_health_without_side_effects(self):
        ack = self.supervisor.handle(self.command("status", "status-1"))
        self.assertEqual(ack["result"], "succeeded")
        self.assertEqual(ack["action"], "status")
        self.assertEqual(ack["command_id"], "status-1")
        self.assertEqual(ack["message"], "status returned")
        status = ack["status"]
        self.assertEqual(status["state"], "streaming")
        self.assertEqual(status["mode"], "continuous")
        self.assertTrue(status["runtime_alive"])
        self.assertTrue(status["rtsp_healthy"])
        self.assertEqual(self.start.call_count, 0)
        self.assertEqual(self.stop.call_count, 0)
        self.assertEqual(self.supervisor.state, EdgeState.STREAMING)

    def test_status_varies_with_runtime_health(self):
        self.alive.return_value = False
        self.healthy.return_value = False
        ack = self.supervisor.handle(self.command("status", "status-2"))
        status = ack["status"]
        self.assertFalse(status["runtime_alive"])
        self.assertFalse(status["rtsp_healthy"])

    def test_restart_recovers_from_error_state(self):
        self.supervisor.machine.transition(EdgeState.ERROR)
        ack = self.supervisor.handle(self.command("restart", "restart-error-1"))
        self.assertEqual(ack["result"], "succeeded")
        self.assertEqual(ack["message"], "runtime restarted")
        self.assertEqual(self.supervisor.state, EdgeState.STREAMING)
        self.assertFalse(self.stop.called)
        self.assertEqual(self.start.call_count, 1)

    def test_restart_failure_moves_to_error(self):
        self.start.side_effect = RuntimeError("boom")
        self.supervisor.machine.transition(EdgeState.STOPPING)
        self.supervisor.machine.transition(EdgeState.STOPPED)
        ack = self.supervisor.handle(self.command("restart", "restart-fail-1"))
        self.assertEqual(ack["result"], "failed")
        self.assertEqual(self.supervisor.state, EdgeState.ERROR)


if __name__ == "__main__":
    unittest.main()
