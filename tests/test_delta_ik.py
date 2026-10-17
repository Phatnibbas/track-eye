import unittest
from pathlib import Path

from delta_bridge.ik_validation import FirmwareIKReference, compare_ik, parse_ik
from delta_bridge.serial_transport import ReadOnlySerial
from delta_bridge.config import SerialPolicy


class IKTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parent / "fixtures" / "delta_v1_20261008"
        self.reference = FirmwareIKReference(root / "spm_ik.py", root / "main.py", root / "neutral.txt")

    def test_neutral_reply_and_rounding(self):
        reply = "IK az=0.0 tilt=0.0 twist=0.0 -> n1=12.857 n2=12.857 n3=12.857"
        self.assertTrue(compare_ik((0, 0, 0), reply, self.reference, (1, 2, 3), .000501)["match"])
        polar = (123.4567, 1.2345, 0)
        wire = tuple(float(f"{v:.3f}") for v in polar)
        motors = self.reference.targets(wire)
        line = f"IK az={wire[0]} tilt={wire[1]} twist={wire[2]} -> " + " ".join(f"n{n}={v:.3f}" for n, v in motors.items())
        self.assertTrue(compare_ik(polar, line, self.reference, (1, 2, 3), .000501)["match"])

    def test_wrong_echo_duplicate_motor_and_wrong_targets(self):
        for reply in ("IK az=1 tilt=0 twist=0 -> n1=12.857 n2=12.857 n3=12.857",
                      "IK az=0 tilt=0 twist=0 -> n1=12.857 n1=12.857 n3=12.857",
                      "IK az=0 tilt=0 twist=0 -> n1=0 n2=0 n3=0"):
            with self.assertRaises(ValueError):
                compare_ik((0, 0, 0), reply, self.reference, (1, 2, 3), .000501)

    def test_typed_query_cannot_inject_motion(self):
        link = ReadOnlySerial(SerialPolicy("unused", 115200, 1, 512))
        captured = []
        link._write_line = captured.append
        link.send_ik(90, 2, 0)
        self.assertEqual(captured, ["ik 90.000 2.000 0.000"])
        for bad in ("0\nlook 0 0", float("nan"), True):
            with self.assertRaises(ValueError):
                link.send_ik(bad, 2, 0)


if __name__ == "__main__":
    unittest.main()
