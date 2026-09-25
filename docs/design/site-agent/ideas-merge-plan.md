# `ideas.py` integration plan: `raffi/site-agent` × `consumer-saas` / PR #2 / the canonical checkout

Prepared 2026-09-24 from read-only comparisons (`git merge-tree`, `git show`, file copies). No other session's
working tree, branch or stash was changed.

## The lines of work

| Line | Ref | `src/postriff_phase2/ideas.py` |
|---|---|---|
| Integration / production | `origin/consumer-saas` = `dcbb533` (PR #1 merge `df9bea0` + docs) | the Rafii v9 version (`f3f4746`) |
| This branch | `raffi/site-agent` (`064982b`, `bc44eee`, peer commit `6022e15` which does not touch the file, and this stage's commit) | v9 **+73 / −11**: site-agent changes only |
| PR #2 (open, held) | `raffi/launch-final` → `consumer-saas`, head **`5a9da46`** on origin (the local ref `1761d3c` is stale) | v9 **+239 / −110**: `_project()` refactor, fingerprinted idempotency (`request_fingerprint`, `_keyed_run`), credits gate, `_quick_start_source()`, `checked_context_ids()`, `runRefs`, `IDEA_LIMIT` |
| Canonical checkout | `/Users/ouxianxing/Documents/James-Au-Studio`, local `consumer-saas` `468811b` + another session's **uncommitted** edits (file saved 2026-09-24 03:59) | `468811b` + the same `_project()`/`intentText` refactor as PR #2, **without** v9 (no `_automation_turn`, `_understand`, voice fallback). It has nothing PR #2 lacks. |

## Trial merges

- `raffi/site-agent` → `origin/consumer-saas`: **clean**. No conflicts in any file.
- `raffi/site-agent` ↔ PR #2 (`5a9da46`): **5 conflicted files**. `ideas.py` has 4 hunks. `hosted_app.py`,
  `learning_model.py`, `web/src/lib/api/types.ts` and `docs/consumer-ready/secret-allowlist.json` have one each.
  Seven other shared files (`campaigns.py`, `hosted.py`, `model_runtime.py`, `client.ts`, `conversation-view.tsx`,
  `channels-view.tsx`, `queue-view.tsx`) auto-merge.

## The fixes that must survive

1. **Home quick-start stale-idea fix (PR #2 / canonical line).** `_project()` drafts `text or intentText or
   brief idea`. A quick start therefore drafts the idea just typed, not the workspace brief's first idea. Pinned by
   `tests/phase2/postgres_credits.py:173` on PR #2.
   `raffi/site-agent` fixed the same bug another way: quick start passed `"idea": chosen["idea"]`. **Keep PR #2's fix
   and drop ours.** The site agent never sends `idea`, and `intentText` is already in the quick-start payload.
2. **Weekday / rework classification fix (this branch).** A turn that carries handed-in `material` is
   drafting: intent `draft`, times and `localTime` cleared, `_understand` and `_orchestration_turn` skipped. "Turn
   Thursday's post into…" therefore never becomes an automation or a schedule. This block sits **outside** the
   conflict hunks and auto-merges. Pinned by scenarios D04, K05, X06, X06b and X06c.
3. Also from this branch, and all must stay:
   - `material` is wrapped in `MATERIAL_LABEL` (the writer reads it as data);
   - `materialRef` is echoed on the user message, and `messageText` (the person's own words when the writer gets
     one step of a longer request) is what the conversation records;
   - `_research()` skips a turn that carries material unless the message has a link. Without this, "Shorten this
     draft" was looked up on the web and unrelated pages became sources. It auto-merges and is pinned by
     `tests/phase2/postgres_research.py`;
   - `reworkOf` and `forCampaign` are carried from outcome to artifact;
   - `apply()` targets the reworked draft, links campaign posts in the same command, sets `provenance.derivedFrom`,
     and marks updates with `proposedUpdate: True`;
   - **the apply source-binding fix** described below.

## Resolution, hunk by hunk (when PR #2 and this branch meet)

**H1: `turn()`, prompt assembly.** Take PR #2's side (`_project(...)`, `existing` from `_keyed_run`). Then re-add
the two site-agent pieces:

```python
# in turn(), right after the projected values are unpacked
material_ref = payload.get("materialRef") if isinstance(payload.get("materialRef"), dict) else None
if text:
    said = clean(payload["messageText"], MAX_TEXT) if isinstance(payload.get("messageText"), str) and payload["messageText"].strip() else text
    self._append_message(cur, workspace_id, conversation_id, "user", {"text": said, "sourceIds": source_ids, "intent": parsed["intent"],
                         **({"material": {k: str(v)[:120] for k, v in material_ref.items() if k in ("type", "id", "title")}} if material_ref else {})})

# in _project(), after `idea = clean(raw_idea[:IDEA_LIMIT], IDEA_LIMIT)`
material = clean(payload["material"], MAX_TEXT) if isinstance(payload.get("material"), str) else ""
if material:
    # Handed-in material (a draft to rework, a campaign brief): read by the writer as data after the instruction.
    idea += f"\n\n{MATERIAL_LABEL}\n<<<\n{material}\n>>>"
```

The `outcome["reworkOf"]` and `outcome["forCampaign"]` lines further down read `material_ref`. They auto-merge, so
`material_ref` must be defined in `turn()` as above. Otherwise they raise `NameError`. `IDEA_LIMIT` still bounds the
typed instruction. The material keeps its own `MAX_TEXT` bound, as it does on this branch today.

**H2: `apply()`, the proposed-update branch.** Take the union: keep PR #2's `old["runRefs"] = …[-10:]` line and
this branch's `"proposedUpdate": True` key in the `created` entry.

**H3: `quick_start()`, the command body.** Take PR #2's side (`checked_context_ids` + `_quick_start_source`).
Drop `chosen["idea"]`, which fix 1 supersedes.

**H4: `quick_start()`, the `turn` call.** Take PR #2's side (it passes `intentText`). Do not add `"idea"`.

**Other files.**
- `hosted_app.py`: keep both new routes, the site-agent dispatch and `billing/credit-packs`.
- `learning_model.py`: build PR #2's body without `temperature` but with `providerOptions`, then
  `if self.model not in NO_TEMPERATURE: body["temperature"] = 0.2`. `NO_TEMPERATURE` arrives through the auto-merged
  `model_runtime.py`.
- `types.ts`: keep `provenance.derivedFrom` and `runRefs?: string[]`.
- `secret-allowlist.json`: keep both new entries.

## The apply source-binding fix (this stage; a production bug)

`apply()` refused every candidate whose writer cited fewer sources than it was given ("Sources or their policies
changed"). The guard re-projected only the *cited* ids but compared them with *all* bindings.
- Found with the live Claude Code writer: it was given 6 sources and cited 2.
- Present on production (`df9bea0`), on PR #2 (`5a9da46`) and in the canonical checkout, which all have identical
  lines.
- Fix: re-project the union of bound and cited ids. Every change to a source the writer was given still refuses; a
  legacy artifact without bindings refuses exactly as before.
- Pinned by `tests/phase2/postgres_cli_route.py` step 11, which fails without the fix and passes with it, including
  the negative case of narrowing an *uncited* source's approved facts.
- Neither side changed these lines, so the fix auto-merges with PR #2.

## Recommended order

1. **Land PR #2 first**, when its held items (migrations 020–022, review items) clear. Its `ideas.py` change is the
   large refactor. Ours is small, so porting ours onto the refactor is the smaller, cleaner operation.
2. Then merge `origin/consumer-saas` into `raffi/site-agent`, **on the branch and not on `consumer-saas`**, resolving
   exactly as above. Re-run the verification below and open the PR from the branch.
3. If PR #2 stays held and the site agent is to land first, the site agent merges cleanly today. PR #2's owner then
   applies the same four resolutions from the other side. The plan is symmetric.
4. The canonical checkout's uncommitted `ideas.py` needs no action from us. It is an older subset of PR #2, and its
   owner should rebase onto `origin/consumer-saas` or drop it in favour of PR #2. **Do not overwrite it.**

## Verification after the resolution

- `python -m unittest discover -s tests`; the full PostgreSQL suite (`scripts/postriff_pg_suite.py`), in particular:
  - `postgres_site_agent_scenarios` (98 scenarios; X06 checks that the conversation shows what was typed);
  - `postgres_research` (reworks look nothing up unless linked);
  - `postgres_cli_route` (11 checks);
  - `postgres_credits` (the stale-idea pin);
  - `postgres_ideas` and the `postgres_raffi_*` tests.
- Web: node tests, `tsc`, lint, `next build`.
- Two targeted checks:
  1. two quick starts with different ideas each draft their own idea (fix 1);
  2. "Turn Thursday's post into a LinkedIn post" with a selected draft yields a rework run with no automation, time or
     schedule (fix 2).
- After the merge, the site agent's delegated writing runs pass through PR #2's credits gate. On a paid route, a
  refusal must show as a "needs you" step with its reason, never as a crash. The scenario suite runs delegated
  writing only on the free deterministic route and the fake asynchronous writer, so this refusal path is **untested**.
  Check it on a paid route once one is qualified.
