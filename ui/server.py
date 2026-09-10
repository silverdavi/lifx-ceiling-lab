#!/usr/bin/env python3
"""Local control widget for the Ceiling: FastAPI + one static page.

    pip install -e ".[ui]"
    python3 ui/server.py            # http://127.0.0.1:8632

Binds to 127.0.0.1 only — this is a LAN remote for one fixture, not a
platform. There is no auth because it never leaves your machine; do not bind
it to 0.0.0.0 without adding some.

Modes:

- **firefly** — streams the baked physics animation at 20 Hz. Brightness
  1–100 scales every pixel (it can be genuinely dim); "single" colour mode
  keeps the per-pixel brightness envelope of the animation but replaces the
  hue with one swatch.
- **image** — upload any image or GIF; stills are pushed once, GIFs loop.
- **uplight** — downlight fully off, the zone-63 ring at the brightness
  slider (default idea: a very dim night light).
- **release** — power off and stop sending, so the LIFX app has uncontested
  control again.
"""

from __future__ import annotations

import asyncio
import io
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from fastapi import FastAPI, File, HTTPException, UploadFile  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from lifx_ceiling import (  # noqa: E402
    HSBK,
    CeilingClient,
    connect,
    hex_to_hsbk,
    load_frames,
)
from lifx_ceiling.transform import UPLIGHT_INDEX  # noqa: E402

FIREFLY_FRAMES = REPO / "examples" / "dynamic" / "frames" / "firefly.json"
WEB = Path(__file__).parent / "web"

app = FastAPI(title="lifx-ceiling-lab widget")


class Controls(BaseModel):
    mode: str = Field(pattern="^(firefly|uplight|release|image)$")
    brightness: int = Field(default=60, ge=1, le=100)
    color_mode: str = Field(default="changing", pattern="^(changing|single)$")
    color: str = Field(default="#ffd23f", pattern="^#?[0-9a-fA-F]{6}$")


class Controller:
    def __init__(self) -> None:
        self.client: CeilingClient | None = None
        self.mode = "released"
        self.brightness = 60
        self.color_mode = "changing"
        self.color = "#ffd23f"
        self.firefly = [
            ([hex_to_hsbk(pixel) for pixel in pixels], duration_ms)
            for pixels, duration_ms in load_frames(FIREFLY_FRAMES)
        ]
        self.uploaded: list[tuple[list[HSBK], int]] | None = None
        self.error: str | None = None
        self._wake = asyncio.Event()

    def ensure_client(self) -> CeilingClient:
        if self.client is None:
            self.client = connect()
        return self.client

    def _effective(self, colors: list[HSBK]) -> list[HSBK]:
        factor = self.brightness / 100
        if self.color_mode == "single":
            hue, saturation, _b, kelvin = hex_to_hsbk(self.color)
            return [
                (hue, saturation, int(b * factor), kelvin) for _h, _s, b, _k in colors
            ]
        return [(h, s, int(b * factor), k) for h, s, b, k in colors]

    async def run(self) -> None:
        """Streaming loop: sends frames while an animated mode is active."""
        index = 0
        next_at = time.monotonic()
        while True:
            frames = (
                self.firefly
                if self.mode == "firefly"
                else self.uploaded if self.mode == "image" else None
            )
            if not frames or (self.mode == "image" and len(frames) == 1):
                self._wake.clear()
                try:
                    await asyncio.wait_for(self._wake.wait(), timeout=1.0)
                except asyncio.TimeoutError:
                    pass
                index = 0
                next_at = time.monotonic()
                continue
            colors, duration_ms = frames[index % len(frames)]
            try:
                client = self.ensure_client()
                await asyncio.to_thread(client.set64, self._effective(colors))
                self.error = None
            except (OSError, TimeoutError) as error:
                self.error = str(error)
                await asyncio.sleep(2.0)
                continue
            index += 1
            next_at += duration_ms / 1000
            delay = next_at - time.monotonic()
            if delay < -1.0:  # fell far behind (sleep/suspend); resync
                next_at = time.monotonic()
            elif delay > 0:
                await asyncio.sleep(delay)

    def apply(self, controls: Controls) -> None:
        self.brightness = controls.brightness
        self.color_mode = controls.color_mode
        self.color = f"#{controls.color.removeprefix('#').lower()}"
        client = self.ensure_client()
        client.save_state()  # snapshot once, so a later restore is possible

        if controls.mode == "release":
            self.mode = "released"
            client.set_light_power(0, duration_ms=400)
            return

        if controls.mode == "uplight":
            self.mode = "uplight"
            level = int(round(0xFFFF * self.brightness / 100))
            colors: list[HSBK] = [(0, 0, 0, 3500)] * 64
            colors[UPLIGHT_INDEX] = (0, 0, level, 3500)
            client.set_light_power(0xFFFF, duration_ms=150)
            client.set64(colors, duration_ms=300, rotate=0, mask_uplight=False)
            return

        if controls.mode == "image":
            if not self.uploaded:
                raise HTTPException(400, "upload an image first")
            self.mode = "image"
            client.set_light_power(0xFFFF, duration_ms=150)
            if len(self.uploaded) == 1:
                client.set64(self._effective(self.uploaded[0][0]), duration_ms=300)
            self._wake.set()
            return

        self.mode = "firefly"
        client.set_light_power(0xFFFF, duration_ms=150)
        self._wake.set()


controller = Controller()


@app.on_event("startup")
async def start_loop() -> None:
    asyncio.create_task(controller.run())


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(WEB / "index.html")


@app.get("/api/status")
async def status() -> JSONResponse:
    return JSONResponse(
        {
            "mode": controller.mode,
            "brightness": controller.brightness,
            "colorMode": controller.color_mode,
            "color": controller.color,
            "uploadedFrames": len(controller.uploaded or []),
            "fireflyFrames": len(controller.firefly),
            "connected": controller.client is not None,
            "error": controller.error,
        }
    )


@app.post("/api/controls")
async def set_controls(controls: Controls) -> JSONResponse:
    try:
        await asyncio.to_thread(controller.apply, controls)
    except TimeoutError as error:
        raise HTTPException(status_code=502, detail=str(error))
    return await status()


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)) -> JSONResponse:
    from PIL import Image

    from lifx_ceiling.images import image_to_pixels

    data = await file.read()
    if len(data) > 20 * 1024 * 1024:
        raise HTTPException(413, "file too large")
    try:
        image = Image.open(io.BytesIO(data))
    except Exception:
        raise HTTPException(400, "not an image")

    frames: list[tuple[list[HSBK], int]] = []
    frame_count = min(getattr(image, "n_frames", 1), 400)
    previous: list[str] | None = None
    for frame_index in range(frame_count):
        image.seek(frame_index)
        pixels = image_to_pixels(image)
        if pixels == previous:
            continue
        duration_ms = max(50, int(image.info.get("duration") or 100))
        frames.append(([hex_to_hsbk(pixel) for pixel in pixels], duration_ms))
        previous = pixels
    if not frames:
        raise HTTPException(400, "no frames decoded")
    controller.uploaded = frames
    return JSONResponse({"frames": len(frames)})


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8632, log_level="warning")


if __name__ == "__main__":
    print("widget at http://127.0.0.1:8632")
    main()
