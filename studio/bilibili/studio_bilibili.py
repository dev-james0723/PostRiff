"""Launch the isolated user-selected Bilibili upload provider on owner request."""
from pathlib import Path
import os
import subprocess
import threading
import time
import httpx
from .studio import StudioError

_lock = threading.Lock()

def register_bilibili_routes(app, root):
    @app.post('/api/connections/bilibili/open')
    def open_provider():
        with _lock:
            url = 'http://127.0.0.1:4387'
            def healthy():
                try:
                    with httpx.Client(trust_env=False, timeout=1) as client:
                        r = client.get(url + '/health')
                    return r.status_code == 200 and r.json() == {'app':'james-studio-bilibili','version':1}
                except Exception:
                    return False
            if not healthy():
                provider = Path(root) / 'studio/bilibili'
                python = provider / '.venv/bin/python'
                if not python.is_file():
                    raise StudioError('bilibili_not_installed', 'Bilibili provider is not installed.', 503)
                env = {k:os.environ[k] for k in ('HOME','PATH','TMPDIR') if k in os.environ}
                child = subprocess.Popen([str(python), str(provider/'server.py')], cwd=provider, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
                for _ in range(60):
                    if healthy():
                        break
                    if child.poll() is not None:
                        raise StudioError('bilibili_start_failed', 'The Bilibili provider could not start.', 503)
                    time.sleep(.1)
                else:
                    raise StudioError('bilibili_start_pending', 'Bilibili is still starting. Try opening it again.', 503)
            return {'url':url, 'route':'unofficial_session_provider'}
