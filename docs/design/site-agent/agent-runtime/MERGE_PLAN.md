# Agent Runtime — three-way merge plan

Checked with `git merge-tree --write-tree` (no working tree touched) from `raffi/site-agent` at 83575ea on
2026-09-25. Nothing here has been pushed or merged. Re-run the same commands against the refs of the day before merging:
branches move.

```sh
git fetch origin
for B in origin/consumer-saas origin/raffi/launch-final origin/raffi/site-agent-release; do
  echo "== $B"; git merge-tree --write-tree --name-only --no-messages raffi/site-agent "$B" | tail -n +2
done
```

## The order that keeps conflicts smallest

1. **PR #2** (`raffi/launch-final` → `consumer-saas`). This is the site agent session's release, not this runtime's.
2. **PR #5** (`raffi/site-agent-release` → `consumer-saas`). The site agent without the runtime, built from `bc44eee`
   with PR #2 merged in and 32ffaaa cherry-picked (as 60a5828). Owned by the site agent session.
3. **This branch** (`raffi/site-agent` → `consumer-saas`), with every `RAFII_*` flag off. The merge base is then
   `bc44eee`, so only the runtime's commits and the site agent's post-`bc44eee` commits are new, and the latter are
   already in `consumer-saas` through PR #5.

## Step 3: conflicts against PR #5 (`origin/raffi/site-agent-release` @ f0f3b88)

| File | Owner | Resolution |
|---|---|---|
| `src/postriff_phase2/hosted_app.py` (1 hunk, the `/api/workspaces/…` dispatch) | shared | **Keep both blocks.** The predicates are disjoint (`parts[3] == "agent"` vs `parts[3:] == ["billing", "credit-packs"]`), so the order doesn't matter. See the resolved text below. |
| `docs/design/site-agent/README.md`, `verification-matrix.md`, `evidence/scenarios.json`, `evidence/browser-*/site-agent-*` | site agent | **Take the `consumer-saas` side** (the release's newer evidence), for everything under `docs/design/site-agent/` **except** `docs/design/site-agent/agent-runtime/**` (the runtime's, which doesn't conflict). |

Resolved `hosted_app.py` hunk:

```python
            if len(parts) >= 5 and parts[:2] == ["api", "workspaces"] and parts[3] == "agent":
                # The Rafii Agent Runtime (text, voice, images); its routes live in agent_runtime_v2/http.py.
                from .agent_runtime_v2.http import handle as agent_runtime_handle
                return agent_runtime_handle(self, environ, start_response, service, token, method, parts)
            if len(parts) == 5 and parts[:2] == ["api", "workspaces"] and parts[3:] == ["billing", "credit-packs"] and method == "GET":
                return self._json(start_response, 200, service.billing_credit_packs(parts[2], token))
```

**Auto-merged, but read the result:**

- `src/postriff_phase2/ideas.py`: the runtime changes only `recover_stalled`, whose two SELECTs skip `agent:`, `task:` and
  `voice:` rows. PR #2 doesn't touch those lines. The site agent's `ideas.py` changes are identical on both sides
  (32ffaaa ≡ 60a5828). The Home quick-start and weekday/rework fixes are not touched by the runtime.
- `src/postriff_phase2/site_agent/service.py`, `web/src/features/site-agent/answer.tsx`, `chat.tsx`, `panel.tsx`: the
  runtime's lines are the `VoiceIndicator` mount, the agent API call when `status.manager.available`, `VoiceMode`,
  `AttachImage` and `AgentExtras`. The site agent's are its own.
- `.env.example`: the runtime's `RAFII_*` block. `requirements.txt`: adds `openai-agents==0.22.3` and `openai==3.19.2`; no
  other branch pins either. `vercel.json`: `microphone=(self)` in the Permissions-Policy (PR #2 and PR #5 leave that line
  as `microphone=()`, so the merge takes the runtime's).

## If this branch merges after PR #2 but before PR #5 (not recommended)

Conflicts against `origin/raffi/launch-final` @ 5a9da46:

- `hosted_app.py`: same hunk and resolution as above.
- `ideas.py`, `learning_model.py`, `web/src/lib/api/types.ts`, `docs/consumer-ready/secret-allowlist.json`: these come
  from the site agent's commits (064982b, bc44eee), not from the runtime. Resolve them per
  `docs/design/site-agent/ideas-merge-plan.md`; that is the site agent session's decision.

## Concurrent work not to overwrite (uncommitted at the time of writing)

- **This worktree:** the Adaptive Social Coworker session has uncommitted changes:
  - `hosted_app.py`: coworker runtime attach, public routes and cron, placed after the runtime's dispatch;
  - `vercel.json`: `/sw.js` headers;
  - `.env.example`: its flags;
  - `email.py`, `skills.py`, notifications and web files;
  - an untracked `coworker/` package.

  Its commits will sit on top of this branch's lines. It plugs into the runtime only through
  `domain_tools.EXTENSION_MODULES` and `specialists.extend_scope`, both guarded, so the runtime works with or without it.
- **The main checkout (`consumer-saas`):** uncommitted `.env.example`, `hosted_app.py`, `ideas.py`, `vercel.json`,
  `web/package.json`. **`raffi-launch`:** staged `hosted_app.py`, `ideas.py`. **`site-agent-release`:** uncommitted
  `answer.tsx`, `chat.tsx`. Merge only after their owners have committed.
- `ai-routing` and `codex/consumer-ready-release` are stale forks (Sept 17–20) of lines already merged into
  `consumer-saas`, and conflict widely with it. They are not merge targets for this branch.

## After the merge (flags still off)

```sh
PYTHONPATH=src:tests python -m unittest discover -s tests -p 'test_*.py'
PYTHONPATH=src:tests python scripts/agent_runtime_pg.py tests/phase2/postgres_agent_runtime.py --port 55621
python scripts/postriff_pg_suite.py
node --test web/tests/*.test.mjs web/tests/*.test.cjs web/src/lib/locales/core.test.mjs
(cd web && npm run lint && npm run typecheck && npx next build)
node web/tests/site-agent-browser.cjs            # against a server with no RAFII_* flags: the site agent is unchanged
python scripts/agent_runtime_matrix.py --unit
```
