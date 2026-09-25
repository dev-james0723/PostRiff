"""Agent-aware intake, untrusted profile import, and portable reviewed packages."""
import base64
import copy
import hashlib
import io
import json
import posixpath
import re
import shutil
import stat
import subprocess
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

EVIDENCE = ["user_confirmed", "observed_in_approved_example", "agent_proposed_needs_confirmation", "conflicting", "unknown", "not_applicable"]
PRIVACY = ["public", "workspace_only", "private", "local_only", "excluded"]
RELATIONSHIP = [
    {"key": "experience", "question": "Do you already use AI as part of your work or creative life?", "options": ["Yes, regularly", "Sometimes", "I just started", "Not yet", "Set up PostRiff without importing another AI"]},
    {"key": "products", "question": "Which AI products have you used enough that they may know something useful about how you work?", "multiple": True, "options": ["ChatGPT / GPT", "Claude", "Gemini", "Grok", "Another AI", "None knows me yet"]},
    {"key": "duration", "question": "How long have you been working with the AI you know best?", "options": ["Less than one week", "One to four weeks", "One to six months", "Six to twelve months", "One to two years", "Two to three years", "More than three years", "Not sure"]},
    {"key": "frequency", "question": "How often do you normally work with it?", "options": ["Almost every day", "A few times a week", "About weekly", "A few times a month", "Occasional tasks"]},
    {"key": "depth", "question": "How well do you feel this AI understands the way you work?", "options": ["It mainly completes individual tasks", "It knows some recurring projects or preferences", "It usually understands my working style and voice", "It feels deeply calibrated to how I think and create", "I am not sure"]},
    {"key": "areas", "question": "What do you believe it understands well?", "multiple": True, "options": ["My writing or speaking voice", "My profession and expertise", "My recurring projects", "How I plan and make decisions", "My strengths and where support helps", "My audiences and content goals", "My boundaries or topics to avoid", "None of these reliably"]},
    {"key": "sources", "question": "Where might that understanding come from?", "multiple": True, "options": ["Conversation history", "Saved memory or custom instructions", "Selected project files or notes", "Personal skills or profile documents", "Repeated corrections and feedback", "I am not sure"]},
]
GUIDED = [
    {"key": "purpose", "section": "Audience and goals", "question": "What kind of work, knowledge, or experience would you like to share?"},
    {"key": "audience", "section": "Audience and goals", "question": "Who would you most like to help or reach?"},
    {"key": "subject", "section": "Identity and expertise", "question": "What subject, business, or offer should this agency draw from?", "modes": ["niche", "business", "hybrid"]},
    {"key": "layers", "section": "Identity and expertise", "question": "Which parts should this agency bring together?", "multiple": True, "options": ["My voice", "A niche", "A business"], "modes": ["hybrid"]},
    {"key": "speaker", "section": "Identity and expertise", "question": "Who should be speaking in this first post?", "options": ["My voice", "The business", "A neutral editor"], "modes": ["hybrid"]},
    {"key": "expertise", "section": "Identity and expertise", "question": "What are two or three things you know especially well?"},
    {"key": "strengths", "section": "Strengths and support", "question": "When people value your work, what do they usually value about it?"},
    {"key": "support", "section": "Strengths and support", "question": "Where would support help?", "hint": "Organizing ideas, careful research, clear writing, consistency, languages, or different channels."},
    {"key": "voiceTraits", "section": "Your voice", "question": "How would you like your writing to feel?", "hint": "Choose up to three qualities in your own words. Warm, direct, reflective, precise…"},
    {"key": "antiStyle", "section": "Your voice", "question": "What should Rafii avoid making you sound like?", "hint": "For example: overly corporate, motivational, aggressive, casual, certain, or wordy."},
    {"key": "languages", "section": "Language and culture", "question": "Which languages should Rafii understand?"},
    {"key": "culturalAudience", "section": "Language and culture", "question": "Which cultural audiences do you want to reach?", "hint": "Audience and language are separate choices. Leave either unknown if you prefer."},
    {"key": "workingStyle", "section": "Working style", "question": "When information is missing, how would you like Rafii to help?", "hint": "Ask one question, leave it unknown, draft around it, or describe your own approach."},
    {"key": "boundaries", "section": "Privacy and boundaries", "question": "Which topics or personal details should stay out of your content?", "hint": "Name categories to avoid, not secret values, identity numbers, addresses, or credentials."},
    {"key": "writingExample", "section": "Your voice", "question": "Is there a short piece of writing that sounds like you?", "hint": "Optional. Use writing you own. Choose whether an approved excerpt may be retained."},
    {"key": "selfDescription", "section": "Optional self-description", "question": "Do you use a self-description such as MBTI that helps explain how you work?", "hint": "Optional, self-described context only. Skip if it is not useful. No personality or clinical trait is inferred."},
]
FIELD_META = {q["key"]: q for q in GUIDED}
FIELD_META["publicName"] = {"key": "publicName", "section": "Identity and expertise", "question": "Public or working name"}
FIELD_META["tone"] = {"key": "tone", "section": "Your voice", "question": "Starting tone"}
ALLOWED_FILES = {"PROFILE.md", "VOICE.md", "WORKING_STYLE.md", "BRAND.md", "BOUNDARIES.md", "sources/manifest.json", "review.md", "skills/personal-voice/SKILL.md", "manifest.json", "profile.json", "README.md", "SKILL.md"}
SENSITIVE = re.compile(r"sk-[A-Za-z0-9_-]{8,}|gh[pousr]_[A-Za-z0-9]{8,}|(?:password|api.?key|passport|social.security|credit.card|ssn|date.of.birth|cookie|access.token)\s*[:=]|\b\d{3}-\d{2}-\d{4}\b|\b(?:\d[ -]?){13,19}\b", re.I)


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def text(value, limit=3000):
    if not isinstance(value, str) or len(value) > limit or "\0" in value:
        raise ValueError("Use plain text within the profile field limit.")
    if SENSITIVE.search(value):
        raise ValueError("Sensitive identifier or credential-like material was blocked. Remove it; describe only a relevant category or communication preference.")
    return value.strip()


