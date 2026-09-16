# Persistent intake contract

PostRiff resolves intent and slots deterministically first, in `src/postriff_phase2/intent.py`, and only asks a model when that classifier cannot decide. Persist every answer as conversation state through the host. A host that cannot persist intake is `runtime_dependency_missing`.

`ConversationStore(path)` uses a local SQLite database. `create(id, mode, slots)` preserves already supplied values. `next(id)` returns at most one question; truth questions have `answer_type=research` and go to the researcher, not to a fabricated human response. `answer(id, slot, value)` accepts only the current question. `revise` increments revision and returns to intake; changing source clears truth state. `verify_identity` records an identity mismatch without switching the browser account. `cancel` persists cancellation across restarts.

`setup_selection(email, selected)` accepts exact channel IDs, `all`, or an empty list. It returns immutable selected/excluded channel IDs and a selection hash. All initial channel states are `not_checked`; no connection is claimed.

Truth-state slots are review inputs, not proof of facts. Bind reviewed source/claim records in the research workflow before approving any derived campaign. The current store does not itself validate a factual assertion or execute a live setup action.
