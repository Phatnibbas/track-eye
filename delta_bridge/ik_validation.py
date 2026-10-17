"""Compare master IK reply with inspected local firmware math, not motor motion."""
import ast
import importlib.util
from pathlib import Path
import re

from .core import finite_number

NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
IK_RE = re.compile(rf"^IK az=({NUMBER}) tilt=({NUMBER}) twist=({NUMBER}) -> (.+)$")
MOTOR_RE = re.compile(rf"n(\d+)=({NUMBER})")


def parse_ik(line, expected_nodes):
    match = IK_RE.fullmatch(line)
    if match is None:
        raise ValueError("not a complete IK reply")
    az, tilt, twist = (float(x) for x in match.groups()[:3])
    values = {}
    for token in match.group(4).split():
        motor = MOTOR_RE.fullmatch(token)
        if motor is None or int(motor[1]) in values:
            raise ValueError("malformed/duplicate IK motor")
        values[int(motor[1])] = float(motor[2])
    if set(values) != set(expected_nodes) or not all(finite_number(v) for v in (az, tilt, twist, *values.values())):
        raise ValueError("IK reply nodes/numbers do not match contract")
    return (az, tilt, twist), values


class FirmwareIKReference:
    """Explicit source paths. Does not import master with its hardware entry point."""
    def __init__(self, ik_path: Path, master_path: Path, neutral_path: Path):
        spec = importlib.util.spec_from_file_location("delta_reference_ik", ik_path)
        self.math = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.math)
        self.neutral = tuple(float(v) for v in neutral_path.read_text().split())
        assignments = {}
        for node in ast.parse(master_path.read_text(encoding="utf-8")).body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "MOTOR_SIGN":
                        assignments[target.id] = ast.literal_eval(node.value)
        self.signs = tuple(assignments["MOTOR_SIGN"])
        if len(self.signs) != len(self.neutral) or any(v not in (-1, 1) for v in self.signs) or not all(finite_number(v) for v in self.neutral):
            raise ValueError("invalid reference motor signs/neutral")
        self.zero = self.math.ik(0, 0, 0)

    def targets(self, polar):
        angles = self.math.ik(*polar)
        return {i + 1: n + s * self.math.wrap180(th - z)
                for i, (n, s, th, z) in enumerate(zip(self.neutral, self.signs, angles, self.zero))}


def compare_ik(command_polar, reply, reference, expected_nodes, tolerance_deg):
    if not finite_number(tolerance_deg) or tolerance_deg <= 0:
        raise ValueError("explicit finite positive comparison tolerance required")
    polar, motors = parse_ik(reply, expected_nodes)
    # Compare to exact rounded numbers sent on the text wire.
    wire_polar = tuple(float(f"{v:.3f}") for v in command_polar)
    if polar != wire_polar:
        raise ValueError("master echoed angles differ from transmitted angles")
    wanted = reference.targets(wire_polar)
    error = {n: abs(motors[n] - wanted[n]) for n in expected_nodes}
    if max(error.values()) > tolerance_deg:
        raise ValueError("master motor targets differ from reference IK")
    return {"wire_polar": wire_polar, "reply_motors": motors,
            "reference_motors": wanted, "errors_deg": error, "match": True}