def defaults():
    return {"schema": "postriff.personal-voice.v1", "stage": "relationship", "relationshipIndex": 0, "guideIndex": 0, "history": [], "relationship": {}, "guidedAnswers": {}, "transfer": "", "scope": None, "request": None, "candidate": [], "importReport": None, "inspection": None, "job": None, "approved": False, "startedAt": timestamp(), "reviewedAt": None}


def ensure(state):
    state.setdefault("profileSetup", defaults())
    return state["profileSetup"]


def questions(state):
    return [q for q in GUIDED if not q.get("modes") or state["brandHub"]["mode"] in q["modes"]]


def metadata():
    return {"relationship": RELATIONSHIP, "guided": GUIDED, "privacy": PRIVACY, "evidence": EVIDENCE}


def checkpoint(w):
    w["history"].append({k: w[k] for k in ("stage", "relationshipIndex", "guideIndex")})


def field(key, value, evidence="user_confirmed", privacy="local_only", source="direct-question", confidence="user-stated", self_described=False):
    if key not in FIELD_META:
        raise ValueError("The profile contains an unsupported field. Use the portable builder's field schema.")
    if privacy not in PRIVACY or evidence not in EVIDENCE:
        raise ValueError("A profile field has an unsupported evidence or privacy state.")
    if isinstance(value, list):
        value = ", ".join(text(v, 200) for v in value)
    value = text(value)
    if privacy == "excluded":
        value = ""
    return {"id": uuid.uuid4().hex, "key": key, "section": FIELD_META[key]["section"], "label": FIELD_META[key]["question"], "value": value, "evidence": evidence if value else "unknown", "privacy": privacy, "sourceIds": [source], "confidence": confidence, "decision": "pending" if value else "unknown", "selfDescribed": bool(self_described), "proposedAt": timestamp()}


