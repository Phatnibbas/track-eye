"""Browser UI server for camera overlay stream and WebSocket status."""

from __future__ import annotations

import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable

import cv2
import numpy as np


class FrameHub:
    def __init__(self):
        self._lock = threading.Lock()
        self._jpeg: bytes | None = None

    def update(self, frame: np.ndarray) -> None:
        ok, encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 82])
        if not ok:
            return
        with self._lock:
            self._jpeg = bytes(encoded)

    def latest_jpeg(self) -> bytes | None:
        with self._lock:
            return self._jpeg


def render_index_html(ws_port: int) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Gaze Eye Control</title>
  <style>
    :root {{ --bg:#060708; --panel:#101317; --ink:#f4efe4; --muted:#9ca3af; --hot:#ff3b1f; --ok:#31d07d; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; min-height:100vh; background:radial-gradient(circle at 20% 0%, #24110d, var(--bg) 42%); color:var(--ink); font-family:Georgia, 'Times New Roman', serif; }}
    main {{ display:grid; grid-template-columns:1fr 320px; gap:18px; padding:18px; min-height:100vh; }}
    .stage {{ position:relative; border:1px solid #2d2a26; border-radius:18px; overflow:hidden; background:#000; box-shadow:0 30px 80px #000a; }}
    .stage img {{ width:100%; height:100%; object-fit:contain; display:block; }}
    .hud {{ background:linear-gradient(180deg,#12161bcc,#07090bcc); border:1px solid #302c24; border-radius:18px; padding:18px; box-shadow:0 20px 60px #0008; }}
    h1 {{ margin:0 0 8px; font-size:24px; letter-spacing:.08em; text-transform:uppercase; }}
    .tag {{ color:var(--muted); margin-bottom:22px; }}
    .metric {{ display:flex; justify-content:space-between; padding:12px 0; border-bottom:1px solid #27231e; font-size:18px; }}
    .metric b {{ color:var(--hot); font-family:Consolas, monospace; }}
    .status {{ margin-top:18px; padding:12px; border-radius:12px; background:#050607; color:var(--muted); font-family:Consolas, monospace; }}
    .live {{ color:var(--ok); }}
    @media (max-width: 900px) {{ main {{ grid-template-columns:1fr; }} }}
  </style>
</head>
<body>
  <main>
    <section class="stage"><img src="/stream.mjpg" alt="camera stream"></section>
    <aside class="hud">
      <h1>Gaze Eye Control</h1>
      <div class="tag">camera + servo status over WebSocket</div>
      <div class="metric"><span>pan</span><b id="pan">--</b></div>
      <div class="metric"><span>tilt</span><b id="tilt">--</b></div>
      <div class="metric"><span>gate</span><b id="gate">--</b></div>
      <div class="metric"><span>clients</span><b id="clients">--</b></div>
      <div class="status" id="status">connecting...</div>
    </aside>
  </main>
  <script>
    const statusEl = document.getElementById('status');
    const ws = new WebSocket('ws://' + location.hostname + ':{ws_port}');
    ws.onopen = () => {{ statusEl.textContent = 'websocket live'; statusEl.className='status live'; }};
    ws.onclose = () => {{ statusEl.textContent = 'websocket closed'; statusEl.className='status'; }};
    ws.onmessage = (ev) => {{
      const msg = JSON.parse(ev.data);
      if (msg.type === 'eye') {{
        document.getElementById('pan').textContent = msg.pan;
        document.getElementById('tilt').textContent = msg.tilt;
        document.getElementById('gate').textContent = msg.gate;
      }}
      if (msg.clients !== undefined) document.getElementById('clients').textContent = msg.clients;
    }};
  </script>
</body>
</html>"""


class WebUIServer:
    def __init__(self, frame_hub: FrameHub, host: str, port: int, ws_port: int):
        self.frame_hub = frame_hub
        self.host = host
        self.port = int(port)
        self.ws_port = int(ws_port)
        self.httpd: ThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        if self.thread is not None:
            return
        hub = self.frame_hub
        ws_port = self.ws_port

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path in ("/", "/index.html"):
                    body = render_index_html(ws_port).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                if self.path == "/stream.mjpg":
                    self.send_response(200)
                    self.send_header("Age", "0")
                    self.send_header("Cache-Control", "no-cache, private")
                    self.send_header("Pragma", "no-cache")
                    self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
                    self.end_headers()
                    while True:
                        jpeg = hub.latest_jpeg()
                        if jpeg is None:
                            time.sleep(0.03)
                            continue
                        self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n")
                    return
                self.send_error(404)

            def log_message(self, fmt, *args):
                return

        self.httpd = ThreadingHTTPServer((self.host, self.port), Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def close(self) -> None:
        if self.httpd is not None:
            self.httpd.shutdown()
