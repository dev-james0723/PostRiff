from pathlib import Path
import sys,tempfile,json,os
root=Path(__file__).resolve().parents[3];sys.path[:0]=[str(root/'src'),str(root/'tests')]
from test_postriff_phase2 import P2Journey
from postriff_phase2.store import Phase2Store
from postriff_alpha.server import make_server
os.umask(0o077)
folder=Path(tempfile.mkdtemp(prefix='postriff-safety-ui-'));store=Phase2Store(folder/'fixture.db');j=P2Journey(store)
j.setup().act('generate',platform='LinkedIn',language='English')
access={'workspaceId':j.id,'token':j.token}
(folder/'access.json').write_text(json.dumps(access))
print(str(folder),flush=True)
make_server(store,root/'docs/postriff-improvement-20260914/evidence/ui-dist',45319).serve_forever()
