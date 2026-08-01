import unittest

from aiot.tracking.face_tracker import FaceTracker, iou


class FaceTrackerTests(unittest.TestCase):
    def test_iou_for_overlapping_boxes(self):
        self.assertAlmostEqual(iou((0, 0, 10, 10), (5, 5, 15, 15)), 25 / 175)

    def test_moving_face_keeps_track_id(self):
        tracker = FaceTracker(min_face_size=1)
        first = tracker.update([(10, 10, 110, 110)], 1)[0]
        second = tracker.update([(15, 12, 115, 112)], 2)[0]

        self.assertEqual(first.track_id, second.track_id)

    def test_center_distance_fallback_keeps_track_id_when_iou_drops(self):
        tracker = FaceTracker(min_face_size=1)
        first = tracker.update([(0, 0, 100, 100)], 1)[0]
        second = tracker.update([(70, 0, 170, 100)], 2)[0]

        self.assertEqual(first.track_id, second.track_id)
        self.assertEqual(len(tracker.tracks), 1)

    def test_expired_track_is_removed(self):
        tracker = FaceTracker(ttl_frames=1, min_face_size=1)
        tracker.update([(10, 10, 110, 110)], 1)
        tracker.update([], 2)
        tracker.update([], 3)

        self.assertEqual(tracker.tracks, {})

    def test_track_survives_until_missed_frames_exceed_ttl(self):
        tracker = FaceTracker(ttl_frames=1, min_face_size=1)
        tracker.update([(10, 10, 110, 110)], 1)

        tracker.update([], 2)

        self.assertEqual(len(tracker.tracks), 1)
        self.assertEqual(tracker.tracks[1].missed_frames, 1)

    def test_scheduler_respects_age_interval_and_limit(self):
        tracker = FaceTracker(
            min_age_frames=2,
            min_face_size=1,
            recognition_interval_frames=3,
        )
        tracker.update([(0, 0, 100, 100), (200, 0, 300, 100)], 1)
        self.assertEqual(tracker.select_for_recognition(1), [])
        tracker.update([(0, 0, 100, 100), (200, 0, 300, 100)], 2)

        selected = tracker.select_for_recognition(2, maximum=1)
        self.assertEqual(len(selected), 1)
        self.assertEqual(tracker.select_for_recognition(3, maximum=2), [tracker.tracks[2]])

    def test_scheduler_prioritizes_pending_then_unknown_then_matched(self):
        tracker = FaceTracker(min_age_frames=1, min_face_size=1, label_confirmations=1)
        tracks = tracker.update([(0, 0, 100, 100), (200, 0, 300, 100), (400, 0, 500, 100)], 1)
        pending, unknown, matched = tracks
        tracker.apply_recognition(unknown.track_id, "", 0.1, 0.45)
        tracker.apply_recognition(matched.track_id, "An", 0.8, 0.45)

        selected = tracker.select_for_recognition(2, maximum=3)

        self.assertEqual([track.track_id for track in selected], [pending.track_id, unknown.track_id, matched.track_id])

    def test_matched_track_uses_longer_recognition_cooldown(self):
        tracker = FaceTracker(
            min_age_frames=1,
            min_face_size=1,
            recognition_interval_frames=1,
            matched_recognition_interval_frames=10,
            label_confirmations=1,
        )
        track = tracker.update([(0, 0, 100, 100)], 1)[0]
        tracker.apply_recognition(track.track_id, "An", 0.8, 0.45)
        tracker.select_for_recognition(2)

        self.assertEqual(tracker.select_for_recognition(3), [])
        self.assertEqual(tracker.select_for_recognition(12), [track])

    def test_identity_requires_confirmation_and_does_not_repeat_event(self):
        tracker = FaceTracker(min_face_size=1, label_confirmations=2)
        track = tracker.update([(0, 0, 100, 100)], 1)[0]

        self.assertIsNone(tracker.apply_recognition(track.track_id, "An", 0.8, 0.45))
        event = tracker.apply_recognition(track.track_id, "An", 0.8, 0.45)
        self.assertEqual(event.kind, "identity_confirmed")
        self.assertIsNone(tracker.apply_recognition(track.track_id, "An", 0.8, 0.45))

    def test_identity_loss_requires_confirmation(self):
        tracker = FaceTracker(min_face_size=1, label_confirmations=1, unknown_confirmations=2)
        track = tracker.update([(0, 0, 100, 100)], 1)[0]
        tracker.apply_recognition(track.track_id, "An", 0.8, 0.45)

        self.assertIsNone(tracker.apply_recognition(track.track_id, "", 0.2, 0.45))
        event = tracker.apply_recognition(track.track_id, "", 0.2, 0.45)
        self.assertEqual(event.kind, "identity_lost")

    def test_identity_change_requires_score_margin(self):
        tracker = FaceTracker(min_face_size=1, label_confirmations=1, label_switch_margin=0.05)
        track = tracker.update([(0, 0, 100, 100)], 1)[0]
        tracker.apply_recognition(track.track_id, "An", 0.8, 0.45)

        self.assertIsNone(tracker.apply_recognition(track.track_id, "Binh", 0.84, 0.45))
        event = tracker.apply_recognition(track.track_id, "Binh", 0.86, 0.45)

        self.assertEqual(event.kind, "identity_changed")
        self.assertEqual(track.label, "Binh")


if __name__ == "__main__":
    unittest.main()
