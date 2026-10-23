# Q-05 hosted probe — owner steps (minimal)

This runs the cross-tenant isolation probe against the live site from GitHub Actions, so your Mac
can stay off. It never deploys or changes anything; it signs in two throwaway accounts and checks
that neither can read or write the other's data. Everything has already been tested offline; these
are the only steps you do.

> **Never paste a login code, access token, or any secret into the chat with the agent.** The agent
> never needs them and never asks for them. Codes and keys go **only** into GitHub Environment secret
> fields (below). A value typed into chat is leaked.

## One time

1. **Make two throwaway accounts the normal way.** On the website, sign up account **A** and
   account **B** exactly like any customer (Google, or "email me a code"). Use two e-mail addresses
   you control, and do **not** turn on two-factor for them. (Do **not** add users in the Supabase
   dashboard — these must be real sign-ups.)
   - Each address's **local part must contain the marker `q05`** (plus-addressing works, e.g.
     `you+q05a@gmail.com` and `you+q05b@gmail.com`). The workflow refuses any e-mail without the
     marker, so one of your everyday accounts can never be used against the live site by mistake.
2. **Create the GitHub Environment** (GitHub → the repo → Settings → Environments → New
   environment), name it exactly `rafii-q05-probe`:
   - Required reviewers: **you**. Turn **Prevent self-review OFF** (you are also the pusher).
   - Deployment branches: **Selected**, pattern `claude/discord-q05-run-*`.
3. **Add these Environment secrets** (Settings → Environments → rafii-q05-probe → Add secret):
   - `Q05_EMAIL_A` and `Q05_EMAIL_B` — the two addresses you signed up with.
   - `Q05_SUPABASE_PUBLISHABLE_KEY` — the site's Supabase **publishable (anon)** key. Supabase → the
     project → Project Settings → API → the publishable/anon key. It is not a password; it only lets
     the workflow exchange a login code. The workflow refuses a secret or `service_role` key, so do
     not paste one of those by mistake.

## Each run (about two minutes of yours)

1. On the website sign-in form, choose **"email me a code"** for account A, then for account B
   (two separate requests, one per address). **Only request the code — do not type it into the
   website and do not finish signing in there.** The workflow does the verification.
2. Open each inbox and read the **6-digit code**.
3. In GitHub, set the two Environment secrets **`Q05_CODE_A`** and **`Q05_CODE_B`** to those codes
   (Settings → Environments → rafii-q05-probe → each secret → update value). The codes are
   **single-use and short-lived** — the provider decides how long, and it is not guaranteed, so treat
   them as expiring soon: set them and approve **right away**. Put the codes **only** in these secret
   fields — never in the chat and never back into the website.
4. Tell the agent to push the request branch. The agent gives you a **commit id and title**. Compare
   **at least the first 12 hex characters** of the commit id (a 7-character short id is not enough to
   trust) and the title.
5. GitHub shows the run as **waiting for review**. Open it, confirm the commit id (≥12 hex) and the
   title match what the agent told you, and **Approve**. The run signs in both accounts and runs the
   probe; the result (route **templates** and counts only — never ids, tokens, or your content)
   appears in the run summary. Both sessions are signed out automatically when the run ends.
6. **Copy the run's receipt** — the step-summary block (project, SHA, serving `sourceRevision`, the
   counts, and PASS / INCONCLUSIVE / FAIL) — into the Q-05 ledger for the gate record.

## Tell the Release Captain before you approve

- A healthy run makes roughly **40 cross-tenant requests that are correctly denied** (about forty
  `403`s). That volume can trip the **H-07 cross-tenant alert**. Let the Release Captain know a Q-05
  run is about to happen, so the spike is expected and not handled as an incident.
- Each run also sends **two login e-mails** (one per account), which counts against the provider's
  e-mail / OTP rate budget. Don't re-run many times in quick succession.

## Afterwards

- Delete the `Q05_CODE_A` / `Q05_CODE_B` secrets.
- Delete the two throwaway accounts through the app's own **Account → Delete account** (if the app
  offers it). If it does not, ask the agent to remove them. Removing the environment and its secrets
  when the probe work is finished is also fine.

## Two things worth knowing

- **Personal API tokens do not work for this probe.** Rafii's API tokens (`docs/postriff-api-tokens.md`)
  have a route allowlist that already blocks actions, approvals, connection changes and members — so a
  denial would come from the token's scope, not from tenant isolation, and would be a false pass. The
  probe therefore uses real signed-in sessions (the codes above), never API tokens.
- **A brand-new sign-in from the runner may trip a security check** (new-device or step-up, RAPv2). If
  that blocks one of the probe's own positive-control checks (the "owner **can** do this through the
  same route" checks), the run reports that control as **INCONCLUSIVE and fails loudly** — it never
  counts a blocked control as a pass. The run can never send a Discord message.

## If this is a gate run (release candidate, not the current live build)

A gate run exercises the real write routes, so set the throwaway accounts up first:

- Prefer **drafts / pending-review** objects, and make sure any Discord object the probe might touch
  is **not actually sendable** (for example an approved job should be scheduled **at least 7 days
  out**, so even a mistakenly-accepted write cannot post before you cancel it; cancel it afterward).
- See `docs/q05/PLAN.md` for the full gate-mode method; the request must pin the promoted build's
  `expectSourceRevision`, and the workflow refuses to run if the serving build does not match.
