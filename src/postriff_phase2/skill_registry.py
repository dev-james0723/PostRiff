"""Rafii capability registry (adaptive coworker spec §4-§7; architecture lock R1/R2/R4).

One machine-readable source of truth, `skills/rafii-registry.json`, classifies every product capability as exactly
one kind (knowledge, workflow, tool, policy, evaluator), pins its semantic version and content hash, names the code
that consumes or implements it, and says how (or whether) a workspace may personalise it. Global capabilities are
product-owned and immutable at runtime: nothing here writes a skill file, and a content change without a version
bump fails `check()`.

`check()` is what CI runs (tests/test_rafii_skill_registry.py, scripts/rafii_skill_registry.py). It fails on:
an unclassified or duplicate skill; a wrong hash; a bad or incompatible version; a tool without a registered typed
tool; a policy or evaluator without a resolvable implementation; a default skill with no proven runtime consumer
(the consumer is executed, not trusted); private material in the default bundle or in the hosted build; and
customer-specific (James Au) content in any default skill file.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

KINDS = ("knowledge", "workflow", "tool", "policy", "evaluator")
PERSONALIZATION = ("overlay_only", "none", "protected")
DEPRECATION = ("active", "dormant", "deprecated")
RISKS = ("low", "medium", "high")
REGISTRY_FILE = "rafii-registry.json"
SCHEMA = "rafii.capability-registry.v1"
PRODUCT_PREFIXES = ("postriff-", "rafii-")
_SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
_ID = re.compile(r"^[a-z0-9][a-z0-9.-]{1,80}$")
REQUIRED = ("id", "version", "kind", "sha256", "description", "intents", "platforms", "formats", "locales", "agents",
            "consumers", "tool", "policy", "evaluator", "personalization", "risk", "tests", "deprecation", "private",
            "hashSources")

# Markers of one specific person's identity, biography, projects, career, tone, visual identity or private setup.
# A default skill must be usable by any customer, so none of these may appear in a file the hosted binder or the
# compiler can reach. Generic domain words (e.g. "music rights" on a platform) are allowed; the patterns target the
# person, their projects and their private environment.
LEAK_PATTERNS = (
    (r"\bjames\b", "a person's name (James)"),
    (r"\bau\s+studio\b|james[- ]au", "a person's studio/brand name"),
    (r"arnaldo|cohen\b", "a person's teacher"),
    (r"\bpianist\b|\bpiano\s+(?:student|teacher|practice\s+journal)", "a person's career"),
    (r"\bd[\s-]?festival\b|fantasia\s+(?:piano|festival|competition)|my\s+best\s+life\b|hkfimm", "a person's projects"),
    (r"sing-sing-\d+", "a personal account handle"),
    (r"/users/[a-z0-9_.-]+", "a local home-directory path"),
    (r"127\.0\.0\.1:\d{3,5}|localhost:\d{3,5}", "a local service address"),
    (r"builder-musician|musician-builder", "a person's self-description"),
    (r"natural\s+cantonese-english\s+mixing", "one person's fixed voice anchor"),
    (r"reflective,\s*specific,\s*calm,\s*curious,\s*candid", "one person's fixed voice adjectives"),
)
_LEAKS = [(re.compile(pattern, re.I), label) for pattern, label in LEAK_PATTERNS]


def skills_root():
    from .skills import default_root
    root = default_root()
    return root if root is not None else Path(__file__).resolve().parents[2] / "skills"


def repo_root():
    return Path(__file__).resolve().parents[2]


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    """A JSON-stable form of a declarative object (dicts, tuples, sets, frozensets, strings, numbers)."""
    if isinstance(value, dict):
        return {str(k): canonical(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if isinstance(value, (set, frozenset)):
        return sorted(canonical(v) for v in value)
    if isinstance(value, (list, tuple)):
        return [canonical(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if hasattr(value, "__dict__") and not callable(value):
        return canonical({k: v for k, v in vars(value).items() if not k.startswith("_")})
    raise TypeError(f"not a declarative value: {type(value).__name__}")


def digest(value):
    return _sha256(json.dumps(canonical(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode())


def resolve(ref):
    """`package.module:attr.sub` → the object. Raises LookupError when it does not resolve."""
    if not isinstance(ref, str) or ":" not in ref:
        raise LookupError(f"bad reference {ref!r}")
    module_name, _, attribute = ref.partition(":")
    try:
        target = importlib.import_module(module_name)
    except Exception as error:  # noqa: BLE001 - the reason is reported, not swallowed
        raise LookupError(f"{ref}: module does not import ({type(error).__name__}: {error})") from error
    for part in attribute.split("."):
        if not hasattr(target, part):
            raise LookupError(f"{ref}: {part} not found")
        target = getattr(target, part)
    return target


def skill_dir_hash(path):
    """sha256 over every file in a skill package (relative path + file hash), sorted; nothing is executed."""
    path = Path(path)
    parts = []
    for file in sorted(p for p in path.rglob("*") if p.is_file() and "__pycache__" not in p.parts and p.name != ".DS_Store"):
        parts.append(f"{file.relative_to(path).as_posix()}:{_sha256(file.read_bytes())}")
    return _sha256("\n".join(parts).encode())


def registered_tools():
    """Every typed tool the runtime can execute: the Agent Runtime v2 registry after the product's tools register."""
    from .agent_runtime_v2 import domain_tools, tool_adapter
    importlib.import_module(".agent_runtime_v2.specialists", __package__)  # importing it registers web_research
    domain_tools.ensure_registered()
    from .coworker import agent_tools
    agent_tools.register()
    return tool_adapter.REGISTRY


