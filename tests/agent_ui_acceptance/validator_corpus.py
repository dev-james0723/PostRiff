"""Lane G — negatives of the trusted parser seam (lane C's validateAndMergeUi behind A's signed internal route).

Runs against the real Next server of the acceptance stack (`POST {AGENT_UI_WEB_URL}/internal/agent-ui/validate`), through the
real Python client (ui_validator.validate_and_merge_ui) and with raw signed requests for transport-level negatives. A positive
control (a minimal valid RafiiRoot built from C's generated schema) must be accepted first; while C's adapter is still the
stub, every case is BLOCKED rather than passing vacuously. Corpus: NC07, NC08, NC11, NC13, NC14, NC17 (corpus.py).

    AGENT_UI_WEB_URL=http://127.0.0.1:4539 AGENT_UI_VALIDATOR_SECRET=… python -m unittest agent_ui_acceptance.validator_corpus -v
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import unittest
from pathlib import Path

from .client import Api
from .evidence import Recorder
from .world import Blocked, recorded

ROOT = Path(__file__).resolve().parents[2]
GENERATED = ROOT / "src/postriff_phase2/agent_runtime_v2/generated"
WRITE_NAMES = ("schedule_apply", "draft_edit", "approvals_decide", "proposal_apply", "p2_approve", "raffi_recurrence_activate", "delete_account")
RECORD = Recorder("validator-corpus")
vcheck = recorded(RECORD, "validator_corpus")


def _assets():
    path = GENERATED / "openui-assets.json"
    if not path.exists():
        raise Blocked("BLOCKED lane C: generated/openui-assets.json is missing (D-A30)")
    return json.loads(path.read_text(encoding="utf-8"))


def _schema(library="consumer"):
    assets = _assets()
    lib = (assets.get("libraries") or {}).get(library)
    if not lib:
        raise Blocked(f"BLOCKED lane C: openui-assets.json has no '{library}' library")
    schema_file = GENERATED / (lib.get("schemaFile") or f"{library}.schema.json")
    if not schema_file.exists():
        raise Blocked(f"BLOCKED lane C: {schema_file.name} is missing")
    return lib, json.loads(schema_file.read_text(encoding="utf-8"))


def _defs(schema):
    # C's generator keys components under top-level `properties` (D-A30); older shapes used $defs.
    return schema.get("$defs") or schema.get("definitions") or schema.get("properties") or {}


def _literal(prop, defs, statements, depth=0):
    """A literal for one JSON-schema property: refs become child statements so the result is a complete, valid tree."""
    if depth > 3:
        return "null"
    if "default" in prop:
        return json.dumps(prop["default"], ensure_ascii=False)
    if "enum" in prop and prop["enum"]:
        return json.dumps(prop["enum"][0], ensure_ascii=False)
    ref = prop.get("$ref")
    if ref:
        name = ref.rsplit("/", 1)[-1]
        return _component(name, defs, statements, depth + 1)
    for key in ("anyOf", "oneOf"):
        if prop.get(key):
            options = [p for p in prop[key] if p.get("type") != "null"] or prop[key]
            return _literal(options[0], defs, statements, depth)
    kind = prop.get("type")
    if isinstance(kind, list):
        kind = next((k for k in kind if k != "null"), "null")
    return {"string": json.dumps("G acceptance"), "number": "1", "integer": "1", "boolean": "false", "array": "[]", "object": "{}",
            "null": "null"}.get(kind, "null")


def _component(name, defs, statements, depth=0):
    spec = defs.get(name) or {}
    props = spec.get("properties") or {}
    required = list(spec.get("required") or [])
    args = []
    last = max([list(props).index(r) for r in required if r in props] or [-1])
    for index, (key, prop) in enumerate(props.items()):
        if index > last:
            break
        args.append(_literal(prop, defs, statements, depth))
    ident = f"s{len(statements) + 1}"
    statements.append(f"{ident} = {name}({', '.join(args)})")
    return ident


def minimal_source(library="consumer") -> tuple[str, dict]:
    """`root = RafiiRoot(...)` with every required positional prop filled, plus the policy and library hash to send."""
    lib, schema = _schema(library)
    defs = _defs(schema)
    root = lib.get("root") or "RafiiRoot"
    if root not in defs:
        raise Blocked(f"BLOCKED lane C: {root} is not in the generated schema")
    statements: list[str] = []
    ident = _component(root, defs, statements)
    lines = [line.replace(f"{ident} = ", "root = ", 1) if line.startswith(f"{ident} = ") else line for line in statements]
    source = "\n".join([lines[-1]] + lines[:-1])          # root first (hoisting rule), children after
    policy = {"rootName": root, "allowedComponents": list(lib.get("components") or defs), "readBindings": ["drafts_list", "library_search"],
              "actionIds": ["draft_edit"], "founder": library == "founder"}
    return source, {"policy": policy, "libraryHash": lib.get("libraryHash") or "", "components": list(lib.get("components") or [])}


class Validator(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.web = os.environ.get("AGENT_UI_WEB_URL")
        cls.secret = os.environ.get("AGENT_UI_VALIDATOR_SECRET")
        if not cls.web or not cls.secret:
            raise RuntimeError("run by scripts/agent_ui_acceptance.sh api|browser: AGENT_UI_WEB_URL and AGENT_UI_VALIDATOR_SECRET are required")
        cls.api = Api(cls.web)
        cls.blocked = None
        try:
            cls.valid, cls.meta = minimal_source()
        except Blocked as error:
            cls.blocked = str(error)
            return
        control = cls.validate(cls.valid)
        if not control.get("accepted"):
            cls.blocked = f"BLOCKED lane C: the positive control was not accepted ({control.get('errors')}) — adapter still a stub or schema/policy mismatch"

    @classmethod
    def validate(cls, candidate, mode="generate", base=None, policy=None, library_hash=None):
        from postriff_phase2.agent_runtime_v2 import ui_validator
        meta = getattr(cls, "meta", {"policy": {}, "libraryHash": ""})
        return ui_validator.validate_and_merge_ui(base, candidate, library_hash or meta["libraryHash"], mode, policy=policy or meta["policy"],
                                                  scope={"workspaceId": "00000000-0000-4000-8000-0000000000a1", "artifactId": "00000000-0000-4000-8000-0000000000a2",
                                                         "attemptId": "00000000-0000-4000-8000-0000000000a3"},
                                                  values={"RAFII_GENUI_VALIDATOR_SECRET": cls.secret, "RAFII_GENUI_VALIDATOR_URL": cls.web})

    def setUp(self):
        if self.blocked:
            RECORD.add(f"validator_corpus.{type(self).__name__}.{self._testMethodName}", "blocked", self.blocked)
            raise Blocked(self.blocked)

    def rejected(self, candidate, *families, mode="generate", base=None, policy=None):
        result = self.validate(candidate, mode=mode, base=base, policy=policy)
        self.assertFalse(result.get("accepted"), f"accepted: {candidate[:200]!r}")
        self.assertIsNone(result.get("canonicalSource"))
        errors = " ".join(result.get("errors") or [])
        if families:
            self.assertTrue(any(f in errors for f in families), f"expected one of {families}, got {result.get('errors')}")
        return result

    def with_root_child(self, extra):
        return self.valid + "\n" + extra

    @vcheck
    def test_positive_control(self):
        result = self.validate(self.valid)
        self.assertTrue(result["accepted"], result.get("errors"))
        self.assertEqual(result["sourceHash"], hashlib.sha256(result["canonicalSource"].encode("utf-8")).hexdigest())
        self.assertTrue(set(result["componentNames"]) <= set(self.meta["policy"]["allowedComponents"]))
        self.assertGreaterEqual(result["statementCount"], 1)
        return f"minimal RafiiRoot accepted; sourceHash={result['sourceHash'][:12]}… = sha256(canonicalSource)"

    @vcheck
    def test_query_write_name_rejected(self):
        """NC07: a generated Query naming a write (or a non-literal/unknown tool) never validates."""
        for name in WRITE_NAMES:
            with self.subTest(name=name):
                self.rejected(self.with_root_child(f'w = Query("{name}", {{}}, null)'), "query_binding_denied", "binding")
        self.rejected(self.with_root_child('w = Query("schedule" + "_apply", {}, null)'), "query_binding_denied", "binding")
        self.rejected(self.with_root_child('$tool = "schedule_apply"\nw = Query($tool, {}, null)'), "query_binding_denied", "binding")
        return "write names, concatenated and $var tool names rejected"

    @vcheck
    def test_mutation_and_top_level_run_rejected(self):
        """NC08: native Mutation and @Run of it are forbidden in 0.3.2 (writes go through ActionButton only)."""
        self.rejected(self.with_root_child('m = Mutation("schedule_apply", {})'), "mutation_forbidden", "mutation")
        self.rejected(self.with_root_child('m = Mutation("schedule_apply", {})\nx = @Run(m)\ny = @Run(m)'), "mutation_forbidden", "mutation")
        self.rejected(self.with_root_child('m = Mutation("drafts_list", {})'), "mutation_forbidden", "mutation")
        return "Mutation statements and @Run(mutation) rejected"

    @vcheck
    def test_unknown_component_and_root(self):
        """NC13: unknown components, a non-RafiiRoot root, a missing root and builtin-named components are rejected."""
        self.rejected("root = NotAComponent()", "component", "unknown", "root")
        body = self.valid.split("\n", 1)
        children = body[1] if len(body) > 1 else ""
        other = next((c for c in self.meta["policy"]["allowedComponents"] if c != self.meta["policy"]["rootName"]), None)
        if other:
            self.rejected(f"root = {other}()\n{children}".strip(), "root")
        self.rejected(self.valid.replace("root = ", "main = ", 1), "root")
        self.rejected(self.with_root_child('h = Html("<b>x</b>")'), "component", "unknown")
        return "unknown component, wrong/missing root and builtin-named components rejected"

    @vcheck
    def test_bounds(self):
        """NC14: source/patch size, statement count, depth and nesting are refused (the client refuses size before any network)."""
        big = self.valid + "\n" + "\n".join(f'pad{i} = "{"x" * 200}"' for i in range(700))
        self.rejected(big, "source_too_large", "bounds")
        many = self.valid + "\n" + "\n".join(f"$v{i} = {i}" for i in range(600))
        self.rejected(many, "bounds", "statement")
        deep = self.valid + "\nd = " + "[" * 80 + "]" * 80
        self.rejected(deep, "nesting", "bounds", "depth")
        patch = "x = " + json.dumps("y" * (33 * 1024))
        self.rejected(patch, "source_too_large", mode="patch", base=self.valid)
        raw = self.raw(b"{" + b" " * (170 * 1024) + b"}")
        self.assertEqual(raw.status, 413)
        # The server enforces its own 128 KiB cap (a body under the 160 KiB transport cap, signed, but an oversized source).
        oversized = self.valid + "\n" + "\n".join(f'pad{i} = "{"x" * 200}"' for i in range(640))
        body = json.dumps({"v": "v1", "contractVersion": "rafii-genui/1", "mode": "generate", "baseSource": None, "candidateSource": oversized,
                           "libraryHash": self.meta["libraryHash"], "policy": self.meta["policy"], "scope": {"workspaceId": "a", "artifactId": "b", "attemptId": "c"}}).encode()
        self.assertLess(len(body), 160 * 1024)
        self.assertGreater(len(oversized.encode()), 128 * 1024)
        answer = self.raw(body)
        self.assertFalse((answer.json() or {}).get("accepted"), "the seam itself refuses an oversized source")
        return "size/statements/depth/nesting/body caps enforced"

    @vcheck
    def test_refresh_and_defaults_rejected(self):
        """NC17: no sub-30 s or computed refresh, no model-supplied defaults shown as data, no query→query arguments."""
        self.rejected(self.with_root_child('q = Query("drafts_list", {}, null, 0.01)'), "refresh")
        self.rejected(self.with_root_child('$fast = 1\nq = Query("drafts_list", {}, null, $fast)'), "refresh")
        self.rejected(self.with_root_child('q = Query("drafts_list", {}, {total: 0})'), "defaults")
        self.rejected(self.with_root_child('a = Query("drafts_list", {}, null)\nb = Query("library_search", {q: a.rows}, null)'), "args", "query_args")
        accepted = self.validate(self.with_root_child('q = Query("drafts_list", {}, null, 30)'))
        self.assertNotIn("refresh_invalid", " ".join(accepted.get("errors") or []), "a literal 30 s refresh is allowed")
        return "refresh <30 s / computed, defaults and query→query args rejected"

    @vcheck
    def test_markup_and_script_urls_never_accepted_as_executable(self):
        """NC11 (parser side): markup and script URLs are only ever string literals; no raw-HTML component can validate.
        Rendering them as inert text / refusing the link is asserted in the browser (e2e:xss)."""
        for text in ('"<script>alert(1)</script>"', '"<img src=x onerror=alert(1)>"', '"javascript:alert(1)"'):
            result = self.validate(self.with_root_child(f"t = {text}"))
            if result.get("accepted"):
                self.assertTrue(set(result["componentNames"]) <= set(self.meta["policy"]["allowedComponents"]))
        for component in ("Html", "RawHtml", "Script", "Iframe", "DangerouslySetInnerHTML"):
            self.rejected(self.with_root_child(f'x = {component}("<b>x</b>")'), "component", "unknown")
        return "markup strings stay literals; raw-HTML-like components are unknown"

    @vcheck
    def test_unexplained_deletion_in_patch_rejected(self):
        """`x = )` parses to Null and would silently delete `x` in mergeStatements; the seam must flag it."""
        child = next((line.split(" = ", 1)[0] for line in self.valid.split("\n")[1:] if " = " in line), None)
        base = self.valid if child else self.valid + "\n$g = 1"
        self.rejected(f"{child or '$g'} = )", "delet", "patch", "unexplained", mode="patch", base=base)
        return "malformed RHS deletion flagged in patch mode"

    @vcheck
    def test_library_skew_rejected(self):
        result = self.validate(self.valid, library_hash="0" * 64)
        self.assertFalse(result.get("accepted"), "a candidate validated for another library build must not be accepted")
        return "library hash mismatch rejected"

    def raw(self, body: bytes, *, key="v1", stamp=None, signature=None, content_type="application/json"):
        from postriff_phase2.agent_runtime_v2 import ui_validator
        stamp = stamp or str(int(time.time()))
        headers = {"Content-Type": content_type, "X-Rafii-Validator-Key": key, "X-Rafii-Validator-Timestamp": stamp,
                   "X-Rafii-Validator-Signature": signature or ui_validator.sign(self.secret, stamp, body)}
        return self.api.request("POST", "/internal/agent-ui/validate", body=body, headers=headers)

    @vcheck
    def test_signed_route_refuses_unsigned_skewed_or_foreign_requests(self):
        body = json.dumps({"v": "v1", "contractVersion": "rafii-genui/1", "mode": "generate", "baseSource": None, "candidateSource": self.valid,
                           "libraryHash": self.meta["libraryHash"], "policy": self.meta["policy"], "scope": {"workspaceId": "a", "artifactId": "b", "attemptId": "c"}}).encode()
        self.assertEqual(self.raw(body).status, 200)
        self.assertEqual(self.raw(body, signature="0" * 64).status, 401)
        self.assertEqual(self.raw(body, key="v0").status, 401)
        self.assertEqual(self.raw(body, stamp=str(int(time.time()) - 600)).status, 401)
        self.assertEqual(self.raw(body + b" ", signature=self.raw_signature(body)).status, 401)
        self.assertEqual(self.raw(body, content_type="text/plain").status, 415)
        foreign = json.loads(body)
        foreign["contractVersion"] = "rafii-genui/0"
        self.assertEqual(self.raw(json.dumps(foreign).encode()).status, 400)
        unsigned = self.api.request("POST", "/internal/agent-ui/validate", body=body, headers={"Content-Type": "application/json"})
        self.assertEqual(unsigned.status, 401)
        return "unsigned, bad signature, stale timestamp, tampered body, wrong type and contract refused"

    def raw_signature(self, body):
        from postriff_phase2.agent_runtime_v2 import ui_validator
        return ui_validator.sign(self.secret, str(int(time.time())), body)


def tearDownModule():
    RECORD.write()
