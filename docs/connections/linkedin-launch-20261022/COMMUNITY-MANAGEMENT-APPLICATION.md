# LinkedIn Community Management API: application packet

Prepared 2026-10-21. Use it to unlock LinkedIn Company Pages (post, analytics, comments, replies) and personal post analytics in Rafii.

**Status:** not submitted. The steps marked **James** need the person who owns Rafii's legal entity and is super admin of Rafii's LinkedIn Page.

## Why it is a separate app

LinkedIn requires the Community Management API to be the **only product on its developer app**. That rule is in the Community Management overview and the partner support guide.

Rafii's current app holds two products:

- Sign In with LinkedIn using OpenID Connect
- Share on LinkedIn

That app keeps doing member sign-in and posting. A second app carries Community Management, with its own client ID and secret.

## What it unlocks

| Rafii capability | Scope | Notes |
|---|---|---|
| Company Page identity | `r_organization_admin` | Lists the Pages where the member is an admin |
| Company Page publish and schedule | `w_organization_social`, `rw_organization_admin` | Rafii still holds scheduled posts itself; LinkedIn has no native scheduling |
| Company Page posts and comments read | `r_organization_social`, `r_organization_social_feed` | Storage limit: 6 weeks for organization social activity |
| Company Page replies | `w_organization_social_feed` | |
| Company Page analytics | `rw_organization_admin`, `r_organization_social` | |
| Personal post analytics | `r_member_postAnalytics` | |

Not unlockable by any application:

- Reading or replying to comments on **personal** profiles. `r_member_social` is closed and accepts no new access requests.

## Development tier

**Limits:** 500 calls per app per day, 100 per member per day, no webhooks. You have 12 months to finish building before you upgrade.

1. **James:** go to linkedin.com/developers and choose Create app.
   - **Name:** `Rafii Pages`. No "LinkedIn" or Microsoft names or logos.
   - **LinkedIn Page:** Rafii's company Page.
   - **Privacy policy URL:** https://rafii.io/privacy
   - **Logo:** the Rafii mark.
2. **James:** on the app's Settings tab, choose Verify. Approve the request from the Page's super admin account.
3. **James:** on the Products tab, request Community Management API and fill in the vetting form within 21 days. Suggested answers:
   - **Organization:** Rafii's registered legal entity name and registration country.
   - **Website and domain:** rafii.io
   - **Business email:** an email address @rafii.io. Personal mail domains are rejected.
   - **Use case:** "Rafii is a social media workspace. Page admins connect their LinkedIn Page, write or approve each post, and Rafii publishes it at the time they choose. Admins see their Page's post analytics and comments in Rafii and approve every reply before Rafii sends it. Nothing posts without a person approving it."
   - **Data handling:**
     - Tokens are encrypted at rest.
     - Disconnecting the Page deletes them.
     - Organization social activity is kept at most 6 weeks.
     - Member data is never sold or used for ads.
     - A deletion request is completed within 10 days.
4. **Engineering (any agent), after LinkedIn grants Development access:**
   - Add the new app's credentials to production as `POSTRIFF_OAUTH_LINKEDIN_ORG_*`, following the existing `POSTRIFF_OAUTH_LINKEDIN_*` naming.
   - Register the redirect URI `https://rafii.io/api/oauth/<provider id>/callback`, using the new adapter's provider ID. The URI is built in `oauth.py`; the member app's is `https://rafii.io/api/oauth/linkedin/callback`.
   - Turn on the `organization_*` capabilities in `src/postriff_phase2/providers.py`. They already exist there and are disabled.

## Standard tier

Apply for Standard tier once Development tier is working end to end.

1. **James:** record a narrated, high-resolution screencast and upload it somewhere LinkedIn can download it. It should show:
   - a Page admin connecting the Page through LinkedIn OAuth;
   - choosing the Page;
   - writing and approving a post, then scheduling it;
   - the post appearing on LinkedIn;
   - the analytics view;
   - the comment list, including which commenter fields Rafii shows;
   - approving a reply;
   - disconnecting.
2. **James:** submit test credentials and a company and product overview.

**If LinkedIn rejects the application:** you cannot re-apply on the same app. Create a new app and start again.

## Sources (checked 2026-10-21)

- https://learn.microsoft.com/en-us/linkedin/marketing/community-management-app-review
- https://learn.microsoft.com/en-us/linkedin/marketing/increasing-access
- https://learn.microsoft.com/en-us/linkedin/marketing/community-management/community-management-overview
- https://learn.microsoft.com/en-us/linkedin/shared/linkedin-api-partner-support-guide
- https://learn.microsoft.com/en-us/linkedin/marketing/data-storage-requirements
