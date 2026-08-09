import os
import threading
import unittest
from unittest.mock import patch

from aiot.streaming.agent_channel import AgentChannelServer, PublisherChannel


class AgentChannelTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.server_event = threading.Event()
        self.server = AgentChannelServer(self._on_server_event)
        self.addCleanup(self.server.close)

    def _on_server_event(self, event):
        self.events.append(event)
        self.server_event.set()

    def test_channel_stays_open_after_connect_timeout_and_relays_both_directions(self):
        child_messages = []
        child_event = threading.Event()

        def on_child_message(message):
            child_messages.append(message)
            child_event.set()

        with patch.dict(os.environ, self.server.child_environment(), clear=False):
            channel = PublisherChannel.from_environment(on_child_message)
        self.addCleanup(channel.close)

        channel.emit({"type": "motion", "active": True})
        self.assertTrue(self.server_event.wait(1))
        self.assertEqual(self.events, [{"type": "motion", "active": True}])

        self.assertTrue(self.server.send({"type": "face_presence", "face_count": 1}))
        self.assertTrue(child_event.wait(1))
        self.assertEqual(child_messages, [{"type": "face_presence", "face_count": 1}])


if __name__ == "__main__":
    unittest.main()
