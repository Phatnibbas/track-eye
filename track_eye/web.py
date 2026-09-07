"""Sequenced MJPEG and software-only status HTTP endpoints."""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable
from urllib.parse import parse_qs, urlsplit

import cv2
import numpy as np

INDEX_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Track Eye Output Tuner</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#060708;color:#f4efe4;font-family:system-ui,sans-serif}
main{display:grid;grid-template-columns:minmax(0,1fr) 360px;gap:18px;padding:18px;min-height:100vh}
.stage{border:1px solid #2d2a26;border-radius:18px;overflow:hidden;background:#000;min-height:360px}
.stage img{width:100%;height:100%;object-fit:contain;display:block}
.hud{background:#101317;border:1px solid #302c24;border-radius:18px;padding:18px;overflow:auto}
h1{margin:0 0 4px;font-size:24px;letter-spacing:.08em}.tag{color:#9ca3af;margin-bottom:16px}
h2{font-size:13px;letter-spacing:.12em;color:#d8cab8;margin:22px 0 8px}
.metric{display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid #27231e}
.metric b,.value{color:#ff8062;font-family:monospace}
.control{display:grid;grid-template-columns:64px 1fr 48px;gap:8px;align-items:center;margin:10px 0}
input[type=range]{width:100%;accent-color:#ff6b4a}
.actions{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:14px}
button{padding:10px;border:1px solid #ff6b4a;border-radius:8px;background:#211714;color:#ffb09c;font-weight:700;cursor:pointer}
button.secondary{border-color:#4a4f57;background:#171a1f;color:#c4cad2}button:disabled{cursor:default;opacity:.5}
#baseline{width:100%;margin-top:10px}.state{margin-top:10px;color:#aeb5bf;font:12px/1.4 monospace}
.dirty{color:#ffd166}.saved{color:#77d49b}
@media(max-width:900px){main{grid-template-columns:1fr}.stage{min-height:52vh}}
</style></head>
<body><main><section class="stage"><img id="camera" alt="camera stream"></section>
<aside class="hud"><h1>Track Eye</h1><div class="tag">natural-motion output tuner</div>
<div class="metric"><span>face</span><b id="face">--</b></div>
<div class="metric"><span>left eye</span><b id="left-eye">--</b></div>
<div class="metric"><span>right eye</span><b id="right-eye">--</b></div>
<h2>DIRECTIONAL GAIN</h2>
<label class="control"><span>Left</span><input data-gain="left" type="range" min=".1" max="10" step=".05"><output></output></label>
<label class="control"><span>Right</span><input data-gain="right" type="range" min=".1" max="10" step=".05"><output></output></label>
<label class="control"><span>Up</span><input data-gain="up" type="range" min=".1" max="10" step=".05"><output></output></label>
<label class="control"><span>Down</span><input data-gain="down" type="range" min=".1" max="10" step=".05"><output></output></label>
<label class="control"><span>Limit</span><input data-gain="soft_limit" type="range" min="1" max="3" step=".05"><output></output></label>
<div class="actions"><button id="neutral">Set neutral</button><button id="save">Save</button></div>
<div class="actions"><button class="secondary" id="reset">Reset defaults</button><span id="save-state" class="state"></span></div>
<div id="neutral-state" class="state">Neutral: not set</div>
<h2>MEASUREMENT</h2><button class="secondary" id="baseline">Start baseline</button>
<div id="baseline-state" class="state">Baseline idle</div>
</aside></main>
<script>
const camera=document.getElementById('camera'),gainInputs=[...document.querySelectorAll('[data-gain]')];
const face=document.getElementById('face'),leftEye=document.getElementById('left-eye'),rightEye=document.getElementById('right-eye');
const neutral=document.getElementById('neutral'),save=document.getElementById('save'),reset=document.getElementById('reset'),baseline=document.getElementById('baseline');
const neutralState=document.getElementById('neutral-state'),saveState=document.getElementById('save-state'),baselineState=document.getElementById('baseline-state');
let initialized=false,timer=null;
async function post(path,body={}){const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const value=await response.json();if(!response.ok)throw new Error(value.error||response.statusText);return value}
function values(){return Object.fromEntries(gainInputs.map(input=>[input.dataset.gain,Number(input.value)]))}
function showValue(input){input.nextElementSibling.textContent=Number(input.value).toFixed(2)}
gainInputs.forEach(input=>{input.oninput=()=>{showValue(input);clearTimeout(timer);timer=setTimeout(()=>post('/output/gain',values()).catch(showError),80)}})
function showError(error){saveState.textContent=error.message;saveState.className='state dirty'}
neutral.onclick=()=>post('/output/neutral').catch(showError);
save.onclick=()=>post('/output/save').catch(showError);
reset.onclick=async()=>{try{await post('/output/reset');initialized=false;await poll()}catch(error){showError(error)}};
baseline.onclick=()=>post('/baseline/start').catch(showError);
async function poll(){try{
 const s=await (await fetch('/status.json',{cache:'no-store'})).json(),t=s.output_tuning,b=s.baseline||{},g=t.calibration.gain;
 face.textContent=s.face_detected?'OK':'NO FACE';
 leftEye.textContent=s.output_left?s.output_left.x.toFixed(3)+', '+s.output_left.y.toFixed(3):'--';
 rightEye.textContent=s.output_right?s.output_right.x.toFixed(3)+', '+s.output_right.y.toFixed(3):'--';
 if(!initialized){gainInputs.forEach(input=>{input.value=g[input.dataset.gain];showValue(input)});initialized=true}
 saveState.textContent=t.dirty?'Unsaved':'Saved';saveState.className=t.dirty?'state dirty':'state saved';
 const neutralCount=t.calibration.neutrals.length;
 neutralState.textContent=t.neutral_state==='collecting'?'Neutral: hold still '+(t.neutral_remaining_seconds||0).toFixed(1)+'s':t.neutral_state==='waiting_for_face'?'Neutral: waiting for FACE OK':'Neutral: '+(neutralCount?'set':'not set');
 neutral.disabled=t.neutral_state!=='idle'||b.state==='countdown'||b.state==='recording';
 baseline.disabled=!['idle','completed','error'].includes(b.state);
 baseline.textContent=b.state==='completed'?'Run baseline again':b.state==='recording'?'Baseline recording...':'Start baseline';
 baselineState.textContent=b.state==='countdown'||b.state==='recording'?`${b.phase_index}/${b.phase_total} ${b.instruction} ${Number(b.remaining_seconds||0).toFixed(1)}s`:`Baseline ${b.state}`;
 if(t.load_error)showError(new Error('Config: '+t.load_error));
 }catch(error){showError(error)}}
poll();setInterval(poll,250);
let frameSequence=0,frameUrl=null;
async function nextFrame(){try{
 const response=await fetch('/frame.jpg?after='+frameSequence,{cache:'no-store'});
 if(response.status===204){requestAnimationFrame(nextFrame);return}
 frameSequence=Number(response.headers.get('X-Frame-Sequence')||frameSequence);
 const nextUrl=URL.createObjectURL(await response.blob());
 await new Promise((resolve,reject)=>{camera.onload=resolve;camera.onerror=reject;camera.src=nextUrl});
 if(frameUrl)URL.revokeObjectURL(frameUrl);frameUrl=nextUrl;
 requestAnimationFrame(nextFrame);
 }catch(_error){setTimeout(nextFrame,250)}}
nextFrame();
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

    def wait_latest(self, sequence: int, timeout: float = 1.0) -> tuple[int, bytes] | None:
        return self.wait_next(sequence, timeout)

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
        action_callbacks: dict[str, Callable[[dict], dict]] | None = None,
    ):
        self.frame_hub = frame_hub
        self.host = host
        self.port = int(port)
        self.status_provider = status_provider
        self.index_html = index_html
        self.start_callback = start_callback
        self.action_callbacks = action_callbacks or {}
        self.httpd: ThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        if self.thread is not None:
            return
        hub, provider, index_html, start_callback, action_callbacks = (
            self.frame_hub,
            self.status_provider,
            self.index_html,
            self.start_callback,
            self.action_callbacks,
        )

        class Handler(BaseHTTPRequestHandler):
            def send_json(self, status: int, value: dict) -> None:
                body = json.dumps(value, separators=(",", ":")).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):  # noqa: N802
                path = urlsplit(self.path).path
                callback = action_callbacks.get(path)
                if callback is None:
                    self.send_error(404)
                    return
                try:
                    content_length = int(self.headers.get("Content-Length", "0"))
                    if content_length > 8192:
                        raise ValueError("request body too large")
                    body = json.loads(self.rfile.read(content_length)) if content_length else {}
                    if not isinstance(body, dict):
                        raise ValueError("JSON object required")
                    self.send_json(200, callback(body))
                except (ValueError, json.JSONDecodeError) as exc:
                    self.send_json(400, {"error": str(exc)})
                except OSError as exc:
                    self.send_json(500, {"error": str(exc)})

            def do_GET(self):  # noqa: N802
                request = urlsplit(self.path)
                path = request.path
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
                if path == "/frame.jpg":
                    try:
                        sequence = int(parse_qs(request.query).get("after", ["0"])[0])
                    except ValueError:
                        self.send_error(400, "invalid frame sequence")
                        return
                    item = hub.wait_latest(sequence, timeout=0.5)
                    if item is None:
                        self.send_response(204)
                        self.send_header("Cache-Control", "no-store")
                        self.end_headers()
                        return
                    sequence, jpeg = item
                    self.send_response(200)
                    self.send_header("Content-Type", "image/jpeg")
                    self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
                    self.send_header("X-Frame-Sequence", str(sequence))
                    self.send_header("Content-Length", str(len(jpeg)))
                    self.end_headers()
                    self.wfile.write(jpeg)
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


