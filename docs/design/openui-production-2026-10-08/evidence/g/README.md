# Lane G evidence (independent acceptance, fault, security, performance)

Everything here is public (the repository is public): hashes, counts, timings, statuses — never tokens, signed URLs, message
text, canonical source or private record content. Every writer passes `tests/agent_ui_acceptance/redaction.py` first.

| Path | What | Written by |
|---|---|---|
| `results/*.json` | gate-level evidence records `{records: [...]}` that `release` mode reads | A copies CI `gate-records.json`; `agent_ui_live.py ingest` |
| `live-<sha>-<timestamp>.json` | one live browser-mode run: the fixed 60-case G03 corpus (D-A53) + 9 edits, verdicts, budget, declared time origins | `agent_ui_live.py ingest` |
| `concurrency-<sha>.json` | 1 / 5 / 20 session run against the loopback harness (fixture provider) | `agent_ui_live.py concurrency` |
| `matrix.md` | the acceptance matrix with the latest status per gate, SHA and evidence paths | G, from the records |
| `review-focus.md` | how review-focus items 1–5 are tested | G |
| `live-runbook.md` | how A drives the live sample through the real UI (passkey sign-in) | G |

## Evidence record (04-ACCEPTANCE "Evidence record")

`tests/agent_ui_acceptance/evidence.record(...)` produces, per gate and evidence kind:
`{gate, status: pass|fail|blocked|unverified, candidateSha, environment: {kind, origin, runner, runId, runUrl}, recordedAt,
timezone: "UTC", command, actor, dataScope, expected, actual, evidencePaths, checks}`.

Evidence kinds (`corpus.EVIDENCE_KINDS`): `contract`, `ci-harness`, `ci-browser-emulation`, `preview-deployment`,
`production-canary`, `production`, `live-provider`, `physical-device`, `manual`, `repository`. Each gate in
`corpus.GATES` lists the kind groups that can satisfy it; e.g. G03 needs `live-provider` **and** a production kind, G15 needs
`ci-browser-emulation` **and** `physical-device`.

## Where CI evidence comes from

`.github/workflows/agent-ui.yml` → "Browser acceptance (lane G)" → `scripts/agent_ui_validation.sh browser` →
`scripts/agent_ui_acceptance.sh browser`. The run's artifact `agent-ui-evidence-<sha>` holds `api-corpus.json`,
`validator-corpus.json`, `e2e-chromium.json`, `e2e-webkit.json`, `bundle-devtools.json`, `gate-records.json` and logs.
To use them for a release: download the artifact for the candidate SHA and copy `gate-records.json` to
`results/ci-<sha>.json` in one evidence-only commit (release mode accepts evidence-only commits after the candidate).

## Release check

```
AGENT_UI_CANDIDATE_SHA=<sha> bash scripts/agent_ui_acceptance.sh release      # or: python -m agent_ui_acceptance.release --candidate <sha>
```
It fails while any required gate lacks pass evidence of an accepted kind for exactly that SHA.
