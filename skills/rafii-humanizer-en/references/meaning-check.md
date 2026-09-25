# Meaning-preservation check

The deterministic stage runs after the humanizer. It compares the source (the
draft plus the approved facts) with the candidate. It only flags problems. It
never rewrites. Any violation blocks the candidate or returns it for revision,
and the evaluator version is recorded in the run trace.

The token lexicons live in
`src/postriff_phase2/coworker/humanizer_patterns.json` under `meaning_lexicon`.
They cover English, Simplified and Traditional Chinese, and written Cantonese.
The fixtures in `tests/fixtures/humanizer_meaning_cases.json` exercise every
code.

## Violation codes

| Code | Flag when the candidate... | Examples |
|---|---|---|
| `number_changed` | changes or drops a number from the source | 20 becomes 30; "about 2x" becomes "3x" |
| `number_added` | adds a number the source does not have | "99.9% uptime" appears from nowhere |
| `date_changed` | changes, adds or drops a date, weekday, time or quarter | 2026-10-17 becomes 2026-10-18; 週五 becomes 週四 |
| `name_changed` | changes or drops a person, organisation or product name | "Northwind Design" becomes "Northwind Labs" |
| `name_added` | adds a name the source does not have | "据 Brightline Research 统计" |
| `negation_lost` | has fewer negations | not, no, never, 不, 没/沒, 未, 无/無, 唔, 冇 |
| `hedge_removed` | has fewer hedges | may, might, suggests, 可能, 或许/或許, 大概, 据称/據稱 |
| `certainty_added` | adds certainty boosters | definitely, proven, 一定, 肯定, 证明/證明, 梗係 |
| `attribution_lost` | has fewer attribution markers | according to, claims, believes, 认为/認為, 表示, 寫道, 根據 |
| `scope_changed` | changes the multiset of scope words | only, some, all, over, at least, 超过/超過, 至少, 只, 約, 如果, 最早 |
| `status_changed` | adds completion markers, or has fewer planned or in-progress markers | "is planned" becomes "opens"; 正在 becomes 已经/已經; 暫定 becomes 定咗 |
| `causal_added` | adds causal connectors | because, drove, led to, 导致/導致, 造成, 所以, 令到 |
| `anecdote_added` | adds experience markers | last month, one of our customers, 上次, 記得, 琴日 |
| `feeling_added` | adds emotion words | thrilled, proud, 兴奋/興奮, 開心, 期待 |
| `brand_term_changed` | loses or alters a listed brand term (exact, case-sensitive) | "Smart Sync" becomes "automatic syncing" |

## Extraction order

1. Brand terms are passed in per workspace (`brand_terms` in the fixtures). They
   are checked first and removed before names are extracted.
2. Dates are extracted and removed before numbers are extracted. Dates include
   ISO dates, `2026年11月8日`, `10月31日`, English month-day forms, weekdays
   (Friday, 週五, 星期五, 禮拜五), `7:30pm` and `Q2`. Weekday variants are
   normalised.
3. Numbers are digit tokens, and thousands separators are ignored. Keep digits as
   digits. Changing 3 into 三 or three breaks the check.
4. Latin names are Title-case sequences. A sentence-initial single word is not a
   name. A sentence-initial stopword ("The", "According") is dropped from a
   longer match. Chinese person and place names are not detected. Protect them
   as brand terms or quoted terms when they matter.
5. Category tokens are counted with the lexicon regexes. Losses are checked for
   negation, hedges, attribution and planned status. Additions are checked for
   certainty, causation, anecdotes, feelings and completion. Scope is compared
   as a multiset.

## Limits

- The check is conservative and lexical. Swapping one hedge for a synonym (可能
  becomes 或许) or one negation for another (未 becomes 没) can still pass. But
  a rewrite that keeps the exact tokens always passes, so writers should keep
  them.
- It cannot see meaning moved between clauses, such as a negation re-attached to
  the wrong verb. Model review and the owner's approval remain the authority.
- A dropped list item or a dropped sentence without tokens is invisible to it.
  The humanizer's structure rules cover those cases.
