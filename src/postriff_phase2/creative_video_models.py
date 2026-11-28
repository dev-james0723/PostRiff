"""The native capabilities and USD list prices of routes this worker implements."""
from dataclasses import dataclass
from fractions import Fraction

from postriff_alpha.domain import AlphaError
from .creative_video_media import FPS, MAX_SCENE_MS, MIN_SCENE_MS, SIZES


VERTEX_FAST = "veo-3.1-fast-generate-001"
RUNWAY_GEN4 = "gen4.5"
RUNWAY_VEO = "veo3.1_fast"
STORYBOARD = "storyboard-v1"
PRICE_VERSION = "video-usd-2026-11-27.1"
RUNWAY_CREDIT_USD_MICRO = 10_000
VERTEX_PRICING = "https://cloud.google.com/model-garden/pricing"
RUNWAY_PRICING = "https://docs.dev.runwayml.com/guides/pricing/"


@dataclass(frozen=True)
class PriceLine:
    """A versioned server-defined rate for a number of input/output units, including token and media units."""
    component: str
    unit: str
    quantity: int
    usd_micro: int
    per_units: int = 1

    def amount(self):
        if (type(self.quantity) is not int or not 0 <= self.quantity <= 10**12 or
                type(self.usd_micro) is not int or not 0 <= self.usd_micro <= 10**12 or
                type(self.per_units) is not int or not 1 <= self.per_units <= 10**9):
            raise ValueError("Invalid server pricing quantity or denomination.")
        return Fraction(self.quantity * self.usd_micro, self.per_units)

    def record(self):
        return {"component": self.component, "unit": self.unit, "quantity": self.quantity,
                "rateUsdMicro": self.usd_micro, "perUnits": self.per_units}


def metered_total(lines):
    # One ceiling to provider microdollars after summing all precise charges. Rafii credit rounding follows separately.
    amount = sum((line.amount() for line in lines), Fraction())
    return (amount.numerator + amount.denominator - 1) // amount.denominator


@dataclass(frozen=True)
class Model:
    id: str
    provider: str
    label: str
    media_kind: str
    ratios: tuple[str, ...]
    durations: tuple[int, ...]
    # Resolution, audio mode, integer USD-micro cost for one generated second.
    rates: tuple[tuple[str, str, int], ...]
    price_source: str | None
    max_prompt_units: int
    supports_cancel: bool = False

    def rates_for(self, resolution, audio):
        return next((rate for size, sound, rate in self.rates if (size, sound) == (resolution, audio)), None)

    def take_ms(self, duration_ms, resolution):
        if type(duration_ms) is not int or not MIN_SCENE_MS <= duration_ms <= MAX_SCENE_MS:
            raise AlphaError("Choose a scene between 42 milliseconds and 8 seconds.", 422)
        if self.media_kind == "composed":
            # Allow time for at least two analysis samples even when the eventual trim is shorter.
            frames = max(FPS, (duration_ms * FPS + 999) // 1000)
            return (frames * 1000 + FPS // 2) // FPS
        if self.id == VERTEX_FAST and resolution == "1080p":
            # This worker requests the documented 8-second configuration for higher native resolution.
            return 8000
        return next(s * 1000 for s in self.durations if s * 1000 >= duration_ms)

    def profile(self, duration_ms, aspect_ratio, resolution, audio):
        if aspect_ratio not in self.ratios or self.rates_for(resolution, audio) is None:
            raise AlphaError("The selected model cannot supply that size, aspect ratio or audio.", 422)
        width, height = SIZES[aspect_ratio]
        if resolution == "1080p":
            width, height = width * 3 // 2, height * 3 // 2
        return {"width": width, "height": height, "fps": FPS, "hasAudio": audio == "generated",
                "durationMs": self.take_ms(duration_ms, resolution), "minFrames": (duration_ms * FPS + 999) // 1000}

    def price_lines(self, duration_ms, resolution, audio):
        rate = self.rates_for(resolution, audio)
        if rate is None:
            raise AlphaError("No current price covers this output configuration.", 422)
        if self.media_kind == "composed":
            return (PriceLine("rafii_storyboard", "composed_take", 1, 0),)
        return (PriceLine("native_video_and_audio" if audio == "generated" else "native_video",
                          "output_second", self.take_ms(duration_ms, resolution) // 1000, rate),)


PORTRAIT_LANDSCAPE = ("9:16", "16:9")
MODELS = {model.id: model for model in (
    Model(STORYBOARD, "rafii-local", "Rafii motion storyboard", "composed", (*PORTRAIT_LANDSCAPE, "1:1"), (),
          (("720p", "silent", 0),), None, 4000),
    Model(VERTEX_FAST, "vertex-veo", "Veo 3.1 Fast · Google Cloud", "generated", PORTRAIT_LANDSCAPE, (4, 6, 8),
          (("720p", "generated", 100_000), ("720p", "silent", 80_000),
           ("1080p", "generated", 120_000), ("1080p", "silent", 100_000)), VERTEX_PRICING, 4000),
    Model(RUNWAY_GEN4, "runway", "Gen-4.5 · Runway", "generated", PORTRAIT_LANDSCAPE, tuple(range(2, 9)),
          (("720p", "silent", 12 * RUNWAY_CREDIT_USD_MICRO),), RUNWAY_PRICING, 1000, True),
    Model(RUNWAY_VEO, "runway", "Veo 3.1 Fast · Runway", "generated", PORTRAIT_LANDSCAPE, (4, 6, 8),
          # The catalog explicitly enables only the 720p partner rates used by this adapter.
          (("720p", "generated", 15 * RUNWAY_CREDIT_USD_MICRO), ("720p", "silent", 10 * RUNWAY_CREDIT_USD_MICRO)),
          RUNWAY_PRICING, 1000, True),
)}