def tool_digest(name, tools=None):
    tools = registered_tools() if tools is None else tools
    tool = tools[name]
    contract = {k: getattr(tool.spec, k) for k in ("name", "effect", "permission", "approval", "voice", "idempotent", "tenant")}
    schema = tool.schema or {}
    shape = {"required": sorted(schema.get("required") or []),
             "properties": {k: (v or {}).get("type") for k, v in sorted((schema.get("properties") or {}).items())}}
    return digest({"spec": contract, "schema": shape})


MANIFEST_EXCLUDED = ("sha256", "lockedVersion")


def manifest_digest(entry):
    """The declared contract of a code-backed capability (its implementation references, scope and version)."""
    return digest({k: v for k, v in entry.items() if k not in MANIFEST_EXCLUDED})


def source_hash(source, root=None, tools=None, entry=None):
    """One hash source → sha256. Types: skill (package directory), object (a declarative value in code),
    file (a data file in the repository), tool (a registered typed tool's spec + schema), manifest (the entry's own
    declared contract, for code-backed capabilities with no declarative table of their own)."""
    kind = source.get("type")
    if kind == "manifest":
        if entry is None:
            raise LookupError("a manifest hash needs its entry")
        return manifest_digest(entry)
    if kind == "skill":
        base = Path(root or skills_root()) / source["id"]
        if not (base / "SKILL.md").is_file():
            raise LookupError(f"skill package {source['id']} is not installed")
        return skill_dir_hash(base)
    if kind == "object":
        return digest(resolve(source["ref"]))
    if kind == "file":
        path = repo_root() / source["path"]
        if not path.is_file():
            raise LookupError(f"{source['path']} does not exist")
        return _sha256(path.read_bytes())
    if kind == "tool":
        return tool_digest(source["name"], tools)
    raise LookupError(f"unknown hash source type {kind!r}")


HASH_PREFIX = "sha256:"


def entry_hash(entry, root=None, tools=None):
    """The recorded form is "sha256:<hex>" (a labelled digest, so secret scanners don't read it as a key)."""
    return HASH_PREFIX + _sha256("\n".join(source_hash(s, root, tools, entry) for s in entry["hashSources"]).encode())


def _semver(version):
    match = _SEMVER.match(version or "")
    return tuple(int(x) for x in match.groups()) if match else None


