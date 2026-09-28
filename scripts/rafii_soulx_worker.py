"""Local/SSH-tunneled SoulX FlashHead Lite renderer for Rafii Live.

Start from a CUDA Python 3.10 environment with the upstream SoulX requirements plus
fastapi and uvicorn. This process does no speech generation or conversation work.
"""
from __future__ import annotations

import asyncio
import base64
from collections import deque
from dataclasses import dataclass, field
import os
from pathlib import Path
import struct
import sys
import threading
import time
from uuid import uuid4

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware


SAMPLE_RATE = 16000
MAX_PACKET_BYTES = 64004  # two seconds of PCM16 at 16 kHz, plus generation header
MAX_PENDING_WINDOWS = 3


@dataclass
class AvatarCall:
    id: str
    generation: int = 0
    sequence: int = 0
    audio: bytearray = field(default_factory=bytearray)
    wake: asyncio.Event = field(default_factory=asyncio.Event)
    closed: bool = False
    first_audio_at: float | None = None
    first_frame_ms: float | None = None
    dropped_frames: int = 0
    dropped_audio_samples: int = 0
    needs_reset: bool = False
    accepted: bool = False
    history: deque[float] = field(default_factory=lambda: deque(maxlen=8 * SAMPLE_RATE))
    history_lock: threading.Lock = field(default_factory=threading.Lock)

    def interrupt(self, generation: int) -> None:
        if generation <= self.generation:
            return
        self.generation = generation
        self.audio.clear()
        with self.history_lock:
            self.history.clear()
        self.first_audio_at = None
        self.first_frame_ms = None
        self.needs_reset = True
        self.accepted = False
        self.wake.set()

    def append(self, packet: bytes, window_bytes: int) -> bool:
        if len(packet) < 6 or len(packet) > MAX_PACKET_BYTES or len(packet) % 2:
            return False
        generation = struct.unpack_from("<I", packet)[0]
        if generation != self.generation or self.closed:
            return False
        if self.first_audio_at is None:
            self.first_audio_at = time.monotonic()
        self.audio.extend(packet[4:])
        cap = window_bytes * MAX_PENDING_WINDOWS
        if len(self.audio) > cap:
            remove = len(self.audio) - cap
            remove += remove % 2
            del self.audio[:remove]
            self.dropped_audio_samples += remove // 2
        self.wake.set()
        return True

    def next_window(self, window_bytes: int) -> bytes | None:
        if len(self.audio) < window_bytes:
            return None
        window = bytes(self.audio[:window_bytes])
        del self.audio[:window_bytes]
        return window


class SoulXEngine:
    """One warm mutable SoulX pipeline. Sessions are isolated and admitted one at a time."""

    def __init__(self) -> None:
        repo = Path(os.environ["SOULX_REPO_PATH"]).expanduser().resolve()
        ckpt = Path(os.environ["SOULX_CHECKPOINT_DIR"]).expanduser().resolve()
        wav2vec = Path(os.environ["SOULX_WAV2VEC_DIR"]).expanduser().resolve()
        self.reference = Path(os.environ["RAFFII_AVATAR_REFERENCE"]).expanduser().resolve()
        for path in (repo, ckpt, wav2vec, self.reference):
            if not path.exists():
                raise RuntimeError(f"SoulX input is missing: {path}")
        if not (repo / "flash_head" / "inference.py").exists():
            raise RuntimeError("SOULX_REPO_PATH is not Soul-AILab/SoulX-FlashHead")
        import torch
        if not torch.cuda.is_available():
            raise RuntimeError("SoulX FlashHead Lite requires NVIDIA CUDA; no real inference was started")
        os.chdir(repo)  # upstream inference.py reads flash_head/configs relative to cwd
        sys.path.insert(0, str(repo))
        from flash_head.inference import get_audio_embedding, get_base_data, get_infer_params, get_pipeline, run_pipeline

        self.get_audio_embedding = get_audio_embedding
        self.get_base_data = get_base_data
        self.get_infer_params = get_infer_params
        self.run_pipeline = run_pipeline
        self.pipeline = get_pipeline(world_size=1, ckpt_dir=str(ckpt), model_type="lite", wav2vec_dir=str(wav2vec))
        params = get_infer_params()
        if params["sample_rate"] != SAMPLE_RATE:
            raise RuntimeError("SoulX sample rate changed; update the browser resampler and protocol")
        self.params = params
        self.window_samples = (params["frame_num"] - params["motion_frames_num"]) * SAMPLE_RATE // params["tgt_fps"]
        self.window_bytes = self.window_samples * 2
        self.history_samples = params["cached_audio_duration"] * SAMPLE_RATE
        self.audio_end_idx = params["cached_audio_duration"] * params["tgt_fps"]
        self.audio_start_idx = self.audio_end_idx - params["frame_num"]
        self.lock = threading.Lock()
        self.session_count = 0
        self.reset()  # warm the conditioning image before the first Live conversation

    def reset(self) -> None:
        # prepare_params owns conditioning and motion state; raccoon face crop is deliberately disabled.
        with self.lock:
            self.get_base_data(self.pipeline, str(self.reference), base_seed=9999, use_face_crop=False)

    def infer(self, call: AvatarCall, window: bytes, reset: bool, generation: int):
        import numpy as np
        import cv2
        if generation != call.generation or call.closed:
            return []
        with call.history_lock:
            if generation != call.generation or call.closed:
                return []
            values = np.frombuffer(window, dtype="<i2").astype(np.float32) / 32768.0
            call.history.extend(values.tolist())
            history = np.zeros(self.history_samples, dtype=np.float32)
            recent = np.fromiter(call.history, dtype=np.float32)
            history[-len(recent):] = recent
        with self.lock:
            if reset:
                self.get_base_data(self.pipeline, str(self.reference), base_seed=9999, use_face_crop=False)
            embedding = self.get_audio_embedding(self.pipeline, history, self.audio_start_idx, self.audio_end_idx)
            video = self.run_pipeline(self.pipeline, embedding)[self.params["motion_frames_num"]:]
            frames = video.cpu().numpy()
        encoded: list[str] = []
        for rgb in frames:
            ok, jpeg = cv2.imencode(".jpg", cv2.cvtColor(rgb.astype(np.uint8), cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 72])
            if ok:
                encoded.append(base64.b64encode(jpeg.tobytes()).decode("ascii"))
        return encoded