def inspect_clis():
    result = []
    for executable, label in (("codex", "Codex CLI"), ("claude", "Claude Code CLI"), ("gemini", "Gemini CLI (supported routes only)")):
        path = shutil.which(executable)
        version = None
        if path:
            try:
                proc = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=5, cwd=str(Path(__file__).parent), stdin=subprocess.DEVNULL)
                match = re.search(r"\b\d+\.\d+\.\d+(?:[-.][\w.]+)?", proc.stdout[:500])
                version = match.group(0) if match else None
            except (OSError, subprocess.SubprocessError):
                pass
        result.append({"id": executable, "label": label, "detection": "detected" if path else "not_detected", "version": version, "versionSupport": "unqualified", "authentication": "not_checked", "sourceAccess": "not_granted", "execution": "not_run", "import": "not_imported", "checkedAt": timestamp()})
    return result


def validate_scope(raw):
    if not isinstance(raw, dict) or raw.get("confirmed") is not True:
        raise ValueError("Review and explicitly confirm the profile source scope first.")
    allowed = {"currentConversation", "memory", "conversations", "files", "examples", "questions", "retention", "confirmed"}
    if set(raw) - allowed:
        raise ValueError("This scope contains unsupported access permissions.")
    out = {k: raw.get(k) is True for k in ("currentConversation", "memory", "questions")}
    for key in ("conversations", "files", "examples"):
        values = raw.get(key, [])
        if not isinstance(values, list) or len(values) > 10:
            raise ValueError("Name at most ten specifically selected sources per category.")
        out[key] = [text(v, 250) for v in values if v]
        if any(v in ("*", "~", "/", "/Users") or re.fullmatch(r"/Users/[^/]+/?", v) or "all history" in v.lower() or "entire" in v.lower() for v in out[key]):
            raise ValueError("Choose specific sources, not a whole home directory or archive.")
    if raw.get("retention") not in ("references_only", "approved_excerpts"):
        raise ValueError("Choose an explicit retention preference.")
    if not any(out.values()):
        raise ValueError("Select at least one narrow source scope, or ask questions instead.")
    out.update({"retention": raw["retention"], "confirmedAt": timestamp()})
    return out


def prepare_request(s):
    w = ensure(s)
    if not w["scope"]:
        raise ValueError("Confirm the selected source scope first.")
    scope = w["scope"]
    manifest = {"request_schema": "postriff.profile-builder.v1", "selected_agent_product": w["relationship"].get("products", ["unknown"]), "selected_runtime": "unqualified_cli_request" if w["transfer"] == "cli" else "copy_paste", "postriff_workspace_alias": "private-agency", "agency_mode": s["brandHub"]["mode"], "target_languages": "unknown", "allowed_source_scope": {"current_conversation": scope["currentConversation"], "saved_agent_memory_if_accessible": scope["memory"], "selected_conversations_or_projects": scope["conversations"], "selected_files_or_directories": scope["files"], "selected_writing_examples": scope["examples"], "ask_questions": scope["questions"]}, "retention_preference": scope["retention"], "output_mode": "MARKDOWN_BLOCKS_AND_PROFILE_JSON", "output_location": "none", "actual_access_by_postriff": "none; user-managed handoff", "createdAt": timestamp()}
    canonical = json.dumps(manifest, sort_keys=True, ensure_ascii=False)
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    prompt = Path(__file__).with_name("profile_builder_prompt.md").read_text()
    substitutions = {"{{AI_PRODUCT_OR_UNKNOWN}}": ", ".join(manifest["selected_agent_product"]), "{{CLI_RUNTIME_OR_COPY_PASTE}}": manifest["selected_runtime"], "{{NON_SENSITIVE_WORKSPACE_ALIAS}}": "private-agency", "{{PERSONAL_BRAND_OR_ROLE_SPECIFIC_OR_BUSINESS_OR_HYBRID}}": s["brandHub"]["mode"], "{{LANGUAGE_LIST_OR_UNKNOWN}}": '"unknown"', "{{REFERENCES_ONLY_OR_APPROVED_EXCERPTS}}": scope["retention"], "{{FILES_IN_APPROVED_WORKDIR_OR_MARKDOWN_BLOCKS}}": "MARKDOWN_BLOCKS_AND_PROFILE_JSON", "{{APPROVED_WORKDIR_OR_NONE}}": "none"}
    # Replace the repeated placeholder through its owning YAML line, not by guessing its occurrence order.
    prompt = prompt.replace('current_conversation: {{YES_OR_NO}}', f'current_conversation: {str(scope["currentConversation"]).lower()}').replace('saved_agent_memory_if_accessible: {{YES_OR_NO}}', f'saved_agent_memory_if_accessible: {str(scope["memory"]).lower()}')
    for key, values in (("selected_conversations_or_projects", scope["conversations"]), ("selected_files_or_directories", scope["files"]), ("selected_writing_examples", scope["examples"])):
        prompt = prompt.replace(key + ": {{EXPLICIT_LIST_OR_NONE}}", key + ": " + json.dumps(values, ensure_ascii=False))
    for key, value in substitutions.items():
        prompt = prompt.replace(key, value.replace('"', '\\"'))
    companion = {"schema": "postriff.personal-voice.v1", "fields": [{"key": "voiceTraits", "value": "A supported candidate, or empty when unknown", "evidence": "agent_proposed_needs_confirmation", "privacy": "local_only", "sourceIds": ["S01"], "confidence": "low", "selfDescribed": False}], "sources": [{"id": "S01", "type": "authorized-source-category", "availability": "state actual access", "rawRetained": False}]}
    prompt += "\n\n## Private alpha import companion\n\nAlso return `profile.json` using this schema. Use only these field keys: " + ", ".join(FIELD_META) + ". Every field is independently reviewed after import. MBTI may use selfDescription only when the user explicitly supplied it. Do not invent source access. No tools, hooks or credentials.\n\n```json\n" + json.dumps(companion, indent=2) + "\n```\n\nApproved scope manifest SHA-256: " + digest + "\n\n```json\n" + json.dumps(manifest, ensure_ascii=False, indent=2) + "\n```\n"
    return {"manifest": manifest, "sha256": digest, "prompt": prompt, "execution": "not_run", "createdAt": timestamp()}