def satisfies(version, requirement):
    """`^1.2.0` (same major, ≥), `>=1.0.0`, `=1.0.0` or an exact version."""
    have = _semver(version)
    if have is None:
        return False
    if requirement.startswith("^"):
        want = _semver(requirement[1:])
        return want is not None and have[0] == want[0] and have >= want
    if requirement.startswith(">="):
        want = _semver(requirement[2:])
        return want is not None and have >= want
    want = _semver(requirement.lstrip("="))
    return want is not None and have == want


@dataclass
class Registry:
    entries: list
    path: Path
    root: Path
    by_id: dict = field(default_factory=dict)

    def __post_init__(self):
        self.by_id = {}
        for entry in self.entries:
            self.by_id.setdefault(entry.get("id"), entry)

    def get(self, capability_id):
        return self.by_id.get(capability_id)

    def defaults(self):
        """The default bundle: active, not private."""
        return [e for e in self.entries if e.get("deprecation") == "active" and not e.get("private")]

    def release(self):
        """One digest over (id, version, sha256) of every entry: the registry release a run pins."""
        return "reg_" + digest(sorted([e["id"], e["version"], e["sha256"]] for e in self.entries))[:24]

    def skill_entries(self):
        return [e for e in self.entries if any(s.get("type") == "skill" for s in e.get("hashSources", []))]


def load(root=None, path=None):
    root = Path(root) if root else skills_root()
    path = Path(path) if path else root / REGISTRY_FILE
    data = json.loads(path.read_text())
    if data.get("schema") != SCHEMA:
        raise ValueError(f"{path}: expected schema {SCHEMA}")
    return Registry(entries=list(data.get("capabilities") or []), path=path, root=root)


_CACHED = None


def default_registry():
    """The shipped registry, read once per process (it is immutable at runtime)."""
    global _CACHED
    if _CACHED is None:
        _CACHED = load()
    return _CACHED


def skill_files(registry, entry):
    files = []
    for source in entry.get("hashSources", []):
        if source.get("type") == "skill":
            base = registry.root / source["id"]
            files.extend(p for p in sorted(base.rglob("*")) if p.is_file() and p.suffix in (".md", ".json", ".txt", ".yaml", ".yml"))
    return files


def leak_findings(registry, entries=None):
    """Customer-specific content in default skill files: [(capability id, relative path, line, label)]."""
    findings = []
    for entry in entries if entries is not None else registry.defaults():
        for file in skill_files(registry, entry):
            # Provenance records of adapted upstream skills (commit locks, licence text) are not bound to any run.
            if file.name in ("source-lock.json", "LICENSE", "LICENSE-NOTICE.md", "source-review.md"):
                continue
            for number, line in enumerate(file.read_text("utf-8", "replace").splitlines(), 1):
                for pattern, label in _LEAKS:
                    if pattern.search(line):
                        findings.append((entry["id"], file.relative_to(registry.root).as_posix(), number, label))
    return findings


# Product copy every customer sees (the coworker UI and its email templates) must not carry one person's examples.
COPY_GLOBS = ("web/src/features/coworker/**/*.ts", "web/src/features/coworker/**/*.tsx", "web/src/lib/coworker/**/*.ts",
              "web/src/app/app/weekly/**/*.tsx", "web/src/app/app/workspace/personalization/**/*.tsx", "src/postriff_phase2/notifications/email_locales.json")
COPY_EXTRA = ((r"\bpiano\b|masterclass|slow\s+practice|recital", "one person's career example"),)
_COPY_LEAKS = _LEAKS + [(re.compile(pattern, re.I), label) for pattern, label in COPY_EXTRA]


def copy_leak_findings(repo_root):
    """Customer-specific examples in default product copy: [("product-copy", relative path, line, label)]."""
    root = Path(repo_root)
    findings = []
    for pattern in COPY_GLOBS:
        for file in sorted(root.glob(pattern)):
            for number, line in enumerate(file.read_text("utf-8", "replace").splitlines(), 1):
                for regex, label in _COPY_LEAKS:
                    if regex.search(line):
                        findings.append(("product-copy", file.relative_to(root).as_posix(), number, label))
    return findings


