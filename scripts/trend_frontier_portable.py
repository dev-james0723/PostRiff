"""Source-bound frontier checks in a new Unix-socket-only PostgreSQL on 56447.

Reuses the frozen learning runner's safe cluster lifecycle; replaces only the
explicit test suite and source fingerprint list in this process. No live I/O.
"""
import hashlib
import importlib.util
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('frontier_disposable_cluster', ROOT/'scripts/trend_learning_portable.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
original_run = runner.subprocess.run
PATHS = ['src/postriff_phase2/growth/trends/'+p+'.py' for p in
         ('frontier','discovery','planner','jobs','store','retention','outbox','learning','analytics_retention')]
PATHS += ['tests/test_trend_frontier.py','tests/test_trend_integration.py','scripts/trend_frontier_portable.py',
          'scripts/trend_learning_portable.py','migrations/postriff/040_social_trend_intelligence.sql']


def execute(cmd, *args, **kwargs):
    if isinstance(cmd,list) and '-c' in cmd and 'test_trend_learning.LearningSQL' in cmd[-1]:
        cmd = cmd[:-1]+[cmd[-1].replace("loadTestsFromName('test_trend_learning.LearningSQL')",
            "loadTestsFromNames(['test_trend_frontier.FrontierOffline','test_trend_frontier.FrontierSQL'])")]
    return original_run(cmd,*args,**kwargs)


if __name__ == '__main__':
    runner.hashes = lambda:{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in PATHS}
    runner.subprocess.run = execute
    sys.exit(runner.main())
