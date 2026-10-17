"""Explicitly approved, finite neutral bench; not a production motion sender."""
import re
import time

from .core import MasterState, NODE_RE, finite_number
from .ik_validation import compare_ik
from .serial_transport import ReadOnlySerial, SerialProtocolError

HEADER_RE = re.compile(r"^STAT fault=(True|False) queue=(\d+) inflight=(\w+|-)$")


class BenchSession:
    def __init__(self, cfg, log, status_attempts, completion_tolerance_deg):
        if type(status_attempts) is not int or status_attempts <= 0:
            raise ValueError("explicit positive snapshot attempt bound required")
        if not finite_number(completion_tolerance_deg) or completion_tolerance_deg <= 0:
            raise ValueError("explicit positive reported-position tolerance required")
        self.cfg, self.log = cfg, log
        self.link = ReadOnlySerial(cfg.serial)
        self.status_attempts = status_attempts
        self.tolerance = completion_tolerance_deg
        self.clear_count = 0
        self.move_attempted = False
        self.post_clear = False

    def receive(self, timeout, allow_fault=False):
        raw, lines = self.link.receive(timeout)
        if raw:
            self.log(rx_hex=raw.hex(), lines=lines)
        if self.link.quarantined:
            raise SerialProtocolError("master boot/REPL/traceback")
        if not allow_fault:
            for line in lines:
                if (line.startswith(("ERR", "FAULT", "WARN STOP"))
                        or (line.startswith("EVT") and ("BOOT" in line or "OFFLINE" in line))):
                    raise SerialProtocolError(line)
        return lines

    def listen(self):
        end = time.monotonic() + self.cfg.serial.io_timeout_s
        while time.monotonic() < end:
            self.receive(max(0, end - time.monotonic()), allow_fault=True)

    def snapshot(self, allow_fault=False):
        for _ in range(self.status_attempts):
            state = MasterState(self.cfg.expected_nodes, self.cfg.snapshot_window_s)
            header = None
            details = {}
            self.link.send_query("status")
            self.log(tx="status")
            end = time.monotonic() + self.cfg.serial.io_timeout_s
            while time.monotonic() < end:
                for line in self.receive(max(0, end - time.monotonic()), allow_fault):
                    now = time.monotonic()
                    state.consume(line, now)
                    hm = HEADER_RE.fullmatch(line)
                    if hm:
                        header = {"fault": hm[1] == "True", "queue": int(hm[2]), "inflight": hm[3]}
                        details = {}
                    nm = NODE_RE.fullmatch(line)
                    if nm and header is not None:
                        nid, online, phase, err, homed, sw, pos, target = nm.groups()
                        details[int(nid)] = {"online": online == "ON", "state": phase,
                                             "err": err, "homed": homed == "1", "switch": sw == "1",
                                             "pos": float(pos), "target": float(target)}
                if state.snapshot_at is not None and set(details) == set(self.cfg.expected_nodes):
                    if self.link.lines.buffer:
                        raise SerialProtocolError("partial diagnostic remains after status")
                    self.log(snapshot=header, nodes=details)
                    return header, details
        raise SerialProtocolError("no complete fresh standalone status snapshot")

    def clear_once_if_needed(self):
        header, nodes = self.snapshot(allow_fault=True)
        validate_start(header, nodes, self.cfg.expected_nodes)
        if header["fault"]:
            if self.clear_count:
                raise RuntimeError("clear budget exhausted")
            self.clear_count += 1
            self.link._write_line("clear")  # Only this approved bench has this capability.
            self.log(tx="clear", explicit_operator_approval=True)
            end = time.monotonic() + self.cfg.serial.io_timeout_s
            ack = False
            while time.monotonic() < end:
                lines = self.receive(max(0, end - time.monotonic()))
                ack |= "OK CLEAR" in lines
                if ack:
                    break
            if not ack:
                raise TimeoutError("CLEAR did not receive OK; do not retry")
        self.post_clear = True
        header, nodes = self.snapshot()
        validate_start(header, nodes, self.cfg.expected_nodes)
        if header["fault"]:
            raise SerialProtocolError("master still faulted after one-shot clear")
        return header, nodes

    def configs(self):
        self.link.send_query("cfg")
        self.log(tx="cfg")
        configs = {}
        end = time.monotonic() + self.cfg.serial.io_timeout_s
        saw_cfg_ack = False
        while time.monotonic() < end:
            for line in self.receive(max(0, end - time.monotonic())):
                saw_cfg_ack |= line == "OK GETCFG"
                match = re.fullmatch(r"CFG n(\d+) (.+)", line)
                if match:
                    vals = {}
                    for token in match[2].split():
                        key, sep, value = token.partition("=")
                        if not sep or key in vals:
                            raise ValueError("incomplete or malformed live node config")
                        vals[key] = float(value)
                    if not all(finite_number(v) for v in vals.values()) or "min" not in vals or "max" not in vals or vals["min"] >= vals["max"]:
                        raise ValueError("live travel bounds invalid")
                    configs[int(match[1])] = vals
            if set(configs) == set(self.cfg.expected_nodes) and saw_cfg_ack:
                if self.link.lines.buffer:
                    raise SerialProtocolError("partial output remains after CFG acknowledgement")
                return configs
        raise TimeoutError("did not read travel bounds for every expected node")

    def verified_ik(self, polar, reference, tolerance):
        self.link.send_ik(*polar)
        self.log(tx=f"ik {polar[0]:.3f} {polar[1]:.3f} {polar[2]:.3f}")
        end = time.monotonic() + self.cfg.serial.io_timeout_s
        while time.monotonic() < end:
            for line in self.receive(max(0, end - time.monotonic())):
                if line.startswith("IK "):
                    result = compare_ik(polar, line, reference, self.cfg.expected_nodes, tolerance)
                    self.log(ik_verified=result)
                    return result["reply_motors"]
        raise TimeoutError("no matching IK response")

    def neutral(self, reference, duration_ms, completion_timeout_s, ik_tolerance):
        if type(duration_ms) is not int or not 1 <= duration_ms <= 65535:
            raise ValueError("explicit uint16 positive move duration required")
        if not finite_number(completion_timeout_s) or completion_timeout_s <= duration_ms / 1000:
            raise ValueError("completion timeout must exceed requested duration")
        self.clear_once_if_needed()
        cfgs = self.configs()
        targets = self.verified_ik((0, 0, 0), reference, ik_tolerance)
        validate_targets(targets, cfgs, self.cfg.expected_nodes)
        header, nodes = self.snapshot()
        validate_start(header, nodes, self.cfg.expected_nodes)
        if header["fault"]:
            raise SerialProtocolError("fault before movement")
        self.move_attempted = True
        self.link._write_line(f"look 0 0 0 {duration_ms}")
        self.log(tx=f"look 0 0 0 {duration_ms}", explicit_operator_approval=True)
        end = time.monotonic() + completion_timeout_s
        ok_move = False
        while time.monotonic() < end:
            until_poll = min(end, time.monotonic() + 1 / self.cfg.poll_hz)
            while time.monotonic() < until_poll:
                lines = self.receive(min(self.cfg.serial.io_timeout_s, max(0, until_poll - time.monotonic())))
                ok_move |= "OK MOVE" in lines
            header, nodes = self.snapshot()
            if header["fault"]:
                raise SerialProtocolError("master fault during neutral move")
            if any(not n["online"] or not n["homed"] or n["err"] != "NONE" or n["state"] not in ("IDLE", "MOVING") for n in nodes.values()):
                raise SerialProtocolError("node not ready during neutral move")
            if ok_move and all(n["state"] == "IDLE" and abs(n["pos"] - targets[i]) <= self.tolerance and abs(n["target"] - targets[i]) <= self.tolerance for i, n in nodes.items()):
                result = {"ok_move": True, "reported_completion": True,
                          "physical_motion_verified": False, "nodes": nodes, "targets": targets}
                self.log(**result)
                return result
        raise TimeoutError("neutral move reported completion deadline exceeded")

    def abort(self):
        if self.move_attempted and self.link.fd is not None and not self.link.quarantined:
            try:
                self.link._write_line("stop")
                self.log(tx="stop", emergency_on_abort=True)
            except (OSError, RuntimeError):
                self.log(stop_delivery_unverified=True)


def validate_start(header, nodes, expected_nodes):
    if header["queue"] != 0 or header["inflight"] != "-" or set(nodes) != set(expected_nodes):
        raise ValueError("master busy/incomplete snapshot")
    if any(not n["online"] or not n["homed"] or n["state"] != "IDLE" or n["err"] != "NONE" for n in nodes.values()):
        raise ValueError("every node must be online, homed, idle and error-free")


def validate_targets(targets, configs, expected_nodes):
    if set(targets) != set(expected_nodes) or set(configs) != set(expected_nodes):
        raise ValueError("incomplete target/config set")
    if any(not finite_number(d) or not configs[n]["min"] <= d <= configs[n]["max"] for n, d in targets.items()):
        raise ValueError("target outside live travel limits; no per-leg clamp")