def create_app(engine: SoulXEngine) -> FastAPI:
    app = FastAPI(title="Rafii SoulX avatar worker")
    allowed = [item.strip() for item in os.environ.get("SOULX_ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",") if item.strip()]
    app.add_middleware(CORSMiddleware, allow_origins=allowed, allow_methods=["GET", "POST", "DELETE"], allow_headers=["content-type"])
    calls: dict[str, AvatarCall] = {}
    admission = asyncio.Lock()

    @app.get("/health")
    async def health():
        return {"ready": True, "model": "soulx-flashhead-lite", "sampleRate": SAMPLE_RATE, "windowSamples": engine.window_samples, "activeSessions": len(calls)}

    @app.post("/session")
    async def create_session():
        async with admission:
            if calls:
                raise HTTPException(status_code=503, detail="Phase 1 worker supports one active CUDA session")
            call = AvatarCall(id=str(uuid4()), history=deque(maxlen=engine.history_samples))
            call.needs_reset = engine.session_count > 0
            engine.session_count += 1
            calls[call.id] = call
        return {"id": call.id, "sampleRate": SAMPLE_RATE, "windowSamples": engine.window_samples}

    @app.delete("/session/{session_id}")
    async def delete_session(session_id: str):
        call = calls.pop(session_id, None)
        if call:
            call.closed = True
            call.wake.set()
        return {"closed": bool(call)}

    @app.websocket("/session/{session_id}/stream")
    async def stream(websocket: WebSocket, session_id: str):
        call = calls.get(session_id)
        if not call or websocket.headers.get("origin") not in allowed:
            await websocket.close(code=1008)
            return
        await websocket.accept()

        async def render_loop():
            while not call.closed:
                window = call.next_window(engine.window_bytes)
                if window is None:
                    call.wake.clear()
                    await call.wake.wait()
                    continue
                generation = call.generation
                reset = call.needs_reset
                call.needs_reset = False
                try:
                    frames = await asyncio.to_thread(engine.infer, call, window, reset, generation)
                except Exception as error:
                    await websocket.send_json({"type": "error", "message": f"SoulX inference failed: {type(error).__name__}"})
                    break
                if call.closed or generation != call.generation:
                    call.dropped_frames += len(frames)
                    continue
                if call.first_frame_ms is None and call.first_audio_at is not None:
                    call.first_frame_ms = (time.monotonic() - call.first_audio_at) * 1000
                await websocket.send_json({"type": "metrics", "generation": generation, "queueDepth": len(call.audio) // engine.window_bytes,
                                           "firstFrameMs": call.first_frame_ms, "droppedFrames": call.dropped_frames,
                                           "droppedAudioSamples": call.dropped_audio_samples})
                for jpeg in frames:
                    if call.closed or generation != call.generation:
                        call.dropped_frames += 1
                        break
                    call.sequence += 1
                    await websocket.send_json({"type": "frame", "generation": generation, "sequence": call.sequence, "jpeg": jpeg})
                    await asyncio.sleep(1 / engine.params["tgt_fps"])

        task = asyncio.create_task(render_loop())
        try:
            while not call.closed:
                message = await websocket.receive()
                if message["type"] == "websocket.disconnect":
                    break
                if message.get("bytes") is not None:
                    if call.append(message["bytes"], engine.window_bytes) and not call.accepted:
                        call.accepted = True
                        await websocket.send_json({"type": "audio_accepted", "generation": call.generation})
                elif message.get("text"):
                    import json
                    control = json.loads(message["text"])
                    if control.get("type") == "interrupt" and isinstance(control.get("generation"), int):
                        call.interrupt(control["generation"])
                        await websocket.send_json({"type": "interrupted", "generation": call.generation})
        except (WebSocketDisconnect, ValueError):
            pass
        finally:
            call.closed = True
            call.wake.set()
            calls.pop(session_id, None)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    return app


if __name__ == "__main__":
    import uvicorn
    worker = SoulXEngine()  # fail fast on missing weights/CUDA; no fake success path
    uvicorn.run(create_app(worker), host=os.environ.get("SOULX_BIND", "127.0.0.1"), port=int(os.environ.get("SOULX_PORT", "8765")))