def validate_markdown_links(name, body):
    for dest in re.findall(r"\]\(([^)\s]+)", body):
        if dest.startswith("#"):
            continue
        dest = dest.split("#")[0]
        normalized = posixpath.normpath(posixpath.join(posixpath.dirname(name), dest))
        if ":" in dest or dest.startswith(("/", "\\")) or "\\" in dest or normalized not in ALLOWED_FILES:
            raise ValueError("The imported Markdown contains an unsafe or unsupported link. Use package-relative profile links only.")


def read_import(p):
    files = {}
    if "zipBase64" in p:
        try:
            blob = base64.b64decode(p["zipBase64"], validate=True)
            if len(blob) > 250000:
                raise ValueError("Profile archive is too large.")
            with zipfile.ZipFile(io.BytesIO(blob)) as archive:
                infos = archive.infolist()
                if len(infos) > len(ALLOWED_FILES) or sum(i.file_size for i in infos) > 250000:
                    raise ValueError("Profile archive exceeds the allowed file count or expanded size.")
                for info in infos:
                    if info.filename not in ALLOWED_FILES or info.filename in files or stat.S_ISLNK(info.external_attr >> 16) or info.file_size > 60000:
                        raise ValueError("Profile archive contains a disallowed path, duplicate, symlink or oversized file.")
                    files[info.filename] = archive.read(info).decode("utf-8", errors="strict")
        except (zipfile.BadZipFile, UnicodeDecodeError, TypeError) as e:
            raise ValueError("Use a valid UTF-8 Rafii profile archive.") from e
        if "manifest.json" not in files:
            raise ValueError("A profile archive needs manifest.json with file hashes.")
        manifest = json.loads(files["manifest.json"])
        hashes = manifest.get("files", {})
        for name, content in files.items():
            if name != "manifest.json" and hashes.get(name) != hashlib.sha256(content.encode()).hexdigest():
                raise ValueError("A profile file does not match its manifest hash.")
            if name.endswith(".md"):
                validate_markdown_links(name, content)
        if "profile.json" in files:
            data = json.loads(files["profile.json"])
        elif "review.md" in files:
            data = markdown_review(files["review.md"])
        else:
            raise ValueError("Include profile.json or a structured review.md field table.")
    elif "markdown" in p:
        body = text(p["markdown"], 50000)
        validate_markdown_links("review.md", body)
        data = markdown_review(body)
    else:
        data = p.get("content")
    if not isinstance(data, dict) or data.get("schema") != "postriff.personal-voice.v1" or not isinstance(data.get("fields"), list) or len(data["fields"]) > 50:
        raise ValueError("Use profile.json with schema postriff.personal-voice.v1 and at most 50 fields, or the builder's review.md table.")
    # Unknown top-level commands, hooks, configs, permissions and skill instructions are ignored, never executed.
    fields, excluded = [], []
    for raw in data["fields"]:
        if not isinstance(raw, dict) or raw.get("key") not in FIELD_META:
            excluded.append("unsupported field")
            continue
        key, privacy = raw["key"], raw.get("privacy", "local_only")
        if privacy == "excluded":
            fields.append(field(key, "", privacy="excluded", source="imported-agent"))
            continue
        evidence = raw.get("evidence", "agent_proposed_needs_confirmation")
        if evidence not in EVIDENCE:
            raise ValueError("The candidate has an invalid evidence state.")
        value = raw.get("value", "")
        # An external agent claiming user confirmation is still an untrusted claim at this boundary.
        effective = evidence if evidence in ("conflicting", "unknown", "not_applicable") else "agent_proposed_needs_confirmation"
        if key == "selfDescription" and raw.get("selfDescribed") is not True:
            value, effective = "", "unknown"
            excluded.append("unconfirmed optional self-description")
        f = field(key, value, effective, privacy, "imported-agent", str(raw.get("confidence", "unassessed"))[:40], raw.get("selfDescribed") is True)
        f["reportedEvidence"] = evidence
        ids = raw.get("sourceIds", [])
        if not isinstance(ids, list) or len(ids) > 10:
            raise ValueError("Each field may reference up to ten source IDs.")
        f["sourceIds"] = ["import:" + text(v, 80) for v in ids] or ["import:untraceable"]
        if not ids:
            f["evidence"] = "agent_proposed_needs_confirmation" if f["value"] else "unknown"
            f["confidence"] = "untraceable"
        fields.append(f)
    if not fields:
        raise ValueError("No supported profile fields were found. Use the builder's companion schema.")
    return fields, {"state": "candidate_needs_review", "fileCount": len(files), "fields": len(fields), "excludedCategories": excluded, "instructions": "Imported commands, hooks and skill instructions were ignored.", "actualSourceAccess": "Rafii read only the candidate you selected; external history access is unverified."}


