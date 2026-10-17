"""Bounded, non-motion Delta master probe using Linux's standard library.

Does not toggle DTR/RTS, send Ctrl-C/Ctrl-D, home, clear, or move commands.
Opening an already-running master does not guarantee absence of firmware-owned
autonomous recovery. Keep the mechanism clear even during diagnostics.
"""

from __future__ import annotations

import argparse
import json
import os
import select
import time
import math


def probe(device: str, listen_s: float = 3.0, reply_s: float = 3.0,
          commands: tuple[str, ...] = ("status", "cfg", "ik 0 0 0"),
          restore_settings: bool = False, *, baud: int, max_line_bytes: int) -> dict:
    import fcntl
    import termios

    if (type(baud) is not int or type(max_line_bytes) is not int or max_line_bytes <= 0
            or any(type(v) not in (int, float) or not math.isfinite(v) or v <= 0 for v in (listen_s, reply_s))):
        raise ValueError("positive finite timings, integer baud and line bound required")
    speed = getattr(termios, f"B{baud}", None)
    if speed is None:
        raise ValueError("unsupported baud")
    fd = None
    original = None
    events = []
    started = time.monotonic()
    buffer = bytearray()
    error = None

    def collect(seconds: float) -> None:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            ready, _, _ = select.select([fd], [], [], min(0.2, max(0, deadline - time.monotonic())))
            if not ready:
                continue
            data = os.read(fd, 4096)
            if not data:
                raise ConnectionError("serial device closed/disconnected")
            buffer.extend(data)
            events.append({"t_s": round(time.monotonic() - started, 3),
                           "rx_hex": data.hex()})
            while b"\n" in buffer:
                line, _, tail = buffer.partition(b"\n")
                buffer[:] = tail
                events.append({"t_s": round(time.monotonic() - started, 3),
                               "rx": line.decode("utf-8", "replace").rstrip("\r")})
            if len(buffer) > max_line_bytes:
                raise ValueError("unterminated serial line exceeds configured byte bound")

    try:
        fd = os.open(device, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        # TIOCEXCL prevents new opens, flock cooperates with the new transport.
        # Neither can prove an unrelated pre-existing owner does not exist.
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.ioctl(fd, termios.TIOCEXCL)
        original = termios.tcgetattr(fd)
        attrs = termios.tcgetattr(fd)
        attrs[0] = 0
        attrs[1] = 0
        attrs[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
        attrs[3] = 0
        attrs[4] = attrs[5] = speed
        attrs[6][termios.VMIN] = 0
        attrs[6][termios.VTIME] = 0
        termios.tcsetattr(fd, termios.TCSANOW, attrs)
        collect(listen_s)
        for command in commands:
            if (any("Traceback" in event.get("rx", "") or ">>>" in event.get("rx", "")
                    for event in events) or b">>>" in buffer) and commands == ("status", "cfg", "ik 0 0 0"):
                events.append({"abort": "master traceback/REPL; no further protocol commands"})
                break
            events.append({"t_s": round(time.monotonic() - started, 3), "tx": command})
            payload = (command + "\n").encode("ascii")
            if os.write(fd, payload) != len(payload):
                raise IOError("partial command write")
            collect(reply_s)
        if buffer:
            events.append({"rx_partial": buffer.decode("utf-8", "replace")})
    except (OSError, ValueError) as exc:
        error = str(exc)
        events.append({"error": error, "rx_partial_hex": buffer.hex()})
    finally:
        if original is not None and restore_settings:
            try:
                termios.tcsetattr(fd, termios.TCSANOW, original)
            except OSError as exc:
                events.append({"restore_error": str(exc)})
        if fd is not None:
            os.close(fd)
    return {"device": device, "baud": baud, "motion_commands_sent": False,
            "restore_settings": restore_settings, "error": error,
            "duration_s": round(time.monotonic() - started, 3), "events": events}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--baud", type=int, required=True)
    parser.add_argument("--max-line-bytes", type=int, required=True)
    parser.add_argument("--listen-seconds", type=float, required=True)
    parser.add_argument("--reply-seconds", type=float, required=True)
    parser.add_argument("--restore-serial-settings", action="store_true",
                        help="explicit experiment only; may restore an incompatible prior baud")
    parser.add_argument("--listen-only", action="store_true",
                        help="capture incoming bytes without transmitting any command")
    parser.add_argument("--prompt-check", action="store_true",
                        help="send only an empty newline to solicit a possible REPL prompt")
    args = parser.parse_args()
    if args.listen_only and args.prompt_check:
        parser.error("choose listen-only or prompt-check, not both")
    result = probe(args.device, args.listen_seconds, args.reply_seconds,
                   commands=() if args.listen_only else (("",) if args.prompt_check else ("status", "cfg", "ik 0 0 0")),
                   restore_settings=args.restore_serial_settings,
                   baud=args.baud, max_line_bytes=args.max_line_bytes)
    with open(args.out, "x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, ensure_ascii=False)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return int(result["error"] is not None)


if __name__ == "__main__":
    raise SystemExit(main())
