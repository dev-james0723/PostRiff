"""Fixture model provider for the CI acceptance harness: a loopback OpenAI-compatible endpoint (labelled fixture, never
evidence of live model quality).

Why at the network boundary: lane B's real presenter, stream, repair, metering and settlement code runs unchanged against
it (AsyncOpenAI(max_retries=0) with RAFII_AGENT_BASE_URL pointed here), so the acceptance corpus tests what ships, not a
replaced Python function. It also gives an independent count of provider requests (`GET /__stats`): "zero provider attempts
on passive reopen / replay / query" is asserted from the boundary, not from the code under test.

    POST /v1/responses           Responses API, `stream: true` -> SSE (response.created … output_text.delta … completed+usage)
    POST /v1/chat/completions    Chat Completions, `stream: true` -> chunks + a final usage chunk + [DONE]
    GET  /__stats                {"requests": n, "byPath": {...}, "faultsUsed": [...]}   (test control, loopback only)
    POST /__fault                {"fault": name, "count": n}  arms the next n generations; {"fault": null} disarms
    POST /__seen                 {"markers": [...]} -> {"seen": {marker: number of provider requests that contained it}}
    POST /__reset                clears counters, faults and the in-memory request bodies

Three kinds of request reach it, told apart by their shape:
* agent requests (function tools present): the Manager and its specialists. They are answered by the existing QA script
  (agent_runtime_v2.harness.manager_step / specialist_step — the same decisions the RAFII_AGENT_HARNESS ScriptedModel makes), so
  the turn runs through the REAL metered path (reservation, usage, settlement) instead of the scripted, unbilled one;
* structured helper requests (no tools, `text.format` json_schema), e.g. follow-up chips: the minimal object the schema allows;
* presenter requests (no tools, free text): deterministic openui-lang source, streamed.

Faults (presenter requests only): malformed | unknown_component | truncated | error | reset | no_usage | slow | hang | xss.
The generated source is a deterministic, valid openui-lang tree built from lane C's generated schema (D-A30); without that
schema it is the bare root, which a real validator may reject — then the corpus records BLOCKED, never a pass.
"""
from __future__ import annotations

import json
import re
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GENERATED = ROOT / "src/postriff_phase2/agent_runtime_v2/generated"
FAULTS = ("malformed", "unknown_component", "truncated", "error", "reset", "no_usage", "slow", "hang", "xss")
# Distinct scripts on purpose: CJK, emoji with ZWJ and RTL make every multi-byte boundary appear in the deltas.
TEXTS = ("Rafii fixture view: progressive rendering 第一段", "第二段：廣東話、普通话 and emoji 🎹🎶 👩‍💻", "Third part مرحبا — fixture provider, not a model")


def _schema(library="consumer"):
    try:
        assets = json.loads((GENERATED / "openui-assets.json").read_text(encoding="utf-8"))
        lib = (assets.get("libraries") or {}).get(library) or {}
        schema = json.loads((GENERATED / (lib.get("schemaFile") or f"{library}.schema.json")).read_text(encoding="utf-8"))
        # C's generator keys components under top-level `properties` (D-A30 schema file); older shapes used $defs.
        return lib, schema.get("$defs") or schema.get("definitions") or schema.get("properties") or {}
    except (OSError, ValueError):
        return {}, {}


def _lit(prop, text):
    if "default" in prop:
        return json.dumps(prop["default"], ensure_ascii=False)
    if prop.get("enum"):
        return json.dumps(prop["enum"][0], ensure_ascii=False)
    kind = prop.get("type")
    if isinstance(kind, list):
        kind = next((k for k in kind if k != "null"), "null")
    for key in ("anyOf", "oneOf"):
        if not kind and prop.get(key):
            options = [p for p in prop[key] if p.get("type") != "null"] or prop[key]
            return _lit(options[0], text)
    return {"string": json.dumps(text, ensure_ascii=False), "number": "1", "integer": "1", "boolean": "false", "array": "[]", "object": "{}"}.get(kind, "null")


