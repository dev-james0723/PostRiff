"""Codex CLI as a content-only writing route — the same contract as the Claude Code route.

`codex exec --json` in a read-only, ephemeral sandbox with a JSON output schema; the person's own
ChatGPT/Codex login pays. PostRiff never reads the login: the CLI authenticates itself from the
person's home directory in a restricted environment.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import time

from postriff_alpha.domain import AlphaError
from .agent_runtime import safe_event
from .cli_runtime import ClaudeCliRuntime, ENABLE_ENV, MAX_DELTA_CHARS, MAX_OUTPUT_BYTES, OUTPUT_SCHEMA, PLATFORM_LIMITS, SAFE_ENV_KEYS, normalize_output, restricted_environment
from .contracts import digest

ROUTE = "codex"
MODEL_PREFIX = "codex:"
EXECUTABLE_ENV = "POSTRIFF_CODEX_BIN"
MODELS_ENV = "POSTRIFF_CODEX_MODELS"  # comma-separated extra model ids the person allows for `-m`
_MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,60}$")
_USAGE_LIMIT = re.compile(r"usage limit|rate limit|quota|credits", re.I)
_LOGIN = re.compile(r"not logged in|login|unauthorized|401|authenticat", re.I)


def _executable():
    override = os.environ.get(EXECUTABLE_ENV)
    if override:
        return override if os.path.isfile(override) and os.access(override, os.X_OK) else None
    return shutil.which("codex")


def allowed_models():
    extra = [m.strip() for m in os.environ.get(MODELS_ENV, "").split(",") if m.strip() and _MODEL_ID.match(m.strip())]
    return ["default"] + extra


def classify_failure(text):
    text = text or ""
    if _USAGE_LIMIT.search(text):
        return "usage", "Codex reported a usage limit for your account. Check chatgpt.com/codex/settings/usage, then try again. No draft was changed."
    if _LOGIN.search(text):
        return "auth", "Codex is not signed in on this machine. Run `codex login` in Terminal, then try again. No draft was changed."
    return "failed", "Codex did not complete the request. No draft was changed and nothing was retried."


class CodexCliRuntime(ClaudeCliRuntime):
    provider = ROUTE
    asynchronous = True
    cost_class = "subscription"
    model = MODEL_PREFIX + "default"

    @classmethod
    def available(cls):
        return os.environ.get(ENABLE_ENV, "1") != "0" and _executable() is not None

    def executable(self):
        if self.executable_override:
            return self.executable_override if os.path.isfile(self.executable_override) and os.access(self.executable_override, os.X_OK) else None
        return _executable()

    # --- discovery -----------------------------------------------------------------
    def detect(self, force=False):
        if self._probe and not force and self.clock() - self._probe_at < 60:
            return self._probe
        executable = self.executable()
        info = {"id": ROUTE, "name": "Codex CLI", "vendor": "OpenAI official CLI", "installed": bool(executable), "version": None, "authStatus": "unknown", "authMethod": None,
                "models": [], "modelsSource": "configured", "guidance": None, "execution": self.execution_settings(), "host": "api-process"}
        if executable:
            env = self.env or restricted_environment()
            try:
                version = subprocess.run([executable, "--version"], capture_output=True, text=True, timeout=10, env=env).stdout
                found = re.search(r"\d+\.\d+\.\d+", version)
                info["version"] = found.group() if found else None
                status = subprocess.run([executable, "login", "status"], capture_output=True, text=True, timeout=15, env=env)
                text = (status.stdout + status.stderr).lower()
                if status.returncode == 0 and "logged in" in text and "not logged in" not in text:
                    info["authStatus"] = "ok"
                    info["authMethod"] = "chatgpt" if "chatgpt" in text else ("api-key" if "api key" in text else "cli")
                else:
                    info["authStatus"] = "missing"
            except (OSError, subprocess.TimeoutExpired):
                info["authStatus"] = "unknown"
            info["models"] = [f"{MODEL_PREFIX}{alias}" for alias in allowed_models()]
            if info["authStatus"] != "ok":
                info["guidance"] = "Run `codex login` in Terminal on this machine, then rescan."
        else:
            info["guidance"] = "Install the Codex CLI on the machine that serves the API, sign in with `codex login`, then rescan."
        self._apply_auth_state(info, force)
        self._probe, self._probe_at = info, self.clock()
        return info

    LOGIN_COMMAND = "codex login"

    def execution_settings(self):
        return {"budgetUsd": 0.0, "timeoutSeconds": self.timeout_seconds, "tools": "none (read-only sandbox)", "mcp": "none", "settingSources": "none (--ignore-user-config --ignore-rules)", "sessionPersistence": False, "environment": list(SAFE_ENV_KEYS)}

    def list_supported_models(self):
        probe = self.detect()
        ready = probe["installed"] and probe["authStatus"] == "ok"
        detail = "Runs the Codex CLI signed in on this machine in a read-only sandbox. Your ChatGPT/Codex plan pays; PostRiff spends $0 and records the run." if ready else (probe["guidance"] or "Codex is not available on this machine.")
        return [{"id": f"{MODEL_PREFIX}{alias}", "label": "Codex CLI · your default model" if alias == "default" else f"Codex CLI · {alias}", "qualified": ready, "costClass": "subscription", "route": ROUTE, "detail": detail} for alias in allowed_models()]

    def owns(self, model_id):
        return isinstance(model_id, str) and model_id in {f"{MODEL_PREFIX}{alias}" for alias in allowed_models()}

    @staticmethod
    def alias_of(model_id):
        alias = model_id[len(MODEL_PREFIX):] if isinstance(model_id, str) and model_id.startswith(MODEL_PREFIX) else "default"
        if alias not in allowed_models():
            raise AlphaError("Choose a supported Codex model.", 400)
        return alias

    def start_conversation(self, workspace_id, actor):
        return {"runtime": ROUTE, "resumable": False}

    # --- prompt and process --------------------------------------------------------
    def argv(self, executable, alias, workdir):
        if alias not in allowed_models():
            raise AlphaError("Choose a supported Codex model.", 400)
        args = [executable, "exec", "--json", "--ephemeral", "--ignore-user-config", "--ignore-rules", "--skip-git-repo-check",
                "--sandbox", "read-only", "--output-schema", os.path.join(workdir, "schema.json"), "-C", workdir]
        if alias != "default":
            args += ["-m", alias]
        return args + ["-"]

    def _execute(self, run_id, request, sink):
        executable = self.executable()
        if not executable:
            raise AlphaError("The Codex CLI is not installed on the machine that serves this workspace.", 503)
        alias = self.alias_of(request.get("model"))
        system_prompt, user_prompt = self.compose(request)
        prompt = system_prompt + "\n\n" + user_prompt
        started = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="postriff-codex-") as workdir:
            os.chmod(workdir, 0o700)
            with open(os.path.join(workdir, "schema.json"), "w", encoding="utf-8") as handle:
                json.dump(OUTPUT_SCHEMA, handle)
            process = self.spawn(self.argv(executable, alias, workdir), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, cwd=workdir, env=self.env or restricted_environment(), start_new_session=True)
            try:
                process.stdin.write(prompt.encode("utf-8"))
                process.stdin.close()
            except (OSError, ValueError):
                pass
            sink.emit(safe_event("progress.updated", stage="writing", percent=10))
            size, final_text, failure, usage, finished = 0, None, None, None, False
            for line in self._read_lines(process, started):
                if sink.cancelled():
                    self._stop(process)
                    raise AlphaError("Cancelled. Partial text retained; no automatic retry.", 499)
                size += len(line)
                if size > MAX_OUTPUT_BYTES:
                    self._stop(process)
                    raise AlphaError("Codex produced more output than allowed; the run was stopped and no draft was changed.", 502)
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(event, dict):
                    continue
                kind = event.get("type")
                item = event.get("item") if isinstance(event.get("item"), dict) else {}
                if kind == "item.completed" and item.get("type") == "agent_message" and isinstance(item.get("text"), str):
                    final_text = item["text"]
                    sink.emit(safe_event("message.delta", text=final_text[:MAX_DELTA_CHARS]))
                elif kind == "item.completed" and item.get("type") == "error":
                    failure = str(item.get("message") or item.get("text") or "")
                elif kind == "error":
                    failure = str(event.get("message", ""))
                elif kind == "turn.failed":
                    failure = failure or json.dumps(event.get("error", ""))[:400]
                    finished = True
                    break
                elif kind == "turn.completed":
                    usage = event.get("usage") if isinstance(event.get("usage"), dict) else None
                    finished = True
                    break
            self._stop(process)
            try:
                process.stdout.close()
            except (OSError, ValueError):
                pass
        if failure:
            code, message = classify_failure(failure)
            raise AlphaError(message, 401 if code == "auth" else 502)
        if not finished:
            raise AlphaError("Codex reached the time limit or exited early. No draft was changed and this request will not retry automatically.", 504)
        try:
            structured = json.loads(final_text) if final_text else None
        except ValueError:
            structured = None
        artifact = normalize_output(structured, request, author="Codex")
        sink.emit(safe_event("message.completed"))
        sink.complete(artifact, {"provenance": "reported_by_cli", "billing": "subscription", "modelRequests": 1, "costUsd": 0, "cliCostUsd": None,
                                 "tokens": usage, "model": request.get("model"), "inputHash": digest({"prompt": prompt}), "limits": PLATFORM_LIMITS})
