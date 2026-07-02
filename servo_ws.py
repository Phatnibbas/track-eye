"""Laptop WebSocket host for broadcasting eye servo commands to ESP32 clients."""

from __future__ import annotations

import asyncio
import json
import threading
from typing import Any


def _clamp_angle(value: float) -> int:
    return max(0, min(180, int(round(float(value)))))


def servo_command_payload(command: Any) -> str:
    return json.dumps(
        {
            "type": "eye",
            "pan": _clamp_angle(command.pan_deg),
            "tilt": _clamp_angle(command.tilt_deg),
            "gate": str(command.gate_state),
        },
        separators=(",", ":"),
    )


class ServoWebSocketServer:
    """Small background WebSocket server; laptop is host, ESP32 is client."""

    def __init__(self, host: str = "0.0.0.0", port: int = 8765):
        self.host = host
        self.port = int(port)
        self.clients: set[Any] = set()
        self.loop: asyncio.AbstractEventLoop | None = None
        self.server = None
        self.thread: threading.Thread | None = None

    async def _handler(self, websocket):
        self.clients.add(websocket)
        try:
            await websocket.wait_closed()
        finally:
            self.clients.discard(websocket)

    async def _start_async(self):
        import websockets

        self.server = await websockets.serve(self._handler, self.host, self.port)

    def start(self) -> None:
        if self.thread is not None:
            return

        def runner() -> None:
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            self.loop.run_until_complete(self._start_async())
            self.loop.run_forever()

        self.thread = threading.Thread(target=runner, daemon=True)
        self.thread.start()

    async def _broadcast_async(self, payload: str) -> None:
        for client in list(self.clients):
            try:
                await client.send(payload)
            except Exception:
                self.clients.discard(client)

    def broadcast_command(self, command: Any) -> None:
        if self.loop is None:
            return
        payload = servo_command_payload(command)
        asyncio.run_coroutine_threadsafe(self._broadcast_async(payload), self.loop)

    def close(self) -> None:
        if self.loop is not None:
            async def shutdown() -> None:
                if self.server is not None:
                    self.server.close()
                    await self.server.wait_closed()

            future = asyncio.run_coroutine_threadsafe(shutdown(), self.loop)
            try:
                future.result(timeout=2)
            except Exception:
                pass
            self.loop.call_soon_threadsafe(self.loop.stop)
        if self.thread is not None:
            self.thread.join(timeout=2)
            self.thread = None
