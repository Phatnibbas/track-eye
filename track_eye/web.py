"""Sequenced MJPEG and software-only status HTTP endpoints."""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable
from urllib.parse import urlsplit

import cv2
import numpy as np

INDEX_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Track Eye</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#060708;color:#f4efe4;font-family:system-ui,sans-serif}
main{display:grid;grid-template-columns:1fr 320px;gap:18px;padding:18px;min-height:100vh}
.stage{border:1px solid #2d2a26;border-radius:18px;overflow:hidden;background:#000}
.stage img{width:100%;height:100%;object-fit:contain;display:block}
.hud{background:#101317;border:1px solid #302c24;border-radius:18px;padding:18px}
h1{margin:0 0 8px;font-size:24px;letter-spacing:.08em}.tag{color:#9ca3af;margin-bottom:22px}
.metric{display:flex;justify-content:space-between;padding:10px 0;border-bottom:1px solid #27231e}
.metric b{color:#ff6b4a;font-family:monospace}.status{margin-top:18px;color:#9ca3af;font-family:monospace;white-space:pre-wrap;font-size:12px}
button{width:100%;margin-top:18px;padding:11px;border:1px solid #ff6b4a;border-radius:8px;background:#211714;color:#ffb09c;font-weight:700;cursor:pointer}
button:disabled{cursor:default;opacity:.55}
</style></head>
<body><main><section class="stage"><img src="/stream.mjpg" alt="camera stream"></section>
<aside class="hud"><h1>Track Eye</h1><div class="tag">software tracker status</div>
<div class="metric"><span>face</span><b id="face">--</b></div>
<div class="metric"><span>left</span><b id="left">--</b></div>
<div class="metric"><span>right</span><b id="right">--</b></div>
<button id="baseline">Start baseline</button>
<div class="status" id="status">loading...</div></aside></main>
<script>
const statusEl=document.getElementById('status'), baselineButton=document.getElementById('baseline');
baselineButton.onclick=async()=>{baselineButton.disabled=true;baselineButton.textContent='Waiting for FACE OK...';await fetch('/start')};
async function poll(){try{const r=await fetch('/status.json',{cache:'no-store'}),s=await r.json(),b=s.baseline||{};
document.getElementById('face').textContent=s.face_detected?'OK':'NO FACE';
document.getElementById('left').textContent=s.output_left?s.output_left.x.toFixed(3)+', '+s.output_left.y.toFixed(3):'--';
document.getElementById('right').textContent=s.output_right?s.output_right.x.toFixed(3)+', '+s.output_right.y.toFixed(3):'--';
if(b.state==='idle'||b.state==='completed'||b.state==='error'){baselineButton.disabled=false;baselineButton.textContent=b.state==='completed'?'Run baseline again':'Start baseline'}
else if(b.state==='countdown'||b.state==='recording'||b.state==='ready'){baselineButton.disabled=true;baselineButton.textContent=b.state==='recording'?'Baseline recording...':'Baseline preparing...'}
statusEl.textContent=JSON.stringify({healthy:s.healthy,fps:s.fps,baseline:b},null,2)}catch(e){statusEl.textContent='status unavailable'}}
poll();setInterval(poll,1000);
</script></body></html>"""


class FrameHub:
    def __init__(self, jpeg_quality: int = 82):
        self._condition = threading.Condition()
        self._sequence = 0
        self._jpeg: bytes | None = None
        self._closed = False
        self._jpeg_quality = jpeg_quality

    def update(self, frame: np.ndarray) -> int:
        ok, encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), self._jpeg_quality])
        if not ok:
            return self._sequence
        with self._condition:
            self._jpeg = encoded.tobytes()
            self._sequence += 1
            self._condition.notify_all()
            return self._sequence

    def wait_next(self, sequence: int, timeout: float = 1.0) -> tuple[int, bytes] | None:
        with self._condition:
            self._condition.wait_for(lambda: self._closed or self._sequence > sequence, timeout)
            if self._closed or self._jpeg is None or self._sequence <= sequence:
                return None
            return self._sequence, self._jpeg

    @property
    def latest_sequence(self) -> int:
        with self._condition:
            return self._sequence

    @property
    def closed(self) -> bool:
        with self._condition:
            return self._closed

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._condition.notify_all()


class WebUIServer:
    def __init__(
        self,
        frame_hub: FrameHub,
        host: str,
        port: int,
        status_provider: Callable[[], dict],
        index_html: str = INDEX_HTML,
        start_callback: Callable[[], None] | None = None,
    ):
        self.frame_hub = frame_hub
        self.host = host
        self.port = int(port)
        self.status_provider = status_provider
        self.index_html = index_html
        self.start_callback = start_callback
        self.httpd: ThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        if self.thread is not None:
            return
        hub, provider, index_html, start_callback = self.frame_hub, self.status_provider, self.index_html, self.start_callback

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                path = urlsplit(self.path).path
                if path in ("/", "/index.html"):
                    body = index_html.encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                if path == "/start":
                    if start_callback is not None:
                        start_callback()
                    body = b"{\"started\":true}"
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                if path == "/status.json":
                    body = json.dumps(provider(), separators=(",", ":")).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                if path == "/healthz":
                    status = provider()
                    body = json.dumps(status, separators=(",", ":")).encode("utf-8")
                    self.send_response(200 if status.get("healthy") else 503)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                if path == "/stream.mjpg":
                    self.send_response(200)
                    self.send_header("Cache-Control", "no-cache, private")
                    self.send_header("Pragma", "no-cache")
                    self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
                    self.end_headers()
                    sequence = 0
                    try:
                        while not hub.closed:
                            item = hub.wait_next(sequence, timeout=1.0)
                            if item is None:
                                continue
                            sequence, jpeg = item
                            self.wfile.write(
                                b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                                + str(len(jpeg)).encode("ascii")
                                + b"\r\n\r\n"
                                + jpeg
                                + b"\r\n"
                            )
                            self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError):
                        return
                    return
                self.send_error(404)

            def log_message(self, _fmt, *_args):
                return

        self.httpd = ThreadingHTTPServer((self.host, self.port), Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, name="track-eye-http", daemon=True)
        self.thread.start()

    def close(self) -> None:
        self.frame_hub.close()
        httpd, self.httpd = self.httpd, None
        if httpd is not None:
            httpd.shutdown()
            httpd.server_close()
        thread, self.thread = self.thread, None
        if thread is not None:
            thread.join(timeout=2.0)


