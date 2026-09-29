"""Synthetic identity injection exists only in disposable tests, never in the deployment artifact."""
import os
import time
from wsgiref.simple_server import make_server, WSGIRequestHandler
from rafii_control.auth import Boundary, Config, VerifiedIdentity, ControlError
from rafii_control.http import ControlApplication
from rafii_control.intelligence import QueryService
from rafii_control.store import PostgresStore, connection_factory

class Quiet(WSGIRequestHandler):
    def log_message(self, format, *args): pass

def main():
    if os.environ.get('VERCEL') or os.environ.get('VERCEL_ENV'): raise RuntimeError('Local tests only')
    dsn=os.environ['RAFII_CONTROL_TEST_DSN']
    if not dsn.startswith('host=127.0.0.1 port='): raise RuntimeError('Disposable loopback cluster only')
    store=PostgresStore(connection_factory(dsn,'rafii_control_session','local'),connection_factory(dsn,'rafii_control_reader','local'),'local')
    def verify(token):
        if token!='synthetic-founder-aal2':raise ControlError('AUTH_REQUIRED',401)
        return VerifiedIdentity('00000000-0000-0000-0000-000000000001','aal2','synthetic-browser-session-001',time.time())
    application=ControlApplication(Boundary(Config(True,'local','http://localhost:4449'),store,verify),QueryService(store))
    with make_server('127.0.0.1',4450,application,handler_class=Quiet) as server: server.serve_forever()

if __name__=='__main__': main()
