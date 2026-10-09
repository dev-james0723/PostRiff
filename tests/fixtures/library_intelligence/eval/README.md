# Frozen retrieval relevance set (A026, A027, A031)

Authored by the coordinator on 2026-10-08, BEFORE seeing the retrieval implementation, and frozen at the commit that adds it. Do not tune ranking against these judgments and then report the same score as independent evidence. Any change to `corpus.json` or `queries.json` is a new set version and must be reported as such.

- `corpus.json`: 64 core documents written for this set. The languages are English, Traditional Chinese (zh-Hant), Simplified Chinese (zh-Hans), Cantonese (yue), and code-switched Cantonese/English. The documents are synthetic creator-library material: concerts, practice, brand facts, campaigns, interviews, invoices and so on. They contain no real personal data.
- `queries.json`: 100 queries. Each has a `type` and a list of `relevant` document ids:
  - 30 `lexical`: exact phrase, filename-like or number
  - 40 `semantic`: paraphrase with little word overlap
  - 15 `cross_lingual`: the query language differs from the relevant document
  - 15 `code_switch`: Cantonese/English mixed queries
- Distractors: `scripts/library-intelligence-eval.py` adds 940 deterministic templated distractor documents, giving 1,004 documents in total, so Recall@10 is not trivial.
- Metric: Recall@10 = mean over queries of (relevant docs retrieved in the top 10) / min(10, number of relevant docs). The acceptance target for semantic/hybrid queries on this set is ≥ 0.90 (A026). Lexical-only results are reported separately and are not presented as semantic results.
