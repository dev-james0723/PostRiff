"""Guard one retry for only the witnessed Next.js Google Font metadata parser failure."""
import unittest
from scripts.trend_strategy_browser import _retryable_google_font_loader_failure


class GoogleFontRetryGate(unittest.TestCase):
    def test_exact_upstream_failure_qualifies(self):
        log = ("An error occurred in `next/font`\\n"
               "TypeError: Cannot read properties of null (reading '1')\\n"
               "  at /app/node_modules/next/dist/compiled/@next/font/dist/google/loader.js:122:78")
        self.assertTrue(_retryable_google_font_loader_failure(log))

    def test_missing_any_signature_does_not_qualify(self):
        exact = ("An error occurred in `next/font`\\n"
                 "TypeError: Cannot read properties of null (reading '1')\\n"
                 "  at /app/node_modules/next/dist/compiled/@next/font/dist/google/loader.js:122:78")
        for marker in (
            'An error occurred in `next/font`',
            "Cannot read properties of null (reading '1')",
            'next/dist/compiled/@next/font/dist/google/loader.js',
        ):
            with self.subTest(marker=marker):
                self.assertFalse(_retryable_google_font_loader_failure(exact.replace(marker, '')))

    def test_real_compile_error_never_retries(self):
        self.assertFalse(_retryable_google_font_loader_failure(
            "Failed to compile. TS2322: Property absent\\nBuild failed because of webpack errors"))
        self.assertFalse(_retryable_google_font_loader_failure(''))


if __name__ == '__main__':
    unittest.main()
