"""Strict experiment configuration. No installation-specific defaults."""
from dataclasses import dataclass
import json
from pathlib import Path

from .core import Mapping, finite_number


def positive(value, name):
    if not finite_number(value) or value <= 0:
        raise ValueError(f"{name} must be finite and positive")
    return value


def exact_keys(data, keys, name):
    if not isinstance(data, dict) or set(data) != set(keys):
        raise ValueError(f"{name} requires exactly: {', '.join(keys)}")


@dataclass(frozen=True)
class SerialPolicy:
    device: str
    baud: int
    io_timeout_s: float
    max_line_bytes: int

    def __post_init__(self):
        if not isinstance(self.device, str) or not self.device:
            raise ValueError("explicit serial device required")
        if type(self.baud) is not int or self.baud <= 0:
            raise ValueError("baud must be a positive integer")
        positive(self.io_timeout_s, "io_timeout_s")
        if type(self.max_line_bytes) is not int or self.max_line_bytes <= 0:
            raise ValueError("max_line_bytes must be a positive integer")


@dataclass(frozen=True)
class BridgeConfig:
    serial: SerialPolicy
    mapping: Mapping
    expected_nodes: tuple[int, ...]
    snapshot_window_s: float
    status_max_age_s: float
    frame_max_age_s: float
    poll_hz: float
    status_url: str


@dataclass(frozen=True)
class MonitorConfig:
    serial: SerialPolicy
    expected_nodes: tuple[int, ...]
    snapshot_window_s: float
    status_max_age_s: float
    poll_hz: float


def _read(path: Path):
    def unique(pairs):
        result = {}
        for k, v in pairs:
            if k in result:
                raise ValueError(f"duplicate config key: {k}")
            result[k] = v
        return result

    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique)


def _nodes(nodes):
    if (not isinstance(nodes, list) or not nodes or any(type(n) is not int or n <= 0 for n in nodes)
            or len(set(nodes)) != len(nodes)):
        raise ValueError("explicit unique node IDs required")
    return tuple(nodes)


def load_monitor_config(path: Path) -> MonitorConfig:
    data = _read(path)
    exact_keys(data, ("schema_version", "mode", "serial", "expected_nodes",
                     "snapshot_window_s", "status_max_age_s", "poll_hz"), "monitor config")
    if type(data["schema_version"]) is not int or data["schema_version"] != 1 or data["mode"] != "read-only":
        raise ValueError("schema 1 read-only monitor required")
    exact_keys(data["serial"], ("device", "baud", "io_timeout_s", "max_line_bytes"), "serial")
    for key in ("snapshot_window_s", "status_max_age_s", "poll_hz"):
        positive(data[key], key)
    return MonitorConfig(SerialPolicy(**data["serial"]), _nodes(data["expected_nodes"]),
                         data["snapshot_window_s"], data["status_max_age_s"], data["poll_hz"])


def load_config(path: Path) -> BridgeConfig:
    data = _read(path)
    exact_keys(data, ("schema_version", "serial", "mapping", "expected_nodes",
                     "snapshot_window_s", "status_max_age_s", "frame_max_age_s",
                     "poll_hz", "status_url", "mode"), "config")
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise ValueError("unsupported config schema")
    if data["mode"] != "dry-run":
        raise ValueError("hardware motion emission is not implemented")
    exact_keys(data["serial"], ("device", "baud", "io_timeout_s", "max_line_bytes"), "serial")
    exact_keys(data["mapping"], ("slot", "max_tilt_deg", "az_offset_deg", "x_sign",
                               "y_sign", "twist_deg", "duration_ms"), "mapping")
    nodes = _nodes(data["expected_nodes"])
    for key in ("snapshot_window_s", "status_max_age_s", "frame_max_age_s", "poll_hz"):
        positive(data[key], key)
    if not isinstance(data["status_url"], str) or not data["status_url"].startswith(("http://", "https://")):
        raise ValueError("HTTP status URL required")
    return BridgeConfig(SerialPolicy(**data["serial"]), Mapping(**data["mapping"]), tuple(nodes),
                        data["snapshot_window_s"], data["status_max_age_s"],
                        data["frame_max_age_s"], data["poll_hz"], data["status_url"])