def markdown_review(body):
    fields = []
    for line in body.splitlines():
        cols = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cols) >= 5 and cols[0] in FIELD_META:
            fields.append({"key": cols[0], "value": cols[1], "evidence": cols[2] if cols[2] in EVIDENCE else "agent_proposed_needs_confirmation", "sourceIds": [v.strip() for v in cols[3].split(",") if v.strip()], "privacy": cols[4] if cols[4] in PRIVACY else "local_only", "confidence": cols[5] if len(cols) > 5 else "unassessed"})
    return {"schema": "postriff.personal-voice.v1", "fields": fields}


def merge_candidates(existing, incoming):
    result = copy.deepcopy(existing)
    for f in incoming:
        peers = [x for x in result if x["key"] == f["key"] and x["value"]]
        if any(x["value"] != f["value"] for x in peers) and f["value"]:
            f["evidence"] = "conflicting"
            for peer in peers:
                peer["evidence"] = "conflicting"
                peer["decision"] = "pending"
        result.append(f)
    return result


def apply(store, s, action, p):
    w = ensure(s)
    if action == "profile_back":
        if w["history"]:
            w.update(w["history"].pop())
        else:
            s["session"]["step"] = 0
    elif action == "profile_relationship":
        q = RELATIONSHIP[w["relationshipIndex"]]
        value = p.get("value")
        values = value if q.get("multiple") and isinstance(value, list) else [value]
        if not values or any(v not in q["options"] for v in values):
            raise ValueError("Choose one of the displayed relationship answers.")
        checkpoint(w)
        w["relationship"][q["key"]] = value
        store._answer(s, "aiRelationship." + q["key"], value)
        if (q["key"] == "experience" and value in ("Not yet", "Set up PostRiff without importing another AI")) or (q["key"] == "products" and "None knows me yet" in values):
            w.update({"stage": "guided", "guideIndex": 0, "transfer": "guided"})
        elif w["relationshipIndex"] == len(RELATIONSHIP) - 1:
            w["stage"] = "transfer"
        else:
            w["relationshipIndex"] += 1
    elif action == "profile_transfer":
        if p.get("route") not in ("cli", "portable", "guided", "compare"):
            raise ValueError("Choose a profile-building route.")
        checkpoint(w)
        w["transfer"] = p["route"]
        w["stage"] = "guided" if p["route"] == "guided" else "scope"
    elif action == "profile_scope":
        scope = validate_scope(p.get("scope"))
        checkpoint(w)
        w["scope"] = scope
        w["request"] = prepare_request(s)
        w["stage"] = "handoff"
    elif action == "profile_inspect":
        w["inspection"] = inspect_clis()
    elif action == "profile_job":
        if not w["request"]:
            raise ValueError("Prepare a scoped request first.")
        w["job"] = {"id": uuid.uuid4().hex, "scopeHash": w["request"]["sha256"], "state": "blocked", "reason": "No real CLI route is qualified in this founder alpha. The request is prepared for review; no executable, authentication flow or model job was launched.", "sourceAccess": "none", "createdAt": timestamp()}
    elif action == "profile_use_guided":
        checkpoint(w)
        w.update({"stage": "guided", "guideIndex": 0})
    elif action == "profile_guided":
        bank = questions(s)
        q = bank[w["guideIndex"]]
        value = p.get("value", "")
        if q.get("options") and value:
            values = value if isinstance(value, list) else [value]
            if any(v not in q["options"] for v in values) or (q["key"] == "layers" and len(set(values)) < 2):
                raise ValueError("Choose the displayed options; a mix needs at least two building blocks.")
        if q["key"] in ("layers", "speaker") and not value:
            raise ValueError("A mixed agency needs its building blocks and first speaker.")
        f = field(q["key"], value, self_described=q["key"] == "selfDescription")
        if q["key"] == "writingExample" and value and p.get("retainExcerpt") is not True:
            f["sourceIds"] = ["writing-example-sha256:" + hashlib.sha256(text(value).encode()).hexdigest()]
            f["value"] = "A writing example was provided; reference retained, raw wording not retained."
        checkpoint(w)
        w["guidedAnswers"][q["key"]] = f["value"]
        # Revisiting an answered question changes its pending direct proposal, never its active profile revision.
        old = [x for x in w["candidate"] if not (x["key"] == q["key"] and x["sourceIds"][0].startswith("direct-question"))]
        w["candidate"] = merge_candidates(old, [f])
        store._answer(s, "profile." + q["key"], f["value"])
        if w["guideIndex"] == len(bank) - 1:
            w["stage"] = "review"
        else:
            w["guideIndex"] += 1
    elif action == "profile_import":
        incoming, report = read_import(p)
        checkpoint(w)
        w["candidate"] = merge_candidates(w["candidate"], incoming)
        w["importReport"] = report
        w["stage"] = "review"
    elif action == "profile_field":
        f = next((x for x in w["candidate"] if x["id"] == p.get("fieldId")), None)
        decision = p.get("decision")
        if not f or decision not in ("approved", "rejected", "unknown"):
            raise ValueError("Choose Approve, Reject, or Keep unknown for this field.")
        value = text(p.get("value", f["value"]))
        privacy = p.get("privacy", f["privacy"])
        if privacy not in PRIVACY:
            raise ValueError("Choose a supported privacy state.")
        if f["key"] == "selfDescription" and decision == "approved" and value and p.get("selfDescribed") is not True:
            raise ValueError("Confirm that this optional description was supplied by you, not inferred.")
        f.update({"value": "" if privacy == "excluded" else value, "privacy": privacy, "decision": decision, "decidedAt": timestamp()})
        if decision == "approved":
            if any(x["id"] != f["id"] and x["key"] == f["key"] and x["decision"] == "approved" and x["value"] != value for x in w["candidate"]):
                raise ValueError("This conflicts with an approved value. Reject the other candidate or edit both to agree first.")
            f["reportedEvidence"] = f.get("reportedEvidence", f["evidence"])
            f["evidence"] = "user_confirmed"
            f["selfDescribed"] = f["key"] == "selfDescription" and p.get("selfDescribed") is True
    elif action == "profile_approve_stated":
        for f in w["candidate"]:
            if f["evidence"] == "user_confirmed" and f["decision"] == "pending" and f["key"] != "selfDescription" and f["privacy"] != "excluded":
                f.update({"decision": "approved", "decidedAt": timestamp()})
    elif action == "profile_review_open":
        if not w["candidate"]:
            w["candidate"] = copy.deepcopy((store._profile(s) or {}).get("fields", []))
        w["stage"] = "review"
        s["session"]["step"] = 1
    elif action == "profile_finish":
        if any(f["decision"] == "pending" for f in w["candidate"]):
            raise ValueError("Review every pending field before activating the package. Agent proposals and conflicts need individual decisions.")
        approved = [copy.deepcopy(f) for f in w["candidate"] if f["decision"] == "approved" and f["privacy"] != "excluded"]
        values = {f["key"]: f["value"] for f in approved}
        if s["brandHub"]["mode"] == "hybrid":
            layers = {v.strip() for v in values.get("layers", "").split(",") if v.strip()}
            if len(layers) < 2 or not layers.issubset({"My voice", "A niche", "A business"}) or values.get("speaker") not in {"My voice", "The business", "A neutral editor"}:
                raise ValueError("Approve at least two displayed building blocks and a valid first speaker for this mixed agency.")
        voice = values.get("voiceTraits", values.get("tone", ""))
        tone = "direct" if "direct" in voice.lower() else "reflective" if "reflect" in voice.lower() else "warm"
        profile = {"tone": tone, "writingExample": values.get("writingExample", ""), "observations": [voice] if voice else ["A provisional warm starting tone; voice fit still needs calibration."], "unknowns": ["No personal experience, credential or result is inferred.", "Voice fit has not been tested with a real model."] + [f["label"] for f in w["candidate"] if f["decision"] != "approved" or f["privacy"] == "excluded"], "preferences": copy.deepcopy((store._profile(s) or {}).get("preferences", [])), "fields": approved, "review": [{"key": f["key"], "decision": f["decision"], "evidence": f["evidence"], "privacy": f["privacy"], "sourceIds": f["sourceIds"], "confidence": f["confidence"]} for f in w["candidate"]], "relationship": copy.deepcopy(w["relationship"]), "profileScope": copy.deepcopy(w["scope"]), "packageSchema": w["schema"]}
        if values.get("antiStyle"):
            profile["observations"].append("Avoid: " + values["antiStyle"])
        store._voice(s, profile, "Explicit field-level Personal Voice Package approval")
        if s["variants"]:
            store._mark_stale(s)
        if not any(i["templateId"] == "personal-voice" for i in s["skillInstances"]):
            s["skillInstances"].append({"templateId": "personal-voice", "templateVersion": "1.0.0", "overrides": {}, "profileRevision": s["speaker"]["activeRevision"], "visibility": "private-local"})
        for key in ("purpose", "audience", "subject"):
            s["brandHub"][key] = values.get(key, "Unknown")
        s["brandHub"]["speaker"] = values.get("speaker", "The business" if s["brandHub"]["mode"] == "business" else "The author")
        s["brandHub"]["layers"] = values.get("layers", s["brandHub"]["mode"]).split(", ")
        s["speaker"]["label"] = s["brandHub"]["speaker"]
        w.update({"approved": True, "reviewedAt": timestamp(), "stage": "review"})
        s["session"]["step"] = 2
        store._mark_stale(s)
    else:
        return False
    return True


