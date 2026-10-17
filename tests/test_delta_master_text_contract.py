"""Execute the actual master parser AST with motor dispatch replaced by a spy.

Does not import MicroPython main(), contact a board or simulate motor physics.
"""
import ast
import contextlib
import io
import struct
from pathlib import Path
from types import SimpleNamespace
import unittest

LEGACY = Path(__file__).resolve().parent / "fixtures" / "delta_v1_20261008"


def parser_subject():
    source = (LEGACY / "main.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Master")
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "handle_line")
    namespace = {"P": SimpleNamespace(NUM_NODES=3, ALL_NODES=7)}
    exec(compile(ast.Module(body=[method], type_ignores=[]), "actual-master-handle-line", "exec"), namespace)
    subject = SimpleNamespace(calls=[], received_polar=[], rejects=False)
    def look_targets(*polar):
        subject.received_polar.append(polar)
        return (None, "outside travel") if subject.rejects else ([12.001, 13.002, 14.003], None)
    subject.look_targets = look_targets
    subject.send_move = lambda *args: subject.calls.append(args)
    return namespace["handle_line"], subject


class TextContractTests(unittest.TestCase):
    def test_full_look_units_and_field_order(self):
        parse, robot = parser_subject()
        with contextlib.redirect_stdout(io.StringIO()) as out:
            parse(robot, "look 90.000 2.000 0.000 500\r\n")
        self.assertEqual(robot.received_polar, [(90.0, 2.0, 0.0)])
        self.assertEqual(robot.calls, [([12001, 13002, 14003], 7, 500)])
        self.assertIn("IK az=90.0 tilt=2.0 twist=0.0", out.getvalue())

    def test_ik_uses_same_angle_parser_without_dispatching_move(self):
        parse, robot = parser_subject()
        with contextlib.redirect_stdout(io.StringIO()) as out:
            parse(robot, "ik -90 2.5e-1 +0.0\n")
        self.assertEqual(robot.received_polar, [(-90.0, .25, 0.0)])
        self.assertEqual(robot.calls, [])
        self.assertIn("n1=12.001", out.getvalue())

    def test_wrong_data_format_not_accepted_as_motion(self):
        parse, robot = parser_subject()
        for data in ('{"x":0.5,"y":0.1}', "EYES,80,60,80,60,tracking", "0.5 0.1", "look x y", "look 90"):
            with contextlib.redirect_stdout(io.StringIO()) as out:
                parse(robot, data)
            self.assertIn("ERR", out.getvalue())
            self.assertEqual(robot.calls, [])

    def test_ik_print_is_not_move_acceptance_when_duration_invalid(self):
        parse, robot = parser_subject()
        with contextlib.redirect_stdout(io.StringIO()) as out:
            parse(robot, "look 90 2 0 not-ms")
        self.assertIn("IK az=", out.getvalue())
        self.assertIn("ERR", out.getvalue())
        self.assertEqual(robot.calls, [])

    def test_travel_rejection_blocks_ik_and_motion(self):
        parse, robot = parser_subject()
        robot.rejects = True
        with contextlib.redirect_stdout(io.StringIO()) as out:
            parse(robot, "look 90 2 0 500")
        self.assertIn("ERR look", out.getvalue())
        self.assertEqual(robot.calls, [])

    def test_optional_fields_and_extra_tokens_current_behavior(self):
        parse, robot = parser_subject()
        with contextlib.redirect_stdout(io.StringIO()):
            parse(robot, "LOOK\t90 2")
        self.assertEqual(robot.received_polar, [(90, 2, 0)])
        self.assertEqual(robot.calls[0][2], None)
        parse, robot = parser_subject()
        with contextlib.redirect_stdout(io.StringIO()):
            parse(robot, "look 90 2 0 500 unexpected")
        # Current firmware ignores extra tokens. This documents a weakness,
        # not an endorsement for the sender to generate ambiguous records.
        self.assertEqual(robot.calls[0][2], 500)


