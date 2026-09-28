"""HTTP/WebSocket protocol verification with a fake inference engine; no CUDA or provider calls."""
import importlib.util
from unittest.mock import patch
from pathlib import Path
import struct
import time
import unittest

from fastapi.testclient import TestClient


spec = importlib.util.spec_from_file_location("rafii_soulx_worker", Path(__file__).resolve().parents[1] / "scripts/rafii_soulx_worker.py")
worker = importlib.util.module_from_spec(spec)
import sys
sys.modules[spec.name] = worker
spec.loader.exec_module(worker)


class FakeEngine:
    window_samples = 160
    window_bytes = 320
    history_samples = 1280
    params = {"tgt_fps": 25}
    session_count = 0

    def __init__(self):
        self.resets = 0
        self.audio = []

    def reset(self):
        self.resets += 1

    def infer(self, call, window, reset, generation):
        self.audio.append((call.id, generation, window))
        if reset:
            self.reset()
        time.sleep(0.02)
        return ["/9j/fake-jpeg"]


class WorkerProtocolTests(unittest.TestCase):
    def test_health_reports_real_resource_fields(self):
        data = TestClient(worker.create_app(FakeEngine())).get('/health').json()
        self.assertTrue(data['ready'])
        self.assertGreaterEqual(data['cpuUserSeconds'], 0)
        self.assertGreaterEqual(data['cpuSystemSeconds'], 0)
        self.assertIn('processRssBytes', data)
        self.assertIn('gpuUtilPercent', data)

    def test_unattached_session_expires_and_releases_slot(self):
        with patch.dict('os.environ', {'SOULX_SESSION_LEASE_SECONDS': '0.02'}):
            with TestClient(worker.create_app(FakeEngine())) as client:
                self.assertEqual(client.post('/session').status_code, 200)
                time.sleep(0.06)
                self.assertEqual(client.get('/ready').json()['available'], True)

    def test_session_audio_frame_interrupt_and_close(self):
        engine = FakeEngine()
        client = TestClient(worker.create_app(engine))
        created = client.post("/session")
        self.assertEqual(created.status_code, 200)
        session_id = created.json()["id"]
        self.assertEqual(client.post("/session").status_code, 503)
        with client.websocket_connect(f"/session/{session_id}/stream", headers={"Origin": "http://localhost:3000"}) as socket:
            half = struct.pack("<II", 0, 1) + struct.pack("<80h", *([1000] * 80))
            full_pcm = struct.pack("<160h", *([1000] * 160))
            socket.send_bytes(half)
            self.assertEqual(socket.receive_json(), {"type": "audio_accepted", "generation": 0, "sessionId": session_id})
            socket.send_bytes(half)
            seen = [socket.receive_json() for _ in range(2)]
            self.assertIn("frame", [item["type"] for item in seen])
            self.assertEqual(next(item for item in seen if item["type"] == "frame")["sourcePacketId"], 1)
            self.assertEqual(engine.audio[0][1], 0)
            self.assertEqual(engine.audio[0][2], full_pcm)
            socket.send_text('{"type":"interrupt","generation":1}')
            self.assertEqual(socket.receive_json(), {"type": "interrupted", "generation": 1, "sessionId": session_id})
            socket.send_bytes(struct.pack("<II", 0, 2) + full_pcm)  # stale generation is ignored
            socket.send_bytes(struct.pack("<II", 1, 3) + full_pcm)
            self.assertEqual(socket.receive_json(), {"type": "audio_accepted", "generation": 1, "sessionId": session_id})
            seen = [socket.receive_json() for _ in range(2)]
            self.assertTrue(any(item.get("generation") == 1 and item["type"] == "frame" for item in seen))
            self.assertEqual(next(item for item in seen if item["type"] == "frame")["sourcePacketId"], 3)
        self.assertEqual(client.get("/health").json()["activeSessions"], 0)
        self.assertEqual(client.get("/ready").json(), {"ready": True, "available": True, "activeSessions": 0})
        self.assertEqual(client.delete(f"/session/{session_id}").json(), {"closed": False})

    def test_origin_and_bounded_input(self):
        call = worker.AvatarCall("test")
        packet = struct.pack("<IIh", 0, 1, 5)
        self.assertTrue(call.append(packet, 320))
        self.assertFalse(call.append(b"bad", 320))
        call.interrupt(1)
        self.assertEqual(len(call.audio), 0)
        self.assertFalse(call.append(packet, 320))

    def test_five_minutes_of_input_volume_remains_bounded_without_inference(self):
        call = worker.AvatarCall("long-test")
        one_second = struct.pack("<II", 0, 1) + bytes(32000)
        for _ in range(300):
            self.assertTrue(call.append(one_second, 32000))
            self.assertLessEqual(len(call.audio), 3 * 32000)
        self.assertGreater(call.dropped_audio_samples, 0)


if __name__ == "__main__":
    unittest.main()
