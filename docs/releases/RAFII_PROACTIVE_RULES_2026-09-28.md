# Rafii custom proactive call rules — release receipt

Status: release in progress. This branch implements and locally verifies the feature; commit, push, production deployment, and live acceptance are recorded separately below.

## Delivered scope

- In Phone Mode settings, a user can choose preset call situations or write a custom **when** condition and a separate **what to discuss** prompt. The form previews the compiled trigger. New and edited rules stay paused until the user explicitly enables them. A rule can be paused or deleted.
- The initial custom vocabulary covers a failed publication (including two or three failures within 24 hours), an uncertain publication outcome, an approval due within 24 hours, a blocked campaign, and a channel needing reconnection. Unsupported conditions fail closed. The user can save up to five rules. This is a bounded natural-language compiler, not an unrestricted model-driven trigger.
- Matching uses persisted notification events in the user's workspace. Planning, request, and delivery recheck the reviewed rule, version, global phone/proactive flags, verified number, membership, quiet hours, daily call count, credit and provider budgets, active call, and duplicate limits. Custom calls have a 24-hour per-rule cooldown. Editing or disabling a rule revokes queued custom calls before phone egress. The event must still be unresolved and recent at delivery.
- The discussion text enters the existing Rafii phone-agent turn only after connection. It has no direct telephony-provider field and does not bypass the agent's existing action approvals.
- Existing preset calls and direct **Have Rafii call me** remain available. The custom-rule form itself never places a call.

## Validation

- 25 focused Python unit tests passed, including every supported event mapping and rejection of unsupported conditions.
- Disposable PostgreSQL Phone Mode acceptance passed with synthetic events and fake telephony, including two failures of the same post, one call, and edit revocation.
- Frontend lint and TypeScript checks passed. The local optimized Next.js production build passed.
- Browser acceptance passed with the local fake-phone and deterministic agent harness on disposable PostgreSQL: custom rule review, activation, edit revocation and deletion placed zero calls; the existing explicit call, delegation, mobile, and accessibility journey also passed. Real calls: zero.
- The repository secret scan passed with no unexpected findings. `git diff --check` passed.

## Release state

- Commit and push: pending.
- Production deployment and alias verification: pending.
- Production configuration: Phone Mode and outbound flags are on; the proactive flag is off. The production database credential is redacted in the available Vercel environment read, so the count of previously opted-in users could not be checked. Enabling the flag could cause paid calls under existing user settings and requires a separate scoped decision.
- Live PSTN and real GPT-Live conversation: not run. No paid provider or model call is part of this receipt.
