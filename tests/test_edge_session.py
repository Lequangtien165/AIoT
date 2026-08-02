import unittest

from aiot.streaming.edge_session import EdgeSessionController, EdgeSessionState


class EdgeSessionTests(unittest.TestCase):
    def test_discovery_expires_without_face_presence(self):
        session = EdgeSessionController(discovery_timeout=30, keepalive_timeout=120)
        session.begin()
        session.publisher_ready(now=10)

        self.assertEqual(session.state, EdgeSessionState.AWAITING_FACE)
        self.assertFalse(session.expired(now=39.9))
        self.assertTrue(session.expired(now=40))

    def test_presence_renews_only_matching_session(self):
        session = EdgeSessionController(discovery_timeout=30, keepalive_timeout=120)
        session_id = session.begin()
        session.publisher_ready(now=0)

        self.assertFalse(session.face_presence("old-session", 1, now=5))
        self.assertFalse(session.face_presence(session_id, 0, now=5))
        self.assertTrue(session.face_presence(session_id, 1, now=5))
        self.assertEqual(session.state, EdgeSessionState.STREAMING)
        self.assertFalse(session.expired(now=124.9))
        self.assertTrue(session.expired(now=125))

    def test_stop_returns_to_monitoring(self):
        session = EdgeSessionController()
        session.begin()
        session.stop()
        self.assertEqual(session.state, EdgeSessionState.STOPPING_STREAM)
        session.complete_stop()
        self.assertEqual(session.state, EdgeSessionState.MONITORING)
        self.assertIsNone(session.stream_session_id)
