import unittest

from track_eye.tracker import TrackingResult


class FilteringContractTests(unittest.TestCase):
    def test_no_face_has_no_eye_values(self):
        result = TrackingResult(123, False, None, 4.5)
        self.assertFalse(result.face_detected)
        self.assertIsNone(result.eyes)


if __name__ == "__main__":
    unittest.main()
