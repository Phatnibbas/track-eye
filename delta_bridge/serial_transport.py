"""Linux USB-UART transport for bounded, read-only Delta diagnostics.

Never toggles reset lines explicitly, never restores stale previous baud, never
sends move/home/clear/reset. Opening a UART may still affect physical modem lines;
that effect must be checked on the actual adapter, not inferred from this code.
"""
from __future__ import annotations

import os
import select
import time

from .config import SerialPolicy
from .core import finite_number


class SerialProtocolError(ValueError):
    pass


class TextLines:
    def __init__(self, max_bytes: int):
        self.max_bytes = max_bytes
        self.buffer = bytearray()

    def feed(self, data: bytes) -> list[str]:
        lines = []
        for byte in data:
            # Firmware diagnostics contain Vietnamese UTF-8. Decode only complete
            # lines so USB reads may split a multibyte character safely.
            if byte not in (9, 10, 13) and (byte < 32 or byte == 127):
                self.buffer.clear()
                raise SerialProtocolError("unexpected control byte in master stream")
            if byte == 10:
                try:
                    lines.append(self.buffer.decode("utf-8", "strict").rstrip("\r"))
                except UnicodeDecodeError as exc:
                    raise SerialProtocolError("invalid UTF-8 in master stream") from exc
                finally:
                    self.buffer.clear()
            else:
                self.buffer.append(byte)
                if len(self.buffer) > self.max_bytes:
                    self.buffer.clear()
                    raise SerialProtocolError("master line exceeds configured bound")
        return lines


class ReadOnlySerial:
    def __init__(self, policy: SerialPolicy):
        self.policy = policy
        self.fd = None
        self.lines = TextLines(policy.max_line_bytes)
        self.quarantined = False
        self.last_rx = b""

    def open(self):
        import fcntl
        import termios
        if self.fd is not None:
            raise RuntimeError("serial already open")
        speed = getattr(termios, f"B{self.policy.baud}", None)
        if speed is None:
            raise ValueError("baud unsupported by this host")
        fd = os.open(self.policy.device, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.ioctl(fd, termios.TIOCEXCL)
            attrs = termios.tcgetattr(fd)
            attrs[0] = attrs[1] = attrs[3] = 0
            attrs[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
            attrs[4] = attrs[5] = speed
            attrs[6][termios.VMIN] = 0
            attrs[6][termios.VTIME] = 0
            termios.tcsetattr(fd, termios.TCSANOW, attrs)
        except BaseException:
            os.close(fd)
            raise
        self.fd = fd
        self.lines = TextLines(self.policy.max_line_bytes)
        self.quarantined = False

    def close(self):
        if self.fd is not None:
            fd, self.fd = self.fd, None
            os.close(fd)
        self.quarantined = True

    def _require_open(self):
        if self.fd is None or self.quarantined:
            raise RuntimeError("serial session is closed/quarantined")

    def send_query(self, command: str):
        # Exactly the non-motion commands inspected in the existing master.
        if command not in ("status", "cfg", "ik 0 0 0"):
            raise ValueError("only status, cfg, or neutral IK query is allowed")
        self._write_line(command)

    def send_ik(self, az: float, tilt: float, twist: float):
        """Typed calculation-only query; cannot inject motion or another line."""
        if any(not finite_number(v) for v in (az, tilt, twist)):
            raise ValueError("finite numeric IK angles required")
        self._write_line(f"ik {az:.3f} {tilt:.3f} {twist:.3f}")

    def _write_line(self, command: str):
        self._require_open()
        data = memoryview((command + "\n").encode("ascii"))
        end = time.monotonic() + self.policy.io_timeout_s
        try:
            while data:
                remaining = end - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("serial write deadline")
                _, ready, _ = select.select([], [self.fd], [], remaining)
                if not ready:
                    raise TimeoutError("serial write deadline")
                try:
                    n = os.write(self.fd, data)
                except BlockingIOError:
                    continue
                if n <= 0:
                    raise ConnectionError("serial write returned no progress")
                data = data[n:]
        except BaseException:
            self.quarantined = True
            raise

    def receive(self, timeout_s: float) -> tuple[bytes, list[str]]:
        self._require_open()
        if not finite_number(timeout_s) or timeout_s < 0:
            raise ValueError("finite nonnegative receive timeout required")
        try:
            ready, _, _ = select.select([self.fd], [], [], timeout_s)
            if not ready:
                return b"", []
            try:
                data = os.read(self.fd, 4096)
            except BlockingIOError:
                return b"", []
            if not data:
                raise ConnectionError("serial disconnect/EOF")
            self.last_rx = data
            parsed = self.lines.feed(data)
            if (any(token in data or token in self.lines.buffer
                    for token in (b">>>", b"Traceback", b"MicroPython"))
                    or any(any(token in s for token in (">>>", "Traceback", "MicroPython")) for s in parsed)):
                self.quarantined = True
            return data, parsed
        except (OSError, SerialProtocolError, ConnectionError):
            self.quarantined = True
            raise