def _args(spec, children=None, text="Rafii"):
    props = spec.get("properties") or {}
    required = [r for r in spec.get("required") or [] if r in props]
    last = max([list(props).index(r) for r in required] or [-1])
    out, placed = [], False
    for index, (_key, prop) in enumerate(props.items()):
        is_children = children is not None and not placed and (prop.get("type") == "array" or "items" in prop)
        if index > last and not is_children:
            break
        if is_children:
            out.append("[" + ", ".join(children) + "]")
            placed = True
        else:
            out.append(_lit(prop, text))
    return ", ".join(out)


TEXT_COMPONENTS = ("Text", "Commentary", "Paragraph", "Heading")


def allowed_components(instructions: str) -> set | None:
    """The per-view component list lane B appends to the instructions ("Use only these components: A, B."), if any."""
    match = re.search(r"Use only these components: ([^\n]+?)\.?(?:\n|$)", instructions or "")
    return {c.strip() for c in match.group(1).split(",") if c.strip()} if match else None


def build_source(texts=TEXTS, library="consumer", *, allowed=None, with_input=False) -> str:
    """root first (hoisting), then children. With `with_input` (and TextField allowed) one labelled text field bound to a
    declared $var is added, so typing/state checks have a real input. Falls back to the bare root without C's schema."""
    lib, defs = _schema(library)
    root = lib.get("root") or "RafiiRoot"
    usable = (lambda name: name in defs and (allowed is None or name in allowed))
    text_component = next((c for c in TEXT_COMPONENTS if usable(c)), None)
    if root not in defs:
        return f"root = {root}([])\n"
    if not text_component:
        return f"root = {root}({_args(defs[root], children=[])})\n"
    ids = [f"t{i + 1}" for i in range(len(texts))]
    field = with_input and usable("TextField")
    children = ids + (["f1"] if field else [])
    lines = [f"root = {root}({_args(defs[root], children=children)})"]
    if field:
        lines.append('$g_note = ""')
    lines += [f"{ident} = {text_component}({_args(defs[text_component], text=text)})" for ident, text in zip(ids, texts)]
    if field:
        lines.append('f1 = TextField("g_note", "Fixture note", $g_note)')
    return "\n".join(lines) + "\n"


def presenter_source(body: dict) -> str:
    """Generate → the full fixture view (with an input); repair → the plain text view; edit → a patch of the current view."""
    user = _text_of(body.get("input") if "input" in body else [m for m in body.get("messages") or [] if m.get("role") == "user"])
    allowed = allowed_components(str(body.get("instructions") or "") + "\n" + _text_of([m for m in body.get("messages") or [] if m.get("role") == "system"]))
    if 'kind="REJECTED_UI"' in user:
        return build_source(allowed=allowed)
    if 'kind="CURRENT_UI"' in user:
        current = user.split('kind="CURRENT_UI"', 1)[1].split("</source>", 1)[0]
        return build_patch(current) or build_source(allowed=allowed)
    return build_source(allowed=allowed, with_input=True)


_STATEMENT = re.compile(r"(?m)^([a-z][A-Za-z0-9_]*) = ([A-Z][A-Za-z0-9]*)\((\"(?:[^\"\\]|\\.)*\")")


def build_patch(prompt_input: str) -> str | None:
    """Patch mode: re-declare the last statement of the current source whose first argument is a string literal."""
    found = list(_STATEMENT.finditer(prompt_input or ""))
    for match in reversed(found):
        name, component, _first = match.groups()
        if name != "root" and component in TEXT_COMPONENTS:   # never a field host: its name is the person's form state
            _lib, defs = _schema()
            spec = defs.get(component)
            if spec is None:
                return f'{name} = {component}("Edited by the fixture provider ✎")\n'
            return f"{name} = {component}({_args(spec, text='Edited by the fixture provider ✎')})\n"
    return None


def _text_of(value) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(_text_of(v) for v in value)
    if isinstance(value, dict):
        if value.get("role") in ("system", "developer"):
            return ""
        return _text_of(value.get("content") if "content" in value else value.get("text", ""))
    return ""


