# UI simplification audit — 2026-09-24

Implements `docs/Raffi_UI_Simplification_Information_Density_Engineering_Spec_2026-09-24.md` across the customer app (`web/src`). Each file below is one area's KEEP / COMPRESS / MOVE / REMOVE table plus its structural changes and intentionally kept copy.

| Area | File |
|---|---|
| Usage & plan | [usage-plan.md](usage-plan.md) |
| Home, Raffi chat, composer, voice, image generation, planning, Overview | [ai-home.md](ai-home.md) |
| Brand & voice (Brand Brain, Learn my voice), Memory, Members, Roles, Audit log, onboarding tours, sign-in/up, invitations | [brand-onboarding.md](brand-onboarding.md) |
| Channels and connection flows, Inbox, Analytics | [channels-inbox-analytics.md](channels-inbox-analytics.md) |
| Ideas, Drafts, approvals, Queue, scheduling, publishing, Calendar, Library, post previews | [content-pipeline.md](content-pipeline.md) |
| Profile, Notifications, Privacy & data, API & integrations, Models | [account.md](account.md) |
| App shell (sidebar, header, account menu, notifications, command palette, gates, errors), shared components, Automations | [shell-automations.md](shell-automations.md) |

## Shared pieces added

- `web/src/lib/status-labels.ts`: the one status vocabulary (Connected, Disconnected, Needs reconnect, Draft, Needs review, Scheduled, Published, Failed, Trial, Saved …). Channel badges, queue and job states, members and automations read from it.
- `web/src/features/queue/job-status.ts`: publishing-job states mapped onto those words; the precise reason moves to the tooltip.
- `web/scripts/copy-audit.mjs` (`npm run audit:copy`): lists suspicious customer-facing phrases for manual review; `--check` fails on implementation words (deployment, backend, database, payload, schema, staging).
- `web/tests/ui-simplification.test.mjs`: regression guards for Usage & plan, the status vocabulary and the implementation-word check.

## Copy review checklist (spec §35)

Before shipping any new customer-facing text:

1. **Can this be deleted?** If the title, the state or the button already says it, delete it.
2. **Can this be shorter?** Buttons 1–3 words, helper text one short sentence, empty states a title plus one action.
3. **Can this appear only when relevant?** Prefer an InfoTip, a Details disclosure, or an inline message after the action fails.
4. **Is it user language?** No deployment, backend, provider, payload, schema, environment or API internals. Say the platform's name and what the person can do ("Instagram disconnected" · Reconnect).
5. **Is it a status?** Use `STATUS` from `lib/status-labels.ts`.
6. **Keep it explicit** when it concerns money, charges, renewal, privacy, permissions, security, legal consent, public publishing or anything irreversible.

Run `npm run audit:copy` and `node --test web/tests/ui-simplification.test.mjs` before merging UI copy.

## Release hardening (server copy and naming)

- **Server copy that reached customers** was rewritten at the source:
  - LinkedIn's `accountRequirement` is now just "LinkedIn member profile."; the card's "Can't import past posts right now." covers the limit.
  - Every "this deployment / this server" error is now a plain state ("Billing isn't available yet.").
  - Model-provider, credential, media-storage and spending-limit errors now say what happened and what to do.
  - Channel capability notes and writer descriptions no longer mention scopes, runtime identity or routing.
  - The memory-file placeholder text is shorter.
- **Plan names:** `billing.plan_display_label` drops a trailing parenthetical note from `pr_plan_terms.label` in the usage view and the plan-active email. "Studio Assist (bounded-batch experiment)" shows as "Studio Assist"; the row itself is unchanged.
- **Memory files** show as Identity / Voice / Boundaries / Brand / How Rafii works (`memoryFileLabel`). The API keys (`VOICE.md` …) are unchanged, because writers receive them by those names.
- **Product name:** customer-visible text says "Rafii" in the web app (marketing and legal pages included), in server messages and in emails. `npm run audit:copy -- --check` fails on "PostRiff" or other spellings in any readable line.
  - "PostRiff" stays only in identifiers: package and module names, environment variables, `X-PostRiff-*` headers, storage keys, the `PostRiffApi` type, the `PostRiff research/0.1` user agent, stored profile answer values, model prompts, the local founder-alpha tool and docs.

## Known remaining items

- **Existing channel records** keep the capability notes written when they connected; reconnecting refreshes them.
- **The email sender name** comes from the `EMAIL_FROM` environment variable in production; check it says Rafii.
- **`automation-lifecycle.ts` labels** must stay equal to `tests/fixtures/automation_lifecycle.json`, which the server reads too. Moving "Ready for review" to "Needs review" needs a server and fixture change.
- **The "Proposed price" badge** on plans reflects unapproved commercial terms. It stays until prices are approved.