def production_workflows(src=None):
    """Workflow names production code enters: `workflow_context("…")` blocks and compile tasks with `"workflow": "…"`."""
    root = Path(src) if src else Path(__file__).resolve().parent
    names = set()
    for path in root.rglob("*.py"):
        if path.name in ("skill_registry.py",):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        names.update(re.findall(r"workflow_context\(\s*[\"']([a-z0-9-]+)[\"']", text))
        names.update(re.findall(r"[\"']workflow[\"']\s*:\s*[\"']([a-z0-9-]+)[\"']", text))
    return names


def run_probe(consumer, registry):
    """Execute a consumer's probe and return the capability ids it actually selected (or raise LookupError)."""
    ref, probe = consumer["ref"], consumer.get("probe") or {}
    resolve(ref)
    flags = probe.get("flags") or {}
    from .coworker import flags as flag_module
    previous = flag_module._values
    flag_module.attach({**(previous or {}), **flags})
    try:
        if ref == "postriff_phase2.skills:SkillLibrary.bind":
            from .skills import SkillLibrary
            from .skill_compiler import workflow_context
            library = SkillLibrary(registry.root)
            with workflow_context(probe.get("workflow")):
                bound = library.bind(probe.get("destinations") or [{"platform": "LinkedIn", "language": "en"}], probe.get("format"),
                                     probe.get("intent"), probe.get("contentType"), max_chars=probe.get("maxChars", 120_000))
            return [b["id"] for b in bound["bindings"]]
        if ref == "postriff_phase2.skill_compiler:compile":
            from .skill_compiler import compile as compile_context
            compiled = compile_context(dict(probe.get("task") or {}), registry=registry)
            return [s["id"] for s in compiled["selections"]]
        if ref.startswith("postriff_phase2.coworker.") and probe.get("selects"):
            # A coworker module that consumes a capability through the compiler or the writer: its declared
            # selection function is executed with the probe input.
            selector = resolve(probe["selects"])
            return list(selector(**(probe.get("input") or {})))
        raise LookupError(f"{ref}: no probe runner")
    finally:
        flag_module.attach(previous)


@dataclass
class Report:
    errors: list
    warnings: list
    totals: dict
    orphans: list
    exceptions: list
    leaks: list
    release: str

    @property
    def ok(self):
        return not self.errors

    def as_dict(self):
        return {"ok": self.ok, "release": self.release, "totals": self.totals, "orphanCount": len(self.orphans), "orphans": self.orphans,
                "documentedExceptions": self.exceptions, "jamesLeakage": {"findings": len(self.leaks), "items": [list(x) for x in self.leaks]},
                "errors": self.errors, "warnings": self.warnings}


