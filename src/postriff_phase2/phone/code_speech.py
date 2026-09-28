"""Isolated, ephemeral pre-auth digit transcription. Never an agent session or a transcript log."""
import io
import re
import struct
import unicodedata
import wave

MAX_SECONDS = 15
# Operator admission estimate covers at most three short STT requests; not a provider billing guarantee.
RESERVE_USD_MICRO = 10000
WORDS = dict(zip('zero one two three four five six seven eight nine'.split(), '0123456789'))
WORDS.update({'oh': '0', 'o': '0'})
CHINESE = dict(zip('零〇一二三四五六七八九幺兩两', '00123456789122'))


def parse_code(text):
    if not isinstance(text, str) or len(text) > 200:
        return None
    text = unicodedata.normalize('NFKC', text).lower().strip()
    for word, digit in WORDS.items():
        text = re.sub(r'\b' + word + r'\b', digit, text)
    text = ''.join(CHINESE.get(c, c) for c in text)
    text = re.sub(r'[\s,，.。\-]', '', text)
    return text if re.fullmatch(r'[0-9]{12}', text) else None


def pcm_sample(value):
    value = ~value & 255
    sample = (((value & 15) << 3) + 132) << ((value >> 4) & 7)
    return (132 - sample) if value & 128 else (sample - 132)


PCM = tuple(pcm_sample(i) for i in range(256))


class Utterance:
    """Phone-band RMS endpointing: two seconds of quiet or fifteen seconds total; bounded memory."""
    def __init__(self):
        self.clear()

    def clear(self):
        self.data = bytearray()
        self.speech = self.quiet = 0

    def feed(self, audio):
        for start in range(0, len(audio), 160):
            frame = audio[start:start + 160]
            loud = sum(PCM[c] ** 2 for c in frame) > len(frame) * 400 ** 2
            if loud:
                self.speech += len(frame)
                self.quiet = 0
            elif self.data:
                self.quiet += len(frame)
            if self.speech:
                self.data.extend(frame)
            if self.data and (self.quiet >= 16000 or len(self.data) >= MAX_SECONDS * 8000):
                result = bytes(self.data) if self.speech >= 2400 else None
                self.clear()
                return result
        return None


def wav_bytes(audio):
    if not 1 <= len(audio) <= MAX_SECONDS * 8000 + 160:
        raise ValueError('Invalid code audio length')
    out = io.BytesIO()
    with wave.open(out, 'wb') as wav:
        wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(8000)
        wav.writeframes(b''.join(struct.pack('<h', PCM[c]) for c in audio))
    return out.getvalue()


async def transcribe(audio, credential):
    from openai import AsyncOpenAI
    # No retries: ambiguous submissions must not duplicate charges. No temporary audio files.
    async with AsyncOpenAI(api_key=credential, max_retries=0, timeout=8) as client:
        result = await client.audio.transcriptions.create(
            model='gpt-4o-mini-transcribe', file=('code.wav', wav_bytes(audio), 'audio/wav'),
            response_format='json', prompt='A Agent Pairing Code, spoken one digit at a time in English, Cantonese or Mandarin. Transcribe only the digits actually heard. Never add or infer missing digits.')
    return parse_code(result.text)
