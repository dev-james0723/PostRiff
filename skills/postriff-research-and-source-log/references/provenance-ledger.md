# Provenance ledger

Record the ledger through the host: research results attach as workspace sources under the four-class policy in `src/postriff_phase2/source_policy.py`, which defaults an attached research source to `rewrite_approval`. A host that cannot record the ledger is `runtime_dependency_missing`; do not keep evidence only in the transcript.

- `register`: immutable reviewed publisher/version, tier and claim-type authority.
- `observe`: immutable bounded source text and exact URL, location and retrieval time. Foreign hosts, stale registry versions and disabled sources are rejected. This does not fetch or execute URLs.
- `review_claim`: trusted researcher boundary requiring explicit support, contradiction or context-only relations. Never fill this field based on publisher reputation alone.
- `fact_pack`: current usable versions only, including qualifications and immutable hash.
- `bind_artifact`, `retract`, `artifact_status`: track local dependent artifacts without changing external content. New claim versions invalidate prior dependencies; historical evidence is retained.

Use `python3 -m unittest tests.test_research_log tests.test_source_publish_boundary -v`. Test documents and reviewers are synthetic. For publication, initialize SourceLog and JobStore with the same SQLite file and bind the exact claims in the immutable job payload. Approval and begin then atomically reject retractions, superseded claims and registry drift. A missing or separate ledger cannot qualify a news job. This does not revoke already-remote schedules, establish semantic correctness, enforce copyright excerpt budgets, or provide a network acquisition runner. These remain explicit integration requirements.