def check(registry=None, verify_hashes=True, run_probes=True):
    registry = registry or load()
    errors, warnings, orphans, exceptions = [], [], [], []
    seen = {}
    tools = None
    try:
        tools = registered_tools()
    except Exception as error:  # noqa: BLE001
        errors.append(f"typed tool registry unavailable: {type(error).__name__}: {error}")
        tools = {}
    for entry in registry.entries:
        cid = entry.get("id")
        missing = [key for key in REQUIRED if key not in entry]
        if missing:
            errors.append(f"{cid}: missing fields {missing}")
            continue
        if not isinstance(cid, str) or not _ID.match(cid):
            errors.append(f"{cid!r}: invalid id")
        if cid in seen:
            errors.append(f"{cid}: duplicate id")
        seen[cid] = entry
        if entry["kind"] not in KINDS:
            errors.append(f"{cid}: kind {entry['kind']!r} is not one of {KINDS}")
        if _semver(entry["version"]) is None:
            errors.append(f"{cid}: version {entry['version']!r} is not semantic (x.y.z)")
        if entry["personalization"] not in PERSONALIZATION:
            errors.append(f"{cid}: personalization {entry['personalization']!r}")
        if entry["risk"] not in RISKS:
            errors.append(f"{cid}: risk {entry['risk']!r}")
        if entry["deprecation"] not in DEPRECATION:
            errors.append(f"{cid}: deprecation {entry['deprecation']!r}")
        if entry["deprecation"] != "active" and not entry.get("deprecationReason"):
            errors.append(f"{cid}: {entry['deprecation']} without a deprecationReason")
        if not entry["hashSources"]:
            errors.append(f"{cid}: no hash source")
        if entry["kind"] == "policy" and entry["personalization"] != "protected":
            errors.append(f"{cid}: a policy must be protected from personalisation")
        if entry["kind"] == "tool":
            names = [entry["tool"]] if isinstance(entry["tool"], str) else (entry["tool"] or [])
            if not names:
                if entry["deprecation"] == "active":
                    errors.append(f"{cid}: tool capability without a typed executable tool")
            for name in names:
                if name not in tools:
                    errors.append(f"{cid}: tool {name!r} is not a registered typed tool")
        for key in ("policy", "evaluator"):
            refs = entry[key] if isinstance(entry[key], list) else ([entry[key]] if entry[key] else [])
            if entry["kind"] == key and not refs:
                errors.append(f"{cid}: {key} capability without an implementation")
            for ref in refs:
                try:
                    resolve(ref)
                except LookupError as error:
                    errors.append(f"{cid}: {key} implementation {error}")
        for requirement in entry.get("requires") or []:
            other = registry.get(requirement.get("id"))
            if other is None:
                errors.append(f"{cid}: requires missing capability {requirement.get('id')}")
            elif not satisfies(other["version"], requirement.get("version", "")):
                errors.append(f"{cid}: requires {requirement['id']} {requirement.get('version')} but the registry has {other['version']}")
        if verify_hashes:
            try:
                actual = entry_hash(entry, registry.root, tools)
                if actual != entry["sha256"]:
                    errors.append(f"{cid}: content changed ({actual[:19]}… ≠ recorded {str(entry['sha256'])[:19]}…); bump the version and run scripts/rafii_skill_registry.py --lock")
            except (LookupError, KeyError, TypeError) as error:
                errors.append(f"{cid}: cannot hash ({error})")
    # Every installed skill package is classified exactly once.
    installed = sorted(p.name for p in registry.root.iterdir() if p.is_dir() and not p.name.startswith((".", "_")))
    classified = {s["id"] for e in registry.entries for s in e.get("hashSources", []) if s.get("type") == "skill"}
    classified |= {s["path"].split("/")[1] for e in registry.entries for s in e.get("hashSources", [])
                   if s.get("type") == "file" and s.get("path", "").startswith("skills/")}
    for name in installed:
        if name not in classified:
            errors.append(f"skills/{name}: installed but not classified in {REGISTRY_FILE}")
    # Private (customer-specific) packages: never default, never in the hosted build, never loadable by the hosted binder.
    ignore = (repo_root() / ".vercelignore").read_text() if (repo_root() / ".vercelignore").is_file() else ""
    for entry in registry.entries:
        if entry.get("private"):
            if entry["deprecation"] == "active" and entry.get("default", False):
                errors.append(f"{entry['id']}: private material cannot be in the default bundle")
            for source in entry["hashSources"]:
                if source.get("type") == "skill" and not source["id"].startswith(PRODUCT_PREFIXES):
                    if "skills/james-au-*/" not in ignore:
                        errors.append(f"{entry['id']}: private skill is not excluded from the hosted build (.vercelignore)")
        elif any(s.get("type") == "skill" and not s["id"].startswith(PRODUCT_PREFIXES) for s in entry["hashSources"]):
            errors.append(f"{entry['id']}: a default skill must use a product prefix {PRODUCT_PREFIXES}")
    # Proven consumers.
    for entry in registry.entries:
        if entry.get("private"):
            continue
        cid = entry["id"]
        if entry["deprecation"] != "active":
            exceptions.append({"id": cid, "state": entry["deprecation"], "reason": entry["deprecationReason"]})
            continue
        if not entry["consumers"]:
            orphans.append(cid)
            errors.append(f"{cid}: active default capability has no runtime consumer")
            continue
        proven = False
        for consumer in entry["consumers"]:
            try:
                resolve(consumer["ref"])
                for caller in consumer.get("callers") or []:
                    resolve(caller)
            except LookupError as error:
                errors.append(f"{cid}: consumer {error}")
                continue
            workflow = ((consumer.get("probe") or {}).get("workflow") or ((consumer.get("probe") or {}).get("task") or {}).get("workflow"))
            if workflow and workflow not in production_workflows():
                # A probe may only use a workflow some production code path actually enters; otherwise it proves nothing.
                errors.append(f"{cid}: probe workflow {workflow!r} is never entered by production code (workflow_context / compile task)")
                continue
            if entry["kind"] in ("knowledge", "workflow") and run_probes:
                try:
                    selected = run_probe(consumer, registry)
                except LookupError as error:
                    errors.append(f"{cid}: consumer probe failed ({error})")
                    continue
                if cid in selected:
                    proven = True
                else:
                    errors.append(f"{cid}: consumer {consumer['ref']} did not select it for its probe {consumer.get('probe')}")
            else:
                proven = True
        if not proven:
            orphans.append(cid)
    leaks = leak_findings(registry) + copy_leak_findings(registry.root.parent)
    for cid, path, line, label in leaks:
        errors.append(f"{cid}: customer-specific content in {path}:{line} ({label})")
    totals = {"registered": len(registry.entries), "default": len(registry.defaults()), "private": sum(1 for e in registry.entries if e.get("private")),
              "byKind": {kind: sum(1 for e in registry.entries if e.get("kind") == kind) for kind in KINDS},
              "deprecated": sum(1 for e in registry.entries if e.get("deprecation") == "deprecated"),
              "dormant": sum(1 for e in registry.entries if e.get("deprecation") == "dormant")}
    return Report(errors=errors, warnings=warnings, totals=totals, orphans=sorted(set(orphans)), exceptions=exceptions, leaks=leaks,
                  release=registry.release() if not any("missing fields" in e for e in errors) else "")