class ReaderContractTests(unittest.TestCase):
    def reader(self):
        source = (LEGACY / "main.py").read_text(encoding="utf-8")
        cls = next(n for n in ast.parse(source).body if isinstance(n, ast.ClassDef) and n.name == "LineReader")
        class Stdin:
            def __init__(self):
                self.data = ""
                self.fail = False
            def read(self, count):
                if self.fail:
                    raise UnicodeError("synthetic invalid input")
                c, self.data = self.data[:count], self.data[count:]
                return c
        stream = Stdin()
        class Poll:
            def register(self, *args):
                pass
            def poll(self, _timeout):
                return [(0, 1)] if stream.data or stream.fail else []
        namespace = {"sys": SimpleNamespace(stdin=stream), "select": SimpleNamespace(poll=Poll, POLLIN=1)}
        exec(compile(ast.Module(body=[cls], type_ignores=[]), "actual-master-reader", "exec"), namespace)
        return namespace["LineReader"](), stream

    def test_fragmentation_and_multiple_commands_crlf(self):
        reader, stream = self.reader()
        stream.data = "ik 90"
        self.assertIsNone(reader.read())
        stream.data = " 2 0\r\nstatus\n"
        self.assertEqual(reader.read(), "ik 90 2 0")
        self.assertEqual(reader.read(), "status")
        self.assertIsNone(reader.read())

    def test_unicode_error_propagates_and_buffer_has_no_bound(self):
        reader, stream = self.reader()
        stream.fail = True
        with self.assertRaises(UnicodeError):
            reader.read()
        stream.fail = False
        stream.data = "x" * 10000
        self.assertIsNone(reader.read())
        self.assertEqual(len(reader.buf), 10000)
        # Pure-source negative probe; malformed bytes/oversized records are
        # deliberately not transmitted to the live master.


class MasterForwardingContractTests(unittest.TestCase):
    def test_actual_send_move_packs_ms_and_three_millidegree_targets(self):
        source = (LEGACY / "main.py").read_text(encoding="utf-8")
        master = next(n for n in ast.parse(source).body if isinstance(n, ast.ClassDef) and n.name == "Master")
        method = next(n for n in master.body if isinstance(n, ast.FunctionDef) and n.name == "send_move")
        namespace = {"P": SimpleNamespace(MOVE_FMT="<Hiii", ST_MOVING=3), "struct": struct}
        exec(compile(ast.Module(body=[method], type_ignores=[]), "actual-master-send-move", "exec"), namespace)
        robot = SimpleNamespace(check_ready=lambda *a, **kw: None,
                                nodes=[SimpleNamespace(bit=1, state=1), SimpleNamespace(bit=2, state=1), SimpleNamespace(bit=4, state=1)],
                                min_duration_ms=lambda targets, mask: 100,
                                move_slot=None, dropped=0)
        namespace["send_move"](robot, [12001, 13002, 14003], 7, 500)
        mask, payload = robot.move_slot
        self.assertEqual(mask, 7)
        self.assertEqual(len(payload), 14)
        self.assertEqual(struct.unpack("<Hiii", payload), (500, 12001, 13002, 14003))

    def test_actual_ready_gate_prevents_packet_when_faulted(self):
        source = (LEGACY / "main.py").read_text(encoding="utf-8")
        master = next(n for n in ast.parse(source).body if isinstance(n, ast.ClassDef) and n.name == "Master")
        method = next(n for n in master.body if isinstance(n, ast.FunctionDef) and n.name == "send_move")
        namespace = {"P": SimpleNamespace(MOVE_FMT="<Hiii", ST_MOVING=3), "struct": struct}
        exec(compile(ast.Module(body=[method], type_ignores=[]), "actual-master-send-move", "exec"), namespace)
        robot = SimpleNamespace(check_ready=lambda *a, **kw: "faulted", move_slot=None)
        with contextlib.redirect_stdout(io.StringIO()) as out:
            namespace["send_move"](robot, [12001, 13002, 14003], 7, 500)
        self.assertIsNone(robot.move_slot)
        self.assertIn("ERR move", out.getvalue())


if __name__ == "__main__":
    unittest.main()
