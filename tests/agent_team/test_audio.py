"""Synthetic WAV/report fixtures; never invoke say, downloads, models or providers."""

import copy
import hashlib
import io
import json
import struct
import tempfile
import unittest
import wave
from pathlib import Path

from agent_team.audio import (
    AudioBlocked,
    AudioLimits,
    CLOUD_METADATA_FIELDS,
    GENERATOR_VERSION,
    SAY_BINARY,
    VOICE,
    generate_report_audio,
    narration_for_report,
    parse_wav,
    validate_report,
    validate_wav,
)
from agent_team.events import canonical
from agent_team.periods import period
from agent_team.reports import report


NOW = "2026-10-06T05:02:00Z"


def fixture_report(*, versioned=False, kind="whole_day", preview=False):
    result = report(period("2026-10-05", kind), [], NOW, preview=preview)
    if versioned:
        result["version"] = 1
        result["initialGeneratedAt"] = result["generatedAt"]
        result["fingerprint"] = hashlib.sha256(canonical({key: value for key, value in result.items()
                                                         if key not in CLOUD_METADATA_FIELDS}).encode()).hexdigest()
    return result


def rehash(document):
    excluded = CLOUD_METADATA_FIELDS if "version" in document else {"fingerprint"}
    document["fingerprint"] = hashlib.sha256(canonical({key: value for key, value in document.items()
                                                        if key not in excluded}).encode()).hexdigest()
    return document


def wav_fixture(*, seconds=0.02, rate=16_000, channels=1, silent=False):
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as stream:
        stream.setnchannels(channels)
        stream.setsampwidth(2)
        stream.setframerate(rate)
        frames = max(1, int(seconds * rate))
        stream.writeframes((b"\x00\x00" if silent else b"\x01\x00") * channels * frames)
    return buffer.getvalue()


class SyntheticRunner:
    execution_state = "synthetic_fixture"

    def __init__(self, payload=None, failure=None):
        self.payload = payload if payload is not None else wav_fixture()
        self.failure = failure
        self.calls = []

    def run(self, argv, *, stdin_bytes, timeout_seconds, max_wav_bytes, output_file):
        self.calls.append({"argv": argv, "stdin": stdin_bytes, "timeout": timeout_seconds,
                           "max_bytes": max_wav_bytes, "output_file": output_file})
        if self.failure:
            raise self.failure
        output_file.write_bytes(self.payload)


class AudioTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def generate(self, document, runner, **kwargs):
        return generate_report_audio(document, canonical_root=self.root, runner=runner, now=NOW, **kwargs)

    def test_full_preview_and_stable_cloud_fingerprint_policies(self):
        local = fixture_report()
        cloud = fixture_report(versioned=True)
        self.assertEqual(validate_report(local, now=NOW).fingerprint_policy, "preview_full_v1")
        self.assertEqual(validate_report(cloud, now=NOW).fingerprint_policy, "cloud_stable_v1")
        changed = copy.deepcopy(cloud)
        changed["generatedAt"] = "2026-10-06T05:01:00Z"
        changed["initialGeneratedAt"] = changed["generatedAt"]
        changed["version"] = 2
        changed["supplementOf"] = "a" * 64
        self.assertEqual(validate_report(cloud, now=NOW).fingerprint, validate_report(changed, now=NOW).fingerprint)

    def test_modified_summary_fails_before_audio_creation(self):
        document = fixture_report(versioned=True)
        document["summary"] += "unexpected modification"
        runner = SyntheticRunner()
        with self.assertRaisesRegex(AudioBlocked, "report_fingerprint_mismatch"):
            self.generate(document, runner)
        self.assertEqual(runner.calls, [])
        self.assertFalse((self.root / ".runtime").exists())

    def test_exact_period_and_version_are_validated(self):
        for field, value, diagnostic in (("schemaVersion", 2, "report_schema_unsupported"),
                                         ("version", True, "report_version_invalid")):
            document = fixture_report(versioned=True)
            document[field] = value
            rehash(document)
            with self.subTest(field=field), self.assertRaisesRegex(AudioBlocked, diagnostic):
                validate_report(document, now=NOW)
        document = fixture_report()
        document["period"]["cutoff"] = "2026-10-06T06:00:00Z"
        rehash(document)
        with self.assertRaisesRegex(AudioBlocked, "report_period_mismatch"):
            validate_report(document, now=NOW)

    def test_only_due_whole_day_cloud_is_delivery_eligible(self):
        self.assertFalse(validate_report(fixture_report(), now=NOW).delivery_eligible)
        self.assertFalse(validate_report(fixture_report(versioned=True, preview=True), now=NOW).delivery_eligible)
        self.assertFalse(validate_report(fixture_report(versioned=True, kind="half_day"), now=NOW).delivery_eligible)
        verified = validate_report(fixture_report(versioned=True), now=NOW)
        self.assertTrue(verified.delivery_eligible)
        self.assertEqual(validate_report(fixture_report(), now=NOW).execution_state, "preview_audio")

    def test_narration_is_deterministic_complete_sentence_excerpt(self):
        document = fixture_report(versioned=True)
        checked = validate_report(document, now=NOW)
        self.assertEqual(narration_for_report(document), checked.narration)
        self.assertLessEqual(len(checked.narration), 64)
        self.assertTrue(document["summary"].startswith(checked.narration))
        self.assertTrue(checked.narration.endswith(("。", "！", "？", ".", "!", "?")))
        self.assertTrue(checked.excerpt)
        self.assertEqual(checked.summary_hash, hashlib.sha256(document["summary"].encode()).hexdigest())
        self.assertEqual(checked.narration_hash, hashlib.sha256(checked.narration.encode()).hexdigest())

    def test_overlong_first_sentence_has_explicit_clip_marker(self):
        document = fixture_report()
        document["summary"] = "測" * 200 + "。"
        rehash(document)
        narration = narration_for_report(document)
        self.assertEqual(narration, "測" * 63 + "…")
        self.assertLessEqual(len(narration), 64)

    def test_markup_control_characters_and_summary_bounds_are_rejected(self):
        for summary in ("[[rate 5]]任務報告。", "報告\x00內容。", "測" * 801, " " + "報告。"):
            document = fixture_report()
            document["summary"] = summary
            rehash(document)
            with self.subTest(summary_length=len(summary)), self.assertRaisesRegex(AudioBlocked, "summary_invalid"):
                narration_for_report(document)

    def test_fixed_argv_private_stdin_and_synthetic_state_are_explicit(self):
        runner = SyntheticRunner()
        document = fixture_report(versioned=True)
        receipt = self.generate(document, runner)
        call = runner.calls[0]
        self.assertEqual(call["argv"][:9], (SAY_BINARY, "-v", VOICE, "-r", "175", "--file-format=WAVE",
                                          "--data-format=LEI16@16000", "--channels=1", "-o"))
        self.assertEqual(call["argv"][-2:], ("-f", "-"))
        self.assertEqual(call["stdin"], (narration_for_report(document) + "\n").encode())
        self.assertEqual(call["timeout"], 5.0)
        self.assertNotIn(document["summary"], str(call["argv"]))
        self.assertEqual(receipt.execution_state, "synthetic_audio_fixture")
        self.assertFalse(receipt.delivery_eligible)
        self.assertEqual(receipt.delivery_state, "not_delivered")
        self.assertIn("no cloned identity", receipt.voice_identity)

    def test_same_fingerprint_reuses_private_wav_without_resynthesizing(self):
        runner = SyntheticRunner()
        document = fixture_report(versioned=True)
        first, second = self.generate(document, runner), self.generate(document, runner)
        self.assertEqual(len(runner.calls), 1)
        self.assertEqual(first.file_path, second.file_path)
        self.assertFalse(first.reused)
        self.assertTrue(second.reused)
        self.assertEqual(first.wav.sha256, second.wav.sha256)
        wav = Path(first.file_path)
        self.assertEqual(wav.stat().st_mode & 0o777, 0o600)
        self.assertEqual(wav.parent.stat().st_mode & 0o777, 0o700)
        metadata = json.loads(wav.with_suffix(".json").read_text())
        self.assertEqual(metadata["generatorVersion"], GENERATOR_VERSION)
        self.assertNotIn(document["summary"], wav.with_suffix(".json").read_text())

    def test_corrupted_cached_audio_is_not_reused_or_overwritten(self):
        runner = SyntheticRunner()
        document = fixture_report()
        receipt = self.generate(document, runner)
        path = Path(receipt.file_path)
        path.write_bytes(b"corrupt")
        with self.assertRaises(AudioBlocked):
            self.generate(document, runner)
        self.assertEqual(path.read_bytes(), b"corrupt")
        self.assertEqual(len(runner.calls), 1)

    def test_invalid_generated_wav_and_timeout_never_publish_final_audio(self):
        document = fixture_report()
        for failure, payload in ((AudioBlocked("say_timeout"), None), (None, b"not a wav")):
            runner = SyntheticRunner(payload=payload, failure=failure)
            with self.subTest(failure=failure), self.assertRaises(AudioBlocked):
                self.generate(document, runner)
            audio_root = self.root / ".runtime/audio"
            self.assertEqual(list(audio_root.glob("*.wav")), [])
            self.assertEqual(list(audio_root.glob("*.json")), [])

    def test_output_path_alias_and_public_runtime_are_rejected(self):
        runtime = self.root / ".runtime"
        runtime.mkdir(mode=0o755)
        runtime.chmod(0o755)
        with self.assertRaisesRegex(AudioBlocked, "private_audio_directory_required"):
            self.generate(fixture_report(), SyntheticRunner())
        runtime.chmod(0o700)
        audio_root = runtime / "audio"
        audio_root.symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(AudioBlocked, "audio_path_alias_not_allowed"):
            self.generate(fixture_report(), SyntheticRunner())

    def test_pcm_wav_metadata_is_derived_from_actual_bytes(self):
        raw = wav_fixture(seconds=0.1)
        info = parse_wav(raw)
        self.assertEqual(info.duration_seconds, 0.1)
        self.assertEqual(info.frame_count, 1_600)
        self.assertEqual(info.sha256, hashlib.sha256(raw).hexdigest())
        self.assertEqual(validate_wav(raw)["sampleRate"], 16_000)
        self.assertEqual(validate_wav(raw)["byteCount"], len(raw))

    def test_wav_format_duration_signal_and_container_limits(self):
        invalid = [wav_fixture(rate=8_000), wav_fixture(channels=2), wav_fixture(silent=True),
                   wav_fixture(seconds=45.001), wav_fixture() + b"tail"]
        for payload in invalid:
            with self.subTest(size=len(payload)), self.assertRaises(AudioBlocked):
                parse_wav(payload)
        raw = bytearray(wav_fixture())
        struct.pack_into("<I", raw, 4, 0xFFFF_FFFF)
        with self.assertRaisesRegex(AudioBlocked, "wav_container_invalid"):
            parse_wav(bytes(raw))
        with self.assertRaisesRegex(AudioBlocked, "wav_size_limit"):
            parse_wav(b"x" * (2 * 1024 * 1024 + 1))

    def test_exact_45_second_limit_is_accepted(self):
        self.assertEqual(parse_wav(wav_fixture(seconds=45)).duration_seconds, 45)

    def test_invalid_limits_do_not_expand_timeout_duration_or_storage(self):
        for limits in (AudioLimits(timeout_seconds=10), AudioLimits(max_duration_seconds=46),
                       AudioLimits(max_wav_bytes=3 * 1024 * 1024)):
            with self.subTest(limits=limits), self.assertRaisesRegex(AudioBlocked, "audio_bounds_invalid"):
                limits.validate()


if __name__ == "__main__":
    unittest.main()
