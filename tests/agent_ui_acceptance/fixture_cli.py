"""Setup-only fixture CLI for the browser runner (web/tests/agent-ui-e2e/run.cjs): rows on the disposable loopback database
that the product's own flows can't create inside one synthetic plan (e.g. a second membership beyond the trial's member
slots). Never used for an assertion; refuses anything but the acceptance stack's loopback DSN.

    AGENT_UI_STACK_STATE=$EVIDENCE/stack.json python -m agent_ui_acceptance.fixture_cli add-member <workspaceId> <userId> <role>
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

from .db import Db

UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
ROLES = ("owner", "admin", "editor", "approver", "viewer")


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    state = json.loads(Path(os.environ["AGENT_UI_STACK_STATE"]).read_text(encoding="utf-8"))
    db = Db(state["dsn"])                      # raises unless the DSN is the loopback disposable cluster
    if len(argv) == 4 and argv[0] == "add-member" and UUID.match(argv[1]) and UUID.match(argv[2]) and argv[3] in ROLES:
        db.add_member(argv[1], argv[2], argv[3])
        print(json.dumps({"ok": True, "workspaceId": argv[1], "role": argv[3]}))
        return 0
    print(json.dumps({"ok": False, "usage": "add-member <workspaceId> <userId> <role>"}), file=sys.stderr)
    return 64


if __name__ == "__main__":
    raise SystemExit(main())
