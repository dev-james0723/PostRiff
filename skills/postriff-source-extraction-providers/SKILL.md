---
name: postriff-source-extraction-providers
description: Normalize an already discovered exact public article URL into provenance-rich source material. Use after RSS, search, a source pack, or the user supplies a URL; do not use for broad discovery, authenticated scraping, factual verification, media reuse, or publishing.
license: MIT
metadata:
  version: 1.0.0
  status: project-local-phase0-fixture-only
  project-contract: postriff-social-media-suite-design-revision-14
---

# PostRiff source extraction providers

Convert a known public URL into a reviewable source artifact without confusing retrieval with truth. This Phase 0 skill evaluates provider policy and offline fixtures only. It does not install or invoke NewsCrawler or XhsSkills.

## Required inputs

Load the active source registry record, exact URL, intended research use, provider registry, and current source/rights policy. Reject missing provenance, private or access-controlled targets, and any request for credentials or raw cookies.

Read [references/provider-boundaries.md](references/provider-boundaries.md) before choosing a provider state or interpreting an extraction result.

## Workflow

1. Confirm that discovery has already supplied one exact URL.
2. Evaluate the exact provider and operation through `config/v14-provider-registry.json`.
3. In Phase 0, use only the matching deterministic fixture and label it `fixture_only`.
4. Normalize original/canonical URL, ordered text, public media references, author, publisher/retrieval time, provider pin, output hash, and warnings.
5. Return access, parser, rate-limit, and rights states without escalating to another route.
6. Send extracted claims to source-tier and claim-level review. Do not strengthen confidence here.

## Output

Return the provider decision, normalized source artifact, provenance, extraction warnings, fact-confidence boundary, rights boundary, and explicit `not_done` items.

## Hard boundary

NewsCrawler remains `candidate_read_only`; XhsSkills remains `reference_only` with zero executable operations. This skill never logs in, reads cookies, bypasses access controls, downloads no-watermark media, messages, reacts, uploads, schedules, publishes, or certifies complete coverage.
