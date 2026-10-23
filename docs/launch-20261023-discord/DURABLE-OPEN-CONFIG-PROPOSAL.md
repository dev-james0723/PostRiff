# PROPOSAL: keep the Discord opening and the server cap from being lost by a later build

Written 2026-10-23 about 04:35Z at the owner's request (`AUTHORIZATION-RECORD.md`, reply 13: "propose how to persist the open configuration and the server cap in the formal project settings, so a build that forgets them cannot close the service by accident; Production settings are not changed without a separate approval"). **This is a proposal. Nothing in Production, in the project settings or in any environment variable has been changed.**

## 1. The problem, exactly

Three values decide whether a customer can use Discord. Today they exist only as `--env` flags on the build command of the open build (`d2` in `BUILD-VIA-GITHUB-ACTIONS.md`):

| Name | Open value | If a later build omits it (code on `2a5a523d`, `discord/launch_gate.py`) |
|---|---|---|
| `POSTRIFF_DISCORD_CONNECT_WORKSPACES` | `*` | unset on hosted production means **closed for every workspace that has no Discord history**; existing connections keep working. New customers see "not open yet" |
| `POSTRIFF_DISCORD_GUILD_CAP` | `10000` | unset on hosted production means **90 servers**; the 91st customer is refused with "no room" |
| `POSTRIFF_OAUTH_DISCORD_REVIEWED` | `true` | unset means the Direct publishing review flag is off; publishing stays disabled |

A build made by a different path (another lane's CLI build, a Git build, a dashboard redeploy, a rollback to an earlier build) carries none of them. Failure mode: **silent**, partial and customer-visible. This already happened to the Discord code itself on 2026-10-21 (`S-01-lineage-report.md`: later CLI builds shipped one lineage and omitted the other).

## 2. Options

| Option | What it is | For | Against |
|---|---|---|---|
| **A. Project variables** (Production target) | The three names set once as project environment variables, plus the worker and lane switches already there | Every future build gets them, whichever path built it; no code change; the simplest fix for the exact failure above | They apply to every build of the project, including other lanes' builds (harmless where the code does not exist); a changed value still needs a new build to reach customers; **the dark twin and the "promote the dark twin to close connections" step rely on a build-level `--env` overriding the project value, and I could not confirm that precedence from the documentation I could read: it must be proven on one staged build before anything depends on it** |
| **B. Read the effective configuration back, and alert on drift** | A small, additive, read-only report of what the serving build actually uses: connect gate mode (closed, list of N workspaces, open), cap, reviewed flag, lane readiness, rate policy days left, source revision. Served behind the cron secret (so it is not public), polled by the monitor; an alert fires when the serving build's gate is not open, or the cap is below 10,000, after the opening | Detects the omission within minutes instead of when a customer complains; needs no change to Production settings; also gives G7 and the acceptance receipts a direct read-back instead of inferring from a build log | Detects, does not prevent; a small code change in the final SHA (reviewed with it) |
| **C. Runtime configuration in the database** | A tiny table for the gate and the cap read at request time with a short cache; the environment stays as the fail-closed default | Opening, closing and raising the cap in seconds from a phone with one statement, no build, no promotion; best for H-07 | New migration and a change to `launch_gate.py`, the most security-sensitive file of the release: a new frozen SHA, new reviews, and a new place where a wrong write opens or closes Discord. Not for this release |

## 3. Recommendation

1. **B goes into the final SHA** (it is additive and read-only; the independent review covers it with the rest). It is what makes the opening observable, which the fresh-customer receipt and the alerts need anyway.
2. **A is applied at the opening step only**, as its own approval line in the packet, together with the open build: the three names, Production target, plain values, read back by name and value from a second listing, exactly as the earlier seven were. Not before: with the project value `*` in place, any build without a build-level override is open, including the dark twin, and the dark stage must stay tester-only.
3. **Before A is applied, prove the precedence once**: the dark build of the final SHA carries a build-level gate list while a harmless project variable of the same kind is set, or the documentation is found; if the build-level value does not win, the dark twin must be built before A is applied, and the "close new connections" step of the ladder becomes the database hold plus a rollback promotion instead of promoting the dark twin.
4. **C is a later improvement**, not part of this release.

Strongest argument against A: it turns the open state into an implicit property of the project, so any accidental build (another lane's) is an open build. Biggest risk: the precedence assumption in 3. What would change the recommendation: finding that a build-level value does not override the project value (then A waits until after the dark twin exists and the ladder changes), or the owner preferring seconds-level control (then C, with a new SHA).

## 4. What the owner would be asked to approve later

One line in Packet 3, only at stage 5c: "set `POSTRIFF_DISCORD_CONNECT_WORKSPACES=*`, `POSTRIFF_DISCORD_GUILD_CAP=10000`, `POSTRIFF_OAUTH_DISCORD_REVIEWED=true` as Production project variables, read back by name and value". Until that approval the agent changes nothing.
