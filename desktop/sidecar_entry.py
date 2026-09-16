#!/usr/bin/env python3
"""Local desktop sidecar; no account secrets or legacy runtime imported."""
import argparse
import json
import os
from pathlib import Path
import signal
import sys
import threading
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from postriff_alpha.server import make_server
from postriff_phase3.store import Phase3Store

def main():
 parser=argparse.ArgumentParser()
 parser.add_argument('--port',type=int,default=4330)
 parser.add_argument('--data',type=Path,default=Path.home()/'Library/Application Support/PostRiffPhase3/local.sqlite3')
 parser.add_argument('--static',type=Path,default=Path(__file__).resolve().parents[1]/'studio/web/dist-alpha')
 parser.add_argument('--parent-watch',action='store_true')
 args=parser.parse_args();os.umask(0o077)
 store=Phase3Store(args.data);server=make_server(store,args.static,args.port)
 server.desktop_secret=os.environ.get('POSTRIFF_DESKTOP_SECRET','')
 stop=threading.Event()
 def shutdown(*_):
  stop.set();threading.Thread(target=server.shutdown,daemon=True).start()
 signal.signal(signal.SIGTERM,shutdown)
 def worker():
  while not stop.wait(.75):
   try:store.fixture_step()
   except Exception:pass # Persisted state is authoritative; no input/credential logging.
 def parent():
  sys.stdin.buffer.read();shutdown()
 if args.parent_watch:threading.Thread(target=parent,daemon=True).start()
 thread=threading.Thread(target=worker,daemon=True);thread.start()
 print(json.dumps({'port':server.server_port,'execution':'phase3-local-contracts'}),flush=True)
 try:server.serve_forever(poll_interval=.2)
 finally:stop.set();server.server_close();thread.join(timeout=2)
if __name__=='__main__':main()
