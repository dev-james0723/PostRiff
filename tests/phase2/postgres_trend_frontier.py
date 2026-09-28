"""Only frozen frontier25 plus runtime tests, fresh Unix-socket PostgreSQL56447."""
import hashlib
import importlib.util
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('frontier_runtime_cluster',ROOT/'scripts/trend_learning_portable.py')
runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
original_run=runner.subprocess.run
PATHS=['src/postriff_phase2/growth/trends/'+name+'.py' for name in
       ('frontier','frontier_runtime','analytics_runtime','analytics_retention','learning','store','jobs','retention','revocation','outbox','planner','contracts')]
PATHS+=['tests/test_trend_frontier.py','tests/test_trend_frontier_runtime.py','tests/test_trend_integration.py',
        'scripts/trend_learning_portable.py','tests/phase2/postgres_trend_frontier.py','migrations/postriff/040_social_trend_intelligence.sql']


def execute(cmd,*args,**kwargs):
    if isinstance(cmd,list) and '-c' in cmd and 'test_trend_learning.LearningSQL' in cmd[-1]:
        cmd=cmd[:-1]+[cmd[-1].replace("loadTestsFromName('test_trend_learning.LearningSQL')",
             "loadTestsFromNames(['test_trend_frontier.FrontierOffline','test_trend_frontier.FrontierSQL','test_trend_frontier_runtime.FrontierRuntimeOffline','test_trend_frontier_runtime.FrontierRuntimeSQL'])")]
    return original_run(cmd,*args,**kwargs)


if __name__=='__main__':
    runner.hashes=lambda:{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in PATHS}
    runner.subprocess.run=execute
    sys.exit(runner.main())
