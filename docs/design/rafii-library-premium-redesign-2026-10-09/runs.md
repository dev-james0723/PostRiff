# Redesign remote runs

Every run below is the full Library release suite (`scripts/library-release-validation.sh`) on JCB → Depot
(`depot-ubuntu-24.04-16`). Runs are recorded from observed results only, failures included.

From 2026-10-09 consumer-saas maps `jcb ci` to the YouTube suite. The Library runs therefore use a temporary,
uncommitted JCB config and regenerated workflow with `ci → ci:library`. These are restored after submission and never
committed; product code is the committed head (`sourceHead`).

| Head | Run | Result | What it showed |
|---|---|---|---|
| 1fac5aa8 | [rxdlf2820l](https://depot.dev/orgs/jf34f85hr0/workflows/rxdlf2820l) | FAIL | TS2322: `Control` accepted base-ui's className function; narrowed to a string. |
| 89f55cc9 | [tznbcn7v2q](https://depot.dev/orgs/jf34f85hr0/workflows/tznbcn7v2q) | FAIL | Lint (jsx-a11y): `onKeyDown` on the docked `<aside>`; replaced by a document Escape listener scoped to focus inside the panel. |
| fe87d52b | [d91qztxmvb](https://depot.dev/orgs/jf34f85hr0/workflows/d91qztxmvb) | FAIL | Library acceptance: delete confirmation timed out; ghost controls rendered with the filled default material (fixed by passing the material as `variant`). |
| 1da1b27a | [xqc8zk4dp6](https://depot.dev/orgs/jf34f85hr0/workflows/xqc8zk4dp6) | FAIL (library=0, intelligence=1) | Library acceptance passes in Chromium and WebKit. Intelligence harness: a stale selection beyond the loaded 200 items was not dropped; fixed by checking unknown selected ids with the server. |
| 59750e94 | [chqvr20shx](https://depot.dev/orgs/jf34f85hr0/workflows/chqvr20shx) | FAIL (web_node) | First run after merging consumer-saas 94ca0dbd. Unit, PostgreSQL 16 (with and without pgvector), adjacent and full Python discovery pass; the suite stops after the cloud stages, so no browser run. `agent-ui-library.test.cjs` (from #137) failed: the Library renderer slot lacked `publishObservability={false}`; fixed in 4ef272b4. |
| cde7e2a3 | [kng84nm81x](https://depot.dev/orgs/jf34f85hr0/workflows/kng84nm81x) | FAIL (library=0, intelligence=1) | Every cloud stage passes (unit, PostgreSQL 16 with and without pgvector, adjacent, web node, full Python), and so do typecheck, lint, build and Library acceptance in Chromium and WebKit. The intelligence harness failed at 390×844 because the select toggle's enlarged hit area (`::after`) sat above the native checkbox and caught the click; the checkbox now stacks above it. The review of this run's screenshots also led to a scroll fade for the phone bulk bar and to the harness waiting for running animations before each evidence screenshot (the detail drawer was captured mid-slide). |
