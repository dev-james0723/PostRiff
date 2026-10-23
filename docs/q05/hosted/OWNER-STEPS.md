# Q-05 hosted probe — owner steps (minimal)

This runs the cross-tenant isolation probe against the live site from GitHub Actions, so your Mac
can stay off. It never deploys or changes anything; it signs in two throwaway accounts and checks
that neither can read or write the other's data. Everything has already been tested offline; these
are the only steps you do.

## One time

1. **Make two throwaway accounts the normal way.** On the website, sign up account **A** and
   account **B** exactly like any customer (Google, or "email me a code"). Use two e-mail addresses
   you control. Do not turn on two-factor for them. (Do **not** add users in the Supabase
   dashboard — these must be real sign-ups.)
2. **Create the GitHub Environment** (GitHub → the repo → Settings → Environments → New
   environment), name it exactly `rafii-q05-probe`:
   - Required reviewers: **you**. Turn **Prevent self-review OFF** (you are also the pusher).
   - Deployment branches: **Selected**, pattern `claude/discord-q05-run-*`.
3. **Add these Environment secrets** (Settings → Environments → rafii-q05-probe → Add secret):
   - `Q05_EMAIL_A` and `Q05_EMAIL_B` — the two addresses you signed up with.
   - `Q05_SUPABASE_PUBLISHABLE_KEY` — the site's Supabase publishable (anon) key. Supabase → the
     project → Project Settings → API → the publishable/anon key. It is not a password; it only
     lets the workflow exchange a login code.

## Each run (about two minutes of yours)

1. On the website sign-in form, choose **"email me a code"** for account A, then for account B.
   (Two separate requests, one per address.)
2. Open each inbox, read the **6-digit code**.
3. In GitHub, set the two Environment secrets **`Q05_CODE_A`** and **`Q05_CODE_B`** to those codes
   (Settings → Environments → rafii-q05-probe → each secret → update value). Do this right before
   approving — codes expire in a few minutes and are single-use, so a leaked code is already dead.
4. Tell the agent to push the request branch. The agent gives you a **short commit id and title** to
   compare.
5. GitHub shows the run as **waiting for review**. Open it, check the commit id and title match what
   the agent told you, and **Approve**. The run signs in both accounts and runs the probe; the result
   (routes and counts only, never ids or your content) appears in the run summary.

**Alternative to the codes:** if the code flow is awkward, you can instead paste a fresh
**access token** for each account into `Q05_TOKEN_A` and `Q05_TOKEN_B` (they expire in about an
hour). The code flow is preferred.

## Afterwards

- Delete the `Q05_CODE_A` / `Q05_CODE_B` (and any `Q05_TOKEN_*`) secrets.
- Delete the two throwaway accounts through the app's own **Account → Delete account** (if the app
  offers it). If it does not, ask the agent to remove them. Removing the environment and its secrets
  when the probe work is finished is also fine.

## Two things worth knowing

- **Personal API tokens do not work for this probe.** Rafii's API tokens (`docs/postriff-api-tokens.md`)
  have a route allowlist that already blocks actions, approvals, connection changes and members — so a
  denial would come from the token's scope, not from tenant isolation, and would be a false pass. The
  probe therefore uses real signed-in sessions (the codes above), never API tokens.
- **A brand-new sign-in from the runner may trip a security check** (new-device or step-up, RAPv2). If
  that blocks one of the probe's own "owner can do this through the same route" control checks, the run
  reports that control as **INCONCLUSIVE and fails loudly** — it never counts a blocked control as a
  pass. If that happens, sign in to the account once in a browser first (to clear the new-device
  prompt), and do not enable two-factor on the throwaway accounts. The run can never send a Discord
  message, and when isolation is healthy it leaves no change in either account.
