# C-01 Environment matrix for the release candidate (names only)

No value in this file is secret and none was read from production. "Where" says whether a setting lives in project env (Production target, applies to builds made after the change) or only on a build command (`vercel deploy --env`), which keeps the dangerous values out of project env so an accidental rebuild can only close things.

| Name | Purpose | Wave 1 target | Where | Applied by | Read back by |
|---|---|---|---|---|---|
| `POSTRIFF_OAUTH_DISCORD_CLIENT_ID`, `POSTRIFF_OAUTH_DISCORD_CLIENT_SECRET` | Discord application credentials | present, unchanged | project env | owner only | name only (`vercel env ls`) |
| `POSTRIFF_DISCORD_BOT_TOKEN` | the shared bot | present, unchanged | project env | owner only | name only |
| `POSTRIFF_PUBLIC_BASE_URL` | builds the redirect URI `https://rafii.io/api/oauth/discord/callback` | `https://rafii.io` | project env | verify only | name only |
| `POSTRIFF_CREDENTIAL_KEY` | encrypts stored provider tokens | present | project env | owner only | name only |
| `CRON_SECRET` | authorises `/api/cron/worker` | present | project env | owner only | name only |
| `POSTRIFF_OAUTH_DISCORD_CALLBACK_ORIGIN` | optional pinned callback origin | unset | project env | verify only | name only |
| `POSTRIFF_DISCORD_AUTHORIZATION_V2_ENABLED` | destination and approval authority v2; needed for schedule to be Direct | `true` (exact string) | project env, type `plain` | AUTH-3 (row 1) | name and value |
| `POSTRIFF_DISCORD_CONNECTIONS_V2_ENABLED` | connections v2 flow (identity link, server pick, install) | `true` | project env, `plain` | AUTH-3 | name and value |
| `POSTRIFF_DISCORD_RATE_LIMITS_V1_ENABLED` | shared PostgreSQL rate coordinator | `true` | project env, `plain` | AUTH-3 | name and value |
| `POSTRIFF_DISCORD_WORKER_V1_ENABLED` | Discord worker lease protocol (accepts `1` or `true`); without it managed Discord jobs are held, not sent | `true` | project env, `plain` | AUTH-3 | name and value |
| `POSTRIFF_DISCORD_RATE_POLICY` | reviewed, expiring pacing policy JSON (not secret); expiry fails every Discord request closed | output of `scripts/discord_rate_policy.py generate`, at least 14 days left at T0 | project env, `plain` | AUTH-4 (row 2) | name and value, plus `check` |
| `POSTRIFF_WORKER_MAX_JOBS`, `POSTRIFF_WORKER_MAX_SECONDS` | per-tick budget for every provider (1 to 25, 1 to 45) | optional `25`, `40`; default `10`, `20` | project env, `plain` | AUTH-3 (row 3, optional) | name and value |
| `POSTRIFF_OAUTH_DISCORD_REVIEWED` | operator declaration that Direct publish is allowed; unset shows publishing as Unsupported | `true` on the two RC builds only | build command `--env` | D-04 (row 4) | deployment env names |
| `POSTRIFF_DISCORD_CONNECT_WORKSPACES` | fail-closed connect gate: unset is closed on production, empty is closed, `*` is open, otherwise workspace UUIDs | D1: tester workspace; D2: `*` | build command `--env` only; never in project env | rows 5 and 6 | catalog `discordAccess` |
| `POSTRIFF_DISCORD_GUILD_CAP` | servers the bot may be in; default 90 on production | 90, or 90 minus the gap to the Portal's own count | build command `--env` when different from the default | rows 5 and 6 | monitoring Q9 |
| `POSTRIFF_OAUTH_DISCORD_DISABLED` | provider-wide kill switch | unset (armed) | a third twin build only, on abort | AUTH-7 step 3 | n/a |
| `POSTRIFF_DISCORD_ENGAGEMENT_V1_ENABLED`, `POSTRIFF_DISCORD_WEBHOOK_V1_ENABLED`, `POSTRIFF_DISCORD_WEBHOOK_QUALIFIED`, `POSTRIFF_DISCORD_USER_INSTALL_V1_ENABLED`, `POSTRIFF_DISCORD_INTERACTION_CONFIG`, `POSTRIFF_DISCORD_MESSAGE_CONTENT_EVIDENCE` | analytics, comments and reply; bot-free webhook mode; User Install and PING; Message Content evidence | unset (off). The code reads only the exact string `true`, so unset is off and no explicit `false` records are needed | none | n/a | absence in the env name list |

## Hazards recorded while building this

- The flags are on only for the literal string `true` (the worker flag also accepts `1`): a value such as `TRUE` or `yes` silently leaves a feature off. Read values back, do not trust that a variable exists.
- Quote every `--env` assignment on the build command, in particular `'POSTRIFF_DISCORD_CONNECT_WORKSPACES=*'`: the `*` is a shell glob character, and zsh (the macOS default shell) stops with "no matches found" instead of passing it. Read the value back from the deployment before promoting it.
- A mistyped Discord v2 flag (anything but the exact string `true`) leaves the v2 flows off and the original Discord connect flow on. On this candidate the original flow is behind the same gate and under the same cap, so a typo cannot open an uncapped path.
- Do not create the new variables as type `sensitive`: sensitive values cannot be read back, which makes this matrix unauditable. Use `plain` for non-secret flags and numbers.
- Project env is shared by every lane. Variables above that are inert without the Discord code are safe to set early; the two dangerous values stay on the build commands.
- 223 of the 271 Production env records could not be listed by the tool available here (a 100-record truncation), so presence of the first five rows is unconfirmed until the owner's `vercel env ls production`.
