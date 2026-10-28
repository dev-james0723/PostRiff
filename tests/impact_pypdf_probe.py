"""Read a directory of PDFs with this interpreter's pypdf through the Universal Library's text path; print JSON.

usage: python impact_pypdf_probe.py <tree root> <pdf directory>

library_extract.extract_text is unchanged between the live tree and the candidate; only the pinned pypdf moves (live
6.19.0, candidate 6.21.2). Running this file under several pypdf versions on the same files shows what the dependency
change does to a customer's PDF upload. Used by tests/test_customer_impact_dependencies.py.
"""
import hashlib
import json
import os
import sys

tree, directory = sys.argv[1], sys.argv[2]
sys.path.insert(0, os.path.join(tree, 'src'))
import pypdf  # noqa: E402
from postriff_alpha.domain import AlphaError  # noqa: E402
from postriff_phase2.library_extract import extract_text  # noqa: E402

out = {'pypdf': pypdf.__version__, 'files': {}}
for name in sorted(os.listdir(directory)):
    with open(os.path.join(directory, name), 'rb') as handle:
        raw = handle.read()
    try:
        status, text = extract_text(raw, 'pdf')
        out['files'][name] = {'ok': True, 'status': status, 'text': text[:400], 'sha256': hashlib.sha256(text.encode()).hexdigest()}
    except AlphaError as error:
        out['files'][name] = {'ok': False, 'message': str(error)}
print(json.dumps(out, sort_keys=True))
