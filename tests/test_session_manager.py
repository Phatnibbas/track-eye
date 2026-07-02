import unittest

from session_manager import SessionManager


class SessionManagerTests(unittest.TestCase):
    def test_starts_idle(self):
        manager = SessionManager()

        self.assertEqual(manager.state, "idle")
        self.assertFalse(manager.ready)

    def test_face_presence_locks_baseline_then_becomes_active(self):
        manager = SessionManager(acquire_frames=2, baseline_hold_s=1.0)

        manager.update(face_detected=True, confidence=0.8, timestamp_s=0.0)
        snapshot = manager.update(face_detected=True, confidence=0.8, timestamp_s=0.1)
        self.assertEqual(snapshot.state, "baseline_lock")
        self.assertFalse(snapshot.ready)

        snapshot = manager.update(face_detected=True, confidence=0.8, timestamp_s=1.2)
        self.assertEqual(snapshot.state, "active")
        self.assertTrue(snapshot.ready)

    def test_lost_face_resets_to_idle_and_requests_estimator_reset(self):
        manager = SessionManager(acquire_frames=1, baseline_hold_s=0.0, lost_face_timeout_s=0.5)
        manager.update(face_detected=True, confidence=0.8, timestamp_s=0.0)

        snapshot = manager.update(face_detected=False, confidence=0.0, timestamp_s=1.0)

        self.assertEqual(snapshot.state, "idle")
        self.assertTrue(snapshot.reset_required)
        self.assertEqual(snapshot.reason, "lost_user")

    def test_large_center_drift_marks_needs_recenter(self):
        manager = SessionManager(
            acquire_frames=1,
            baseline_hold_s=0.0,
            drift_threshold=0.25,
        )
        manager.update(face_detected=True, confidence=0.8, timestamp_s=0.0, x_eye=0.0, y_eye=0.0)

        snapshot = manager.update(face_detected=True, confidence=0.8, timestamp_s=1.0, x_eye=0.35, y_eye=0.0)

        self.assertEqual(snapshot.state, "needs_recenter")
        self.assertFalse(snapshot.ready)
        self.assertEqual(snapshot.reason, "center_drift")


if __name__ == "__main__":
    unittest.main()
