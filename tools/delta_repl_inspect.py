"""Read selected non-secret board files only after an observed master crash.

Requires explicit --confirmed-repl. No reset, interrupt, firmware write or motion.
"""
import argparse
import json

from delta_serial_probe import probe


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--confirmed-repl", action="store_true", required=True)
    parser.add_argument("--reply-seconds", type=float, required=True)
    parser.add_argument("--baud", type=int, required=True)
    parser.add_argument("--max-line-bytes", type=int, required=True)
    parser.add_argument("--chunk-bytes", type=int, required=True)
    parser.add_argument("--listen-seconds", type=float, required=True)
    args = parser.parse_args()
    if args.chunk_bytes <= 0:
        parser.error("positive chunk size required")
    # Fixed allowlist: never read secrets/config arbitrary files via this tool.
    # Stream small chunks: base64 of the whole master exhausts this board's heap.
    code = "import os, ubinascii, gc\nprint('AUDIT_OS', os.uname())\nprint('AUDIT_FILES', os.listdir())\nfor p in ('main.py', 'delta_proto.py', 'spm_ik.py', 'neutral.txt'):\n if p in os.listdir():\n  print('AUDIT_BEGIN', p)\n  f=open(p, 'rb')\n  while True:\n   b=f.read(192)\n   if not b: break\n   print('AUDIT_CHUNK', ubinascii.b2a_base64(b).decode().strip())\n  f.close()\n  print('AUDIT_END', p)\n  gc.collect()\n"
    code = code.replace("f.read(192)", f"f.read({args.chunk_bytes})")
    command = "exec(" + repr(code) + ")"
    result = probe(args.device, listen_s=args.listen_seconds, reply_s=args.reply_seconds,
                   commands=(command,), restore_settings=False,
                   baud=args.baud, max_line_bytes=args.max_line_bytes)
    with open(args.out, "x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