def lock(registry=None):
    """Recompute hashes. A changed hash is written only with a changed version; otherwise the lock refuses."""
    registry = registry or load()
    data = json.loads(registry.path.read_text())
    tools = registered_tools()
    refused, updated, unhashable = [], [], []
    for entry in data["capabilities"]:
        try:
            actual = entry_hash(entry, registry.root, tools)
        except (LookupError, KeyError, TypeError) as error:
            unhashable.append({"id": entry["id"], "error": str(error)})
            continue
        if actual == entry.get("sha256"):
            continue
        recorded_version = entry.get("lockedVersion")
        if entry.get("sha256") and recorded_version == entry["version"]:
            refused.append(entry["id"])
            continue
        entry["sha256"] = actual
        entry["lockedVersion"] = entry["version"]
        updated.append(entry["id"])
    if not refused:
        registry.path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    return {"updated": updated, "refused": refused, "unhashable": unhashable}


def validate_overlay(overlay, registry=None):
    """A user overlay may personalise only `overlay_only` capabilities, and never a policy key. Raises ValueError."""
    registry = registry or default_registry()
    target = overlay.get("capability")
    if target:
        entry = registry.get(target)
        if entry is None:
            raise ValueError(f"overlay targets unknown capability {target}")
        if entry["personalization"] != "overlay_only":
            raise ValueError(f"{target} cannot be personalised ({entry['personalization']})")
    protected = {"approval", "publish", "publishing", "permission", "permissions", "billing", "payment", "tenant", "security",
                 "rights", "usage_limit", "budget", "egress", "consent", "destructive", "verification", "hitl", "proposal"}
    keys = {str(k).lower() for k in (overlay.get("rule") or {}).keys()} | {str(overlay.get("ruleKey") or "").lower()}
    words = set(re.split(r"[^a-z]+", " ".join(keys)))
    if words & protected:
        raise ValueError(f"overlay tries to change protected policy: {sorted(words & protected)}")
    return True
