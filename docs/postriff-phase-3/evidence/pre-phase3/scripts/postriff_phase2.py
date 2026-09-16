#!/usr/bin/env python3
"""Separate loopback runtime; never reads the founder-alpha database."""
import argparse
import os
import sys
import threading
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"src"))
from postriff_alpha.server import make_server
from postriff_phase2.store import Phase2Store


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=4328)
    parser.add_argument("--data", type=Path, default=Path.home()/"Library/Application Support/PostRiffPhase2/local.sqlite3")
    parser.add_argument("--static", type=Path, default=Path(__file__).resolve().parents[1]/"studio/web/dist-alpha")
    args = parser.parse_args()
    if not (args.static/"index.html").is_file():
        parser.error("Build the alpha frontend first.")
    os.umask(0o077)
    store = Phase2Store(args.data)
    stop = threading.Event()
    def work():
        while not stop.wait(2):
            try:
                store.worker_step()
            except Exception:
                # No private state, request contents or credentials in logs.
                print("Local worker could not finish; saved leases will recover.", flush=True)
    worker = threading.Thread(target=work, daemon=True)
    worker.start()
    server = make_server(store, args.static, args.port)
    print(f"PostRiff Phase 2 local fixtures: http://127.0.0.1:{args.port}/ | zero external execution", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        server.server_close()
        worker.join(timeout=5)

if __name__ == "__main__":
    main()
