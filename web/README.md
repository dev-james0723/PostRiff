# PostRiff web

Next.js 16 app for the PostRiff consumer site and workspace: public marketing pages, Supabase auth (Phase B) and the `/app/*` workspace. The API is the Python WSGI service at the repo root, served under `/api/*`.

## Run locally

```bash
cd web
cp .env.example .env.local   # then fill in what you need
npm install
npm run dev                  # http://localhost:3000
```

In development `next.config.ts` rewrites `/api/*` to `POSTRIFF_API_ORIGIN` (default `http://127.0.0.1:4331`). Start the Python dev harness from the repo root in another terminal:

```bash
LC_ALL=C .venv/bin/python scripts/postriff_dev_hosted.py --port 4331
```

That harness runs the real hosted code on a disposable PostgreSQL with simulated identity and providers (see `docs/postriff-consumer-web/decisions.md`, D14).

## Checks

```bash
npm run typecheck   # tsc --noEmit
npm run lint        # oxlint src
npm run build       # next build
```

## Layout

- `src/app/(marketing)` public pages; `src/app/auth` sign-in / sign-up; `src/app/app` the workspace.
- `src/config/site.ts` site identity and public links; `src/config/nav-config.ts` app navigation; `src/config/legal.ts` legal review gate.
- `src/lib/supabase` browser / server / proxy clients; `src/proxy.ts` refreshes the session and gates `/app/*`.
- `src/lib/auth/access.tsx` workspace access context (stubbed until Phase B).
- `src/components/marketing` header, footer, section, hero, CTA band and capability badge.
- Icons only via `@/components/icons`.

## Deploying

On Vercel, `/api/*` is routed to the Python service by the repo-root `vercel.json`; do not set `POSTRIFF_API_ORIGIN` there. Set `NEXT_PUBLIC_APP_URL` to the public origin.