def portable_files(s, profile):
    fields = profile.get("fields", [])
    sections = {"PROFILE.md": ["Identity and expertise", "Audience and goals", "Strengths and support"], "VOICE.md": ["Your voice", "Language and culture"], "WORKING_STYLE.md": ["Working style", "Strengths and support", "Optional self-description"], "BRAND.md": ["Identity and expertise", "Audience and goals", "Language and culture"], "BOUNDARIES.md": ["Privacy and boundaries"]}
    files = {}
    for name, groups in sections.items():
        rows = [f"## {f['key']}\n\n{f['value']}\n\nEvidence: {f['evidence']} · Privacy: {f['privacy']} · Sources: {', '.join(f['sourceIds'])}" for f in fields if f["section"] in groups]
        files[name] = f"# {name.removesuffix('.md').replace('_', ' ').title()}\n\nPrivate founder-alpha package. Approved voice revision {s['speaker']['activeRevision']}. User-owned data; no tool authority.\n\n" + "\n\n".join(rows or ["Unknown; no approved fields in this section."])
    files["VOICE.md"] += "\n\n## Scoped writing preferences\n\n" + json.dumps(profile.get("preferences", []), ensure_ascii=False, indent=2)
    files["WORKING_STYLE.md"] += "\n\n## AI relationship (user-reported, unverified)\n\n" + json.dumps(profile.get("relationship", {}), ensure_ascii=False, indent=2)
    files["BRAND.md"] += "\n\nAgency mode: " + s["brandHub"]["mode"] + ". Speaker: " + s["speaker"]["label"] + ". No offer, credential or result is inferred."
    files["BOUNDARIES.md"] += "\n\nPublic fields may inform a reviewed draft. Workspace-only fields are context, private fields guide interaction, local-only fields must stay on the device, excluded values are omitted. Nothing here grants research, tools, payment, account, scheduling or publishing authority."
    sources = [{"id": source_id, "type": "direct_question" if source_id.startswith("direct") else "user_selected_candidate", "scope": "reviewed profile field", "recency": "unknown", "sensitivity": "customer-controlled", "confidence": "field-level only", "rawRetained": False} for source_id in sorted({source for f in fields for source in f["sourceIds"]})]
    files["sources/manifest.json"] = json.dumps({"schema": "postriff.profile-sources.v1", "sources": sources, "grantedScope": profile.get("profileScope"), "actualExternalAccess": "none by Rafii; any external-agent source access is unverified"}, ensure_ascii=False, indent=2)
    rows = []
    for r in profile.get("review", []):
        f = next((f for f in fields if f["key"] == r["key"]), None)
        value = (f["value"] if f and r["decision"] == "approved" else "Unknown or excluded; candidate value omitted").replace("|", " / ").replace("\n", " ")
        rows.append(f"| {r['key']} | {value} | {r['evidence']} | {', '.join(r['sourceIds'])} | {r['privacy']} | {r['confidence']} | {r['decision']} |")
    files["review.md"] = "# Field-level review\n\nStatus: user_approved for selected fields; unapproved candidate values omitted.\n\n| Field | Proposed value | Evidence state | Source IDs | Privacy | Confidence | Decision |\n|---|---|---|---|---|---|---|\n" + "\n".join(rows)
    files["profile.json"] = json.dumps({"schema": "postriff.personal-voice.v1", "status": "user_approved", "fields": fields}, ensure_ascii=False, indent=2)
    files["skills/personal-voice/SKILL.md"] = "# Personal Voice\n\nUse the approved [Profile](../../PROFILE.md), [Voice](../../VOICE.md), [Working style](../../WORKING_STYLE.md), [Brand](../../BRAND.md), [Boundaries](../../BOUNDARIES.md) and [Review](../../review.md) as customer-owned data. Never infer experience, credentials, relationships, opinions, emotion or sensitive traits. Current task instructions override older preferences. Ask one focused question for a necessary gap. Preserve sources, uncertainty, language and privacy. Adapt each draft independently. Propose learning for explicit review. Default to draft, save and export. This package grants no tools, hooks, shell, research, account, payment, scheduling or publication authority. Do not install it globally.\n"
    return files
