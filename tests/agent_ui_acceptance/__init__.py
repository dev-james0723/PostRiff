"""Lane G — independent acceptance, fault, security and performance harness of Rafii Generative UI (rafii-genui/1).

Owned by G (docs/design/openui-production-2026-10-08/A-DECISIONS.md ownership register). G reports defects to the owning lane
and never edits production files. What lives here:

    corpus.py                              the 04-ACCEPTANCE negative corpus and gate map (single source of truth for coverage)
    test_agent_ui_acceptance_contract.py   pure contract-layer negatives (frozen A seam: validators, framing, kill switch, migration)
    test_agent_ui_acceptance_release.py    release-mode checker + live-runner guards (no network, no DB)
    api_corpus.py                          API-level negatives against the running harness (real WSGI app, real PostgreSQL, the
                                           real Node parser seam); run by `scripts/agent_ui_acceptance.sh api|browser` in cloud CI
    validator_corpus.py                    the trusted parser seam's negatives over its signed internal route (lane C)
    serve.py                               the acceptance harness server (dev harness + migration 102 + fault injection + expiry)
    client.py / db.py / sse.py             HTTP/SSE client with fragmented-UTF-8 reader, DB before/after counters
    release.py                             `release` mode: every required gate needs pass evidence for the exact candidate SHA

Evidence is never fabricated: a case whose positive control cannot run (a lane still answers `ui_not_ready`) is recorded
`blocked`, not `pass`, and a mock, fixture, screenshot or emulation never satisfies a gate that requires a real provider,
database, deployment or device.
"""
