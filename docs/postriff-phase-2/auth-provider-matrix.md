# Auth provider qualification

2026-09-14. Two temporary Production validation accounts were created and deleted. Emails/SMS/OAuth consents sent: **0**.

| Provider | Local state | Hosted requirement |
|---|---|---|
| Google | Expiring state/PKCE-bound verification fixture; replay, denial, cancel and recovery tested | Exact Supabase project, configured OAuth client, redirect allowlist and real callback/session integration |
| Email | Deterministic code fixture; linked identity and recovery tested; nothing delivered | SMTP/delivery configuration, abuse controls and real OTP/link verification on the exact domain |
| Apple | Disabled with Needs setup | Developer configuration, redirect/signing keys, qualification and consent |
| Microsoft | Disabled with Needs setup | Application/tenant configuration, redirect and qualification |
| Phone | Disabled with Needs setup | Approved SMS provider, country/cost/abuse policy and actual verification; no live SMS approval exists |

The fixture creates identity, workspace, owner membership, device and one 14-day trial atomically. Replaying a callback does not create another workspace/grant. Wrong identity, incorrect proof/PKCE, cancellation and expiry create nothing. Only Studio and Assist are available; Business cannot start a trial. Switching plans preserves the original expiry and shared ten-request grant. All three released neutral skills remain included.

Account identity, workspace authorization, social permissions and external runtime access are distinct records. A linked identity may not merge two accounts. The last recovery method cannot be removed. Session revocation and 24-hour local expiry deny old credentials; recovery creates a new device on the same workspace. Deleted accounts keep a minimal identity/trial tombstone, with workspace/media/session data removed. In-flight outcomes must be reconciled before deleting their evidence.

`SupabaseSessionCandidate` accepts a principal only from the exact project's successful server-side user response. Editable user metadata cannot select a different actor or role. [Supabase's advanced auth guide](https://supabase.com/docs/guides/auth/server-side/advanced-guide) distinguishes server session checks, PKCE, refresh and cache behavior. [Identity linking](https://supabase.com/docs/guides/auth/auth-identity-linking) remains a separate operation.

The Supabase hosted route/session composition now passes synthetic Production refresh, restoration, logout revocation, export and account deletion. It does not qualify Google OAuth, delivered email/SMS, or provider-specific token refresh/unlink. Those provider onboarding gates remain external.
