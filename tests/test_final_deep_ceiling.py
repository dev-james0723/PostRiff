"""FINAL-05: the reservation ceiling for deep mode stays a true upper bound without making deep drafting
unaffordable. The revise pass re-reads the first draft, whose length `max_tokens` bounds; the old ceiling
counted the 1 MB transport cap as tokens (a deep caption on Sonnet held about 657 credits, more than a new
workspace has)."""
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from postriff_phase2.model_runtime import ATTEMPTS, MAX_OUTPUT_TOKENS, ServerModelRuntime
from test_postriff_model_runtime import context


def credits(usd):
    return math.ceil(usd * 3000 - 1e-9) / 10


class DeepCeiling(unittest.TestCase):
    def setUp(self):
        self.runtime = ServerModelRuntime('key', model='anthropic/claude-sonnet-5', models=['anthropic/claude-sonnet-5'])
        self.request = {'context': context(), 'idea': 'Announce the spring recital.', 'destinations': [{'platform': 'LinkedIn', 'language': 'en-US'}]}

    def test_deep_ceiling_covers_every_call_but_stays_usable(self):
        standard = self.runtime.price_quote({**self.request, 'reasoning': 'standard'})
        deep = self.runtime.price_quote({**self.request, 'reasoning': 'deep'})
        self.assertGreater(deep, standard)
        self.assertLess(deep, 3 * standard, 'deep is at most one more call plus the re-read draft')
        self.assertLess(credits(deep), 50, 'a new workspace can afford one deep caption')

    def test_deep_ceiling_still_bounds_the_worst_case(self):
        import json
        prompt_bytes = len(json.dumps(self.runtime._messages({**self.request, 'reasoning': 'deep'}, 'deep'), ensure_ascii=False).encode()) + 256
        calls = ATTEMPTS + 1
        worst = self.runtime._cost('anthropic/claude-sonnet-5', prompt_bytes * calls + MAX_OUTPUT_TOKENS, MAX_OUTPUT_TOKENS * calls)
        self.assertGreaterEqual(self.runtime.price_quote({**self.request, 'reasoning': 'deep'}), worst)


if __name__ == '__main__':
    unittest.main()
