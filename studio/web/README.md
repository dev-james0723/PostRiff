# James Au Studio — local workspace and Phase B drafting bridge

Real React + TypeScript interface for the same-origin Studio API. No mock backend,
localStorage draft database, live publishing or scheduling. The Phase B panel
uses the separately qualified backend Codex CLI transport; readiness is read
from the server, never inferred from an installed skill.

`npm ci --ignore-scripts --no-fund --no-audit` installs the exact lockfile.
`npm run build` type-checks and produces `dist/` for the loopback Python service.
The service must serve this build and `/api/` together so its local owner session
and Host/Origin checks apply. A standalone Vite preview cannot substitute for it.

Design: original charcoal/paper/rust editorial workspace, promoted into locally
compiled Tailwind theme variables. GSAP 3.13.0 uses scoped `useGSAP` cleanup and
`matchMedia` reduced-motion handling; only headings animate, not focused controls.
There are no runtime CDN, web-font, image-provider or external analytics requests.

Frontend direct dependencies: React/ReactDOM (MIT), GSAP and @gsap/react
([GSAP Standard No Charge License](https://gsap.com/community/standard-license/),
checked 2026-09-13 against package metadata and official terms). This UI uses
GSAP for navigation orientation, not a visual animation authoring tool. Build tooling: Vite,
Tailwind and React Vite plugin (MIT), TypeScript (Apache-2.0), React types (MIT).
Exact versions and transitive integrity values are in `package-lock.json`.

Draft saving uses expected revisions. Conflicts retain unsaved input and offer a
recovery Markdown download or an explicitly confirmed reload. Archive is
recoverable. Template versions and local assets remain server records. Calendar
dates are labelled local plans, never publishing jobs. Copy-to-Codex is an
explicit clipboard fallback and does not claim an agent ran.

Guided drafting persists one-question intake, then shows the exact input snapshot,
instruction hashes and model-usage notice in a native review dialog. Only an
explicit checked consent plus Generate sends a model request. Status polling is
bounded and cannot generate/retry. Cancel targets a tracked run. Candidate
application is another explicit owner action, selected-channel-only, guarded by
the saved draft revision and dirty editor state. Failed/interrupted work stays
honest. Unsaved guided answers participate in navigation/unload warnings.

`npm test` runs isolated API-boundary tests (stubbed fetch in tests only), including
no automatic generation/retry, idempotency payloads, consent, polling, cancellation,
chosen-copy application and Phase A regression checks. This is not a real-provider
verification; the main integration task runs that separately.

Primary browser acceptance is run by the main integration task against the real
API: empty workspace → source/angle → independent English/Chinese native copies
→ template/Guizang → local asset → proposed time → save → reload/restart; plus
conflict, archived restore, template version, backup and desktop/mobile checks.
