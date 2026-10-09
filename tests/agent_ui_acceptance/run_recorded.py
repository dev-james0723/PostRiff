"""Run a lane-G unittest module and record each test's outcome in the Recorder format the gate summary reads, so checks that
live in a plain unittest module (the contract-layer negatives) count toward the same CI run's gate records.

    python -m agent_ui_acceptance.run_recorded test_agent_ui_acceptance_contract contract-corpus
"""
from __future__ import annotations

import sys
import unittest

from .evidence import Recorder


class _Result(unittest.TextTestResult):
    def __init__(self, *args, recorder: Recorder, module: str, **kwargs):
        super().__init__(*args, **kwargs)
        self.recorder, self.module = recorder, module

    def _name(self, test) -> str:
        return f"{self.module}.{type(test).__name__}.{test._testMethodName}"

    def addSuccess(self, test):
        super().addSuccess(test)
        self.recorder.add(self._name(test), "pass", "ok")

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.recorder.add(self._name(test), "fail", str(err[1])[:400])

    def addError(self, test, err):
        super().addError(test, err)
        self.recorder.add(self._name(test), "fail", f"{err[0].__name__}: {err[1]}"[:400])

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.recorder.add(self._name(test), "blocked", str(reason)[:400])


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    module, name = argv[0], argv[1]
    recorder = Recorder(name)
    suite = unittest.defaultTestLoader.loadTestsFromName(f"agent_ui_acceptance.{module}")
    runner = unittest.TextTestRunner(verbosity=2, resultclass=lambda *a, **k: _Result(*a, recorder=recorder, module=module, **k))
    result = runner.run(suite)
    recorder.write()
    return 0 if result.wasSuccessful() and result.testsRun > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
