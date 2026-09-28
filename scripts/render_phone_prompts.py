"""Preview by default. --generate makes exactly one paid TTS request per missing clip, without retries.
Creates reviewable candidate WAV/PCMU assets; does not install, upload or deploy them.
An in-flight/error record blocks uncertain duplicate submissions.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import wave

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'src/postriff_phase2/phone/assets/prompts.json'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--generate', action='store_true')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--only', choices=('dial-acceptance', 'dial-inbound', 'dial-inbound-retry'))
    args = parser.parse_args()
    spec = json.loads(MANIFEST.read_text())
    if args.only:
        spec['prompts'] = {args.only: spec['prompts'][args.only]}
    if not args.generate:
        print(json.dumps({'execution': 'candidate; no API calls', 'requests': len(spec['prompts']), **spec}, indent=2))
        return
    if not args.output:
        parser.error('--output is required for generation')
    from openai import OpenAI
    # No automatic credential discovery, retries or account switch.
    client = OpenAI(api_key=os.environ['OPENAI_API_KEY'], max_retries=0, timeout=60)
    args.output.mkdir(parents=True, exist_ok=True)
    receipt_path = args.output / 'generation.json'
    receipt = json.loads(receipt_path.read_text()) if receipt_path.exists() else {}
    def save():
        receipt_path.write_text(json.dumps(receipt, indent=2)+'\n')
    for name, text in spec['prompts'].items():
        request = {k: spec[k] for k in ('model', 'voice', 'instructions', 'response_format')}
        request['input'] = text
        fingerprint = hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()
        previous = receipt.get(name)
        if previous:
            if previous['fingerprint'] != fingerprint or previous['state'] != 'completed':
                raise RuntimeError('Changed or uncertain prior generation; reconcile before another paid request')
            if not (args.output / (name + '.wav')).is_file() or not (args.output / (name + '.mulaw')).is_file():
                raise RuntimeError('Previously generated asset missing; reconcile without another request')
            continue
        receipt[name] = {'state': 'submitted_outcome_unknown', 'fingerprint': fingerprint}
        save()
        wav = args.output / (name + '.wav')
        with client.audio.speech.with_streaming_response.create(**request) as response:
            response.stream_to_file(wav)
        # Streaming WAV headers may advertise an unknown length; normalize from actual frames.
        with wave.open(str(wav)) as source:
            channels, width, rate = source.getnchannels(), source.getsampwidth(), source.getframerate()
            frames = source.readframes(source.getnframes())
        with wave.open(str(wav), 'wb') as output:
            output.setnchannels(channels)
            output.setsampwidth(width)
            output.setframerate(rate)
            output.writeframes(frames)
        receipt[name]['state'] = 'audio_received'
        save()
        mulaw = args.output / (name + '.mulaw')
        subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-i', str(wav), '-ac', '1', '-ar', '8000', '-c:a', 'pcm_mulaw', '-f', 'mulaw', str(mulaw)], check=True)
        size = mulaw.stat().st_size
        if not 8000 <= size <= (120000 if name == 'dial-acceptance' else 200000):
            raise RuntimeError('Generated prompt is outside the phone playback duration limits; review before installing')
        receipt[name].update(state='completed', seconds=size / 8000, sha256=hashlib.sha256(mulaw.read_bytes()).hexdigest())
        save()
    print(json.dumps({'execution':'generated candidate; not installed or deployed','receipt':str(receipt_path)}))

if __name__ == '__main__': main()
