"""No network: bounded transport construction and hosted ingestion wiring."""
import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1] / "src"))
from postriff_phase2.providers import http_transport

class AudienceTransport(unittest.TestCase):
    def test_https_context_belongs_to_handler_not_opener_open(self):
        class Response(io.BytesIO):
            status = 200
            headers = {}
        class Opener:
            def open(self, request, timeout):
                assert timeout == 20
                return Response(json.dumps({"data":[]}).encode())
        with patch("postriff_phase2.providers.build_opener",return_value=Opener()) as build:
            assert http_transport("GET","https://synthetic.invalid/replies")["body"] == {"data":[]}
            assert len(build.call_args.args) == 2
