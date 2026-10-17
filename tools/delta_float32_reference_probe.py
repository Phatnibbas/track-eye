"""Hypothesis-only float32 arithmetic model of inspected IK source.

Not a MicroPython emulator or an independent kinematics validator. It helps
explain a host-double/reference discrepancy; it cannot prove board build flags.
"""
import argparse
import ast
import json
import math
from pathlib import Path
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from delta_bridge.ik_validation import FirmwareIKReference


def f32(value):
    return struct.unpack("<f", struct.pack("<f", float(value)))[0]


class RoundFloat(ast.NodeTransformer):
    def visit_ImportFrom(self, node):
        return None if node.module == "math" else node

    def visit_Constant(self, node):
        if type(node.value) is float:
            return ast.copy_location(ast.Call(func=ast.Name(id="f32", ctx=ast.Load()),
                                             args=[node], keywords=[]), node)
        return node

    def visit_BinOp(self, node):
        self.generic_visit(node)
        return ast.copy_location(ast.Call(func=ast.Name(id="f32", ctx=ast.Load()),
                                         args=[node], keywords=[]), node)


def build_hypothesis(ik_path):
    def sum32(values):
        total = 0
        for value in values:
            total = f32(total + value)
        return total
    namespace = {"f32": f32, "sum": sum32}
    for name in ("sin", "cos", "acos", "sqrt"):
        function = getattr(math, name)
        namespace[name] = lambda value, fn=function: f32(fn(value))
    namespace["atan2"] = lambda x, y: f32(math.atan2(x, y))
    namespace["radians"] = lambda x: f32(x * f32(math.pi / 180))
    namespace["degrees"] = lambda x: f32(x * f32(180 / math.pi))
    tree = RoundFloat().visit(ast.parse(ik_path.read_text(encoding="utf-8")))
    ast.fix_missing_locations(tree)
    exec(compile(tree, str(ik_path) + ":float32-hypothesis", "exec"), namespace)
    return namespace


def explain(reference_dir, polar):
    ref = FirmwareIKReference(reference_dir / "spm_ik.py", reference_dir / "main.py",
                              reference_dir / "neutral.txt")
    model = build_hypothesis(reference_dir / "spm_ik.py")
    single_polar = tuple(f32(v) for v in polar)
    angles = model["ik"](*single_polar)
    zero = model["ik"](0, 0, 0)
    targets = {i + 1: f32(f32(n) + f32(s * model["wrap180"](f32(a - z))))
               for i, (n, s, a, z) in enumerate(zip(ref.neutral, ref.signs, angles, zero))}
    return {"hypothesis_only": True, "polar": polar, "float32_inputs": single_polar,
            "host_double_targets": ref.targets(polar), "float32_model_targets": targets,
            "float32_model_text_3dp": {n: f"{v:.3f}" for n, v in targets.items()},
            "limitation": "Rounds Python operations/transcendentals to float32; not proof of deployed MicroPython arithmetic"}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--reference-dir", type=Path, required=True)
    p.add_argument("--az", type=float, required=True)
    p.add_argument("--tilt", type=float, required=True)
    p.add_argument("--twist", type=float, required=True)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    result = explain(a.reference_dir, (a.az, a.tilt, a.twist))
    with a.out.open("x", encoding="utf-8") as out:
        json.dump(result, out, indent=2, allow_nan=False)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
