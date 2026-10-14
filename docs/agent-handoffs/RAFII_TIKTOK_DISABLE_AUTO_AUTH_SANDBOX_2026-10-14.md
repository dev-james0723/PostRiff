# Rafii × TikTok — Sandbox explicit-consent OAuth test

**Date:** 2026-10-14
**Branch:** `codex/rafii-tiktok-sandbox-oauth-20261013`
**Starting commit:** `b6a647e98da195b6706b4cbd616eb48cdfc26a0f`
**Deployment target:** existing protected TikTok Preview at `https://rafii-tiktok-sandbox-650aea72.vercel.app`
**Hard restrictions:** no Production modification, Merge, TikTok posting, App Review submission, or automated TikTok consent.

## Observed failure (live, before this patch)

- Rafii Google login succeeded on the exact Preview origin after the Staging Supabase redirect whitelist was corrected.
- Channels → TikTok → **Account only** generated OAuth with only `user.info.basic`, then navigated to TikTok's official `/v2/auth/authorize/` endpoint.
- The browser later landed at TikTok homepage with no observed approval page, callback, code exchange, or linked account. TikTok web login was `@jamesaucreates`, matching the Sandbox Target User. This does **not** prove the source of the provider-side redirect.
- TikTok Login Kit for Web documents `disable_auto_auth=1` as **always show authorization page**: https://developers.tiktok.com/docs/en/login-kit-web

## Isolated change

- `src/postriff_phase2/wave3_connectors.py` now includes `disable_auto_auth=1` **only when `TikTokProvider.sandbox_mode` is true**. All OAuth parameters, state, redirect URI, scopes and optional PKCE stay unchanged.
- `tests/test_tiktok_sandbox_oauth.py` asserts the flag appears on Sandbox identity-only URLs and is **absent** from Production OAuth URLs.
- No schema/migration, secret, credentials, publishing capability, feature flag, redirect, or customer data changes.

## Test evidence

1. Before the fix, newly added Sandbox URL assertion failed as expected: `KeyError: 'disable_auto_auth'`, while Production absence assertion passed.
2. After fix, the two targeted unit tests passed (2/2).
3. Relevant Python regression suite passed **124/124** using existing `.venv`: `PYTHONPATH=src:tests .venv/bin/python -m unittest -q test_hosted_wave1_connectors test_hosted_wave3_connectors test_tiktok_sandbox_oauth test_social_readiness_hardening test_social_voice_onboarding`.
4. UI deep-link/readiness Node suite passed **3/3**: `node --test web/tests/channels-connect-deeplink.test.cjs web/tests/provider-readiness-label.test.mjs` (nonfatal MODULE_TYPELESS_PACKAGE_JSON warning).
5. `git diff --check` passed before commit.
6. Entire 303-module Python test tree **not executed** to avoid unrelated integration side effects; no claim of full-suite acceptance.

## Deployment guardrails

1. Verify clean isolated Git branch and exact Git parent `b6a647e9`, with only the two source/test edits and this handoff.
2. Verify remote `rafii.io` Production alias remains untouched. Leave GitHub branches unmerged; avoid a GitHub Push if local CLI supports using branch-scoped Preview env values.
3. Create a **new protected Preview candidate** from the isolated commit, with `--skip-domain` and `RAFII_VIDEO_UPLOADS_ENABLED=false`. Never deploy to Production.
4. Wait for Vercel `READY` and confirm HTTP `/api/health` includes exact new source revision, configured=true; check release gates and identity-only provider readiness.
5. Only then update the **existing Preview alias**, preserving `rafii.io`.
6. On Mac, resume Rafii logged-in Chrome session; use `/app/channels?connect=tiktok&capability=identity`, prepare OAuth, confirm `scope=user.info.basic` and new flag.
7. Follow real TikTok authorization URL. **Stop at TikTok consent/login screen**; do not click Allow/Authorize. If TikTok redirects to homepage again, record the observed result and stop — no synthetic success.

## Rollback

Previously verified protected Preview: `dpl_8xfSD26qq9n8fAaDmiASBV5Fzyse`.
Reassign only alias `rafii-tiktok-sandbox-650aea72.vercel.app` to that deployment if the new Preview fails; never change `rafii.io`. The change is add-only URL parameter and fully reversible via reverting the isolated Git commit. Never reset or force-push unrelated work.

## Acceptance state

- Local URL generation test: **VERIFIED**.
- TikTok consent screen from live provider: **NOT YET VERIFIED**.
- Token exchange / connected account: **NOT RUN, not permitted to consent on the user's behalf**.
- Production app readiness: **UNCHANGED**.