def _chunks(text: str, parts: int = 6) -> list[str]:
    size = max(1, -(-len(text) // parts))
    return [text[i:i + size] for i in range(0, len(text), size)]


def _agent_of(tools: list) -> str | None:
    names = {t.get("name") for t in tools if isinstance(t, dict)}
    if not names:
        return None
    if any(str(n).startswith("ask_") for n in names):
        return "manager"
    if "draft_create" in names:
        return "content"
    if names & {"image_generate", "image_analyze"}:
        return "creative"
    if names & {"campaign_get", "campaign_link"}:
        return "campaign"
    return "manager"


def agent_output(body: dict) -> list:
    """Output items for a Manager/specialist request, decided by the QA script on the request's own input items."""
    from types import SimpleNamespace
    from postriff_phase2.agent_runtime_v2 import harness
    agent = _agent_of(body.get("tools") or [])
    raw = body.get("input")
    items = raw if isinstance(raw, list) else [{"role": "user", "content": raw or ""}]
    step = harness.manager_step if agent == "manager" else harness.specialist_step(agent)
    out = []
    for item in step(SimpleNamespace(input=items)):
        dumped = item.model_dump(mode="json", exclude_none=True) if hasattr(item, "model_dump") else dict(item)
        out.append(dumped)
    return out


def minimal_json(schema: dict, defs: dict | None = None, depth: int = 0):
    """The smallest value a JSON schema accepts (required properties only; empty arrays; first enum)."""
    defs = defs if defs is not None else (schema.get("$defs") or schema.get("definitions") or {})
    if depth > 8 or not isinstance(schema, dict):
        return None
    if "$ref" in schema:
        return minimal_json(defs.get(schema["$ref"].rsplit("/", 1)[-1], {}), defs, depth + 1)
    for key in ("anyOf", "oneOf", "allOf"):
        if schema.get(key):
            nulls = [o for o in schema[key] if isinstance(o, dict) and o.get("type") == "null"]
            return None if nulls else minimal_json(schema[key][0], defs, depth + 1)
    if schema.get("enum"):
        return schema["enum"][0]
    kind = schema.get("type")
    if isinstance(kind, list):
        if "null" in kind:
            return None
        kind = kind[0]
    if kind == "object" or "properties" in schema:
        props = schema.get("properties") or {}
        return {k: minimal_json(v, defs, depth + 1) for k, v in props.items() if k in (schema.get("required") or list(props))}
    return {"array": [], "string": "", "integer": 0, "number": 0, "boolean": False, "null": None}.get(kind)


class State:
    def __init__(self):
        self.lock = threading.Lock()
        self.requests = 0
        self.by_path: dict = {}
        self.faults: list = []           # [(name, remaining)]
        self.used: list = []
        self.models: list = []
        self.bodies: list = []           # (kind, raw request body), in memory only (loopback test process), bounded
        self.by_kind: dict = {}          # agent | structured | presenter

    def take_fault(self):
        with self.lock:
            while self.faults:
                name, remaining = self.faults[0]
                if remaining <= 0:
                    self.faults.pop(0)
                    continue
                self.faults[0] = (name, remaining - 1)
                self.used.append(name)
                return name
        return None


class Handler(BaseHTTPRequestHandler):
    server_version = "RafiiFixtureProvider/1"
    protocol_version = "HTTP/1.1"
    state: State = None
    delay = 0.35

    def log_message(self, *_):
        pass

    def _send_json(self, status, body):
        raw = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _read(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            return json.loads(raw.decode("utf-8")) if raw else {}
        except ValueError:
            return {}

    def do_GET(self):
        if self.path == "/__stats":
            with self.state.lock:
                return self._send_json(200, {"requests": self.state.requests, "byPath": dict(self.state.by_path), "byKind": dict(self.state.by_kind),
                                             "presenterRequests": self.state.by_kind.get("presenter", 0), "faultsUsed": list(self.state.used),
                                             "faultsArmed": [list(f) for f in self.state.faults], "models": list(self.state.models)[-20:]})
        return self._send_json(404, {"error": {"message": "unknown fixture route"}})

    def do_POST(self):
        body = self._read()
        if self.path == "/__fault":
            fault = body.get("fault")
            with self.state.lock:
                if fault is None:
                    self.state.faults.clear()
                elif fault in FAULTS:
                    self.state.faults.append((fault, int(body.get("count") or 1)))
                else:
                    return self._send_json(400, {"error": "unknown fault"})
            return self._send_json(200, {"ok": True})
        if self.path == "/__reset":
            with self.state.lock:
                self.state.requests, self.state.by_path, self.state.faults, self.state.used, self.state.models, self.state.bodies = 0, {}, [], [], [], []
                self.state.by_kind = {}
            return self._send_json(200, {"ok": True})
        if self.path == "/__seen":
            markers = [str(m) for m in body.get("markers") or [] if isinstance(m, str) and m][:20]
            kinds = set(body.get("kinds") or ["presenter"])
            with self.state.lock:
                seen = {m: sum(1 for kind, raw in self.state.bodies if kind in kinds and m in raw) for m in markers}
            return self._send_json(200, {"seen": seen, "requests": sum(1 for kind, _ in self.state.bodies if kind in kinds), "kinds": sorted(kinds)})
        path = self.path.split("?", 1)[0].rstrip("/")
        if not path.endswith(("/responses", "/chat/completions")):
            return self._send_json(404, {"error": {"message": "the fixture provider serves /responses and /chat/completions only"}})
        fmt = ((body.get("text") or {}).get("format") or {}) if isinstance(body.get("text"), dict) else {}
        agent = bool([t for t in body.get("tools") or [] if isinstance(t, dict) and t.get("type") == "function"])
        structured = fmt.get("type") == "json_schema" or (body.get("response_format") or {}).get("type") == "json_schema"
        kind = "agent" if agent else "structured" if structured else "presenter"
        with self.state.lock:
            self.state.requests += 1
            self.state.by_path[path] = self.state.by_path.get(path, 0) + 1
            self.state.by_kind[kind] = self.state.by_kind.get(kind, 0) + 1
            self.state.models.append(str(body.get("model") or ""))
            self.state.bodies = (self.state.bodies + [(kind, json.dumps(body, ensure_ascii=False))])[-300:]
        if agent:
            return self._agent(path, body)
        if structured:
            schema = fmt.get("schema") or ((body.get("response_format") or {}).get("json_schema") or {}).get("schema") or {}
            return self._structured(path, body, json.dumps(minimal_json(schema), ensure_ascii=False))
        fault = self.state.take_fault()
        if fault == "error":
            return self._send_json(500, {"error": {"message": "fixture provider error", "type": "server_error"}})
        source = presenter_source(body)
        if fault == "malformed":
            source = "root = RafiiRoot(\nchart = )\n@Run(\n"
        elif fault == "unknown_component":
            source = "root = NotAComponent([])\n"
        elif fault == "xss":
            source = source.replace(TEXTS[0], "<img src=x onerror=alert(1)> javascript:alert(1)") if TEXTS[0] in source else source
        prompt_tokens = max(1, len(json.dumps(body)) // 4)
        usage_tokens = (prompt_tokens, max(1, len(source) // 4))
        model = str(body.get("model") or "fixture")
        if not body.get("stream"):
            return self._send_json(200, self._complete_body(path, model, source, usage_tokens, fault))
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        try:
            if path.endswith("/responses"):
                self._stream_responses(model, source, usage_tokens, fault)
            else:
                self._stream_chat(model, source, usage_tokens, fault)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _usage(self, body, text):
        prompt = max(1, len(json.dumps(body)) // 4)
        return {"input_tokens": prompt, "input_tokens_details": {"cached_tokens": 0}, "output_tokens": max(1, len(text) // 4),
                "output_tokens_details": {"reasoning_tokens": 0}, "total_tokens": prompt + max(1, len(text) // 4)}

    def _response(self, body, output, text):
        return {"id": "resp_fx_" + uuid.uuid4().hex[:16], "object": "response", "created_at": int(time.time()), "model": str(body.get("model") or "fixture"),
                "status": "completed", "output": output, "parallel_tool_calls": True, "tool_choice": "auto", "tools": [], "error": None,
                "incomplete_details": None, "instructions": None, "metadata": {}, "text": body.get("text") or {"format": {"type": "text"}},
                "truncation": "disabled", "usage": self._usage(body, text)}

    def _agent(self, path, body):
        """Manager / specialist turn step (never faulted: faults target the presenter)."""
        if not path.endswith("/responses"):
            return self._send_json(400, {"error": {"message": "the fixture answers agent requests on the Responses API only"}})
        try:
            output = agent_output(body)
        except Exception as error:  # noqa: BLE001 — surface as a provider error the runtime handles
            return self._send_json(500, {"error": {"message": f"fixture agent script failed: {type(error).__name__}", "type": "server_error"}})
        text = json.dumps(output, ensure_ascii=False)
        response = self._response(body, output, text)
        if not body.get("stream"):
            return self._send_json(200, response)
        self._stream_items(response)

    def _structured(self, path, body, text):
        if path.endswith("/chat/completions"):
            return self._send_json(200, {"id": "chatcmpl-fx", "object": "chat.completion", "created": int(time.time()), "model": str(body.get("model") or ""),
                                         "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
                                         "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}})
        part = {"type": "output_text", "text": text, "annotations": []}
        response = self._response(body, [{"id": "msg_fx_s", "type": "message", "status": "completed", "role": "assistant", "content": [part]}], text)
        if not body.get("stream"):
            return self._send_json(200, response)
        self._stream_items(response)

    def _stream_items(self, response):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        seq = 0
        self._emit("response.created", {"type": "response.created", "sequence_number": seq, "response": {**response, "status": "in_progress", "output": []}})
        for index, item in enumerate(response["output"]):
            seq += 1
            self._emit("response.output_item.added", {"type": "response.output_item.added", "sequence_number": seq, "output_index": index, "item": item})
            seq += 1
            self._emit("response.output_item.done", {"type": "response.output_item.done", "sequence_number": seq, "output_index": index, "item": item})
        self._emit("response.completed", {"type": "response.completed", "sequence_number": seq + 1, "response": response})

    def _emit(self, event, data):
        frame = (f"event: {event}\n" if event else "") + "data: " + json.dumps(data, ensure_ascii=False) + "\n\n"
        self.wfile.write(frame.encode("utf-8"))
        self.wfile.flush()

    def _pause(self, fault, index):
        time.sleep(1.5 if fault == "slow" else 75 if fault == "hang" and index == 1 else self.delay)

    def _stream_responses(self, model, source, usage, fault):
        rid, mid, seq = "resp_fx_" + uuid.uuid4().hex[:16], "msg_fx_" + uuid.uuid4().hex[:16], 0
        created = int(time.time())
        base = {"id": rid, "object": "response", "created_at": created, "model": model, "output": [], "parallel_tool_calls": False, "tool_choice": "none",
                "tools": [], "status": "in_progress", "error": None, "incomplete_details": None, "instructions": None, "metadata": {}, "temperature": None,
                "top_p": None, "text": {"format": {"type": "text"}}, "truncation": "disabled", "usage": None}

        def nxt():
            nonlocal seq
            seq += 1
            return seq - 1
        self._emit("response.created", {"type": "response.created", "sequence_number": nxt(), "response": base})
        self._emit("response.output_item.added", {"type": "response.output_item.added", "sequence_number": nxt(), "output_index": 0,
                                                   "item": {"id": mid, "type": "message", "status": "in_progress", "role": "assistant", "content": []}})
        self._emit("response.content_part.added", {"type": "response.content_part.added", "sequence_number": nxt(), "item_id": mid, "output_index": 0,
                                                    "content_index": 0, "part": {"type": "output_text", "text": "", "annotations": []}})
        pieces = _chunks(source)
        for index, piece in enumerate(pieces):
            if fault == "truncated" and index == len(pieces) // 2:
                return                                   # connection closes mid-source: no done, no completed, no usage
            if fault == "reset" and index == len(pieces) // 2:
                self.connection.shutdown(2)
                return
            self._emit("response.output_text.delta", {"type": "response.output_text.delta", "sequence_number": nxt(), "item_id": mid, "output_index": 0,
                                                       "content_index": 0, "delta": piece, "logprobs": []})
            self._pause(fault, index)
        part = {"type": "output_text", "text": source, "annotations": []}
        self._emit("response.output_text.done", {"type": "response.output_text.done", "sequence_number": nxt(), "item_id": mid, "output_index": 0,
                                                  "content_index": 0, "text": source, "logprobs": []})
        self._emit("response.content_part.done", {"type": "response.content_part.done", "sequence_number": nxt(), "item_id": mid, "output_index": 0,
                                                   "content_index": 0, "part": part})
        item = {"id": mid, "type": "message", "status": "completed", "role": "assistant", "content": [part]}
        self._emit("response.output_item.done", {"type": "response.output_item.done", "sequence_number": nxt(), "output_index": 0, "item": item})
        done = {**base, "status": "completed", "output": [item],
                "usage": None if fault == "no_usage" else {"input_tokens": usage[0], "input_tokens_details": {"cached_tokens": 0}, "output_tokens": usage[1],
                                                          "output_tokens_details": {"reasoning_tokens": 0}, "total_tokens": usage[0] + usage[1]}}
        self._emit("response.completed", {"type": "response.completed", "sequence_number": nxt(), "response": done})

    def _stream_chat(self, model, source, usage, fault):
        cid, created = "chatcmpl-fx" + uuid.uuid4().hex[:12], int(time.time())
        pieces = _chunks(source)
        for index, piece in enumerate(pieces):
            if fault in ("truncated", "reset") and index == len(pieces) // 2:
                return
            delta = {"content": piece, **({"role": "assistant"} if index == 0 else {})}
            self._emit(None, {"id": cid, "object": "chat.completion.chunk", "created": created, "model": model,
                              "choices": [{"index": 0, "delta": delta, "finish_reason": None}]})
            self._pause(fault, index)
        self._emit(None, {"id": cid, "object": "chat.completion.chunk", "created": created, "model": model, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]})
        if fault != "no_usage":
            self._emit(None, {"id": cid, "object": "chat.completion.chunk", "created": created, "model": model, "choices": [],
                              "usage": {"prompt_tokens": usage[0], "completion_tokens": usage[1], "total_tokens": usage[0] + usage[1]}})
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()

    def _complete_body(self, path, model, source, usage, fault):
        if path.endswith("/responses"):
            part = {"type": "output_text", "text": source, "annotations": []}
            return {"id": "resp_fx_" + uuid.uuid4().hex[:16], "object": "response", "created_at": int(time.time()), "model": model, "status": "completed",
                    "output": [{"id": "msg_fx", "type": "message", "status": "completed", "role": "assistant", "content": [part]}], "parallel_tool_calls": False,
                    "tool_choice": "none", "tools": [], "usage": None if fault == "no_usage" else {"input_tokens": usage[0], "output_tokens": usage[1],
                                                                                                   "total_tokens": sum(usage), "input_tokens_details": {"cached_tokens": 0},
                                                                                                   "output_tokens_details": {"reasoning_tokens": 0}}}
        return {"id": "chatcmpl-fx", "object": "chat.completion", "created": int(time.time()), "model": model,
                "choices": [{"index": 0, "message": {"role": "assistant", "content": source}, "finish_reason": "stop"}],
                **({} if fault == "no_usage" else {"usage": {"prompt_tokens": usage[0], "completion_tokens": usage[1], "total_tokens": sum(usage)}})}


def start(port: int = 0, delay: float = 0.35):
    """Start on 127.0.0.1 in a daemon thread. Returns (server, base_url_with_v1, state)."""
    state = State()
    handler = type("FixtureHandler", (Handler,), {"state": state, "delay": delay})
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True, name="fixture-provider").start()
    return server, f"http://127.0.0.1:{server.server_address[1]}/v1", state


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=4540)
    args = parser.parse_args()
    srv, url, _ = start(args.port)
    print(json.dumps({"fixtureProvider": url}), flush=True)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        srv.shutdown()
