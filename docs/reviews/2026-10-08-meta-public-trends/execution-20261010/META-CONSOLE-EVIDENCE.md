# Read-only Meta console evidence — 2026-10-10

Observed through the existing authenticated Chrome Meta for Developers session, approximately 14:04–14:16 UTC. No permission was added, token revealed, account changed, review submitted or public endpoint called.

App: Rafii, Meta app ID 1401844428820097.

- Basic settings: app is Published; rafii.io domain, privacy, terms and data-deletion links configured. Published is not evidence of advanced public-content access.
- App Review submissions: **Not submitted**. New requests include owned Instagram Business permissions, pages_manage_posts, pages_show_list, pages_manage_engagement, instagram_manage_comments, business_management, pages_read_engagement and public_profile. These do not demonstrate any of the three public discovery approvals.
- Use cases currently listed: “Manage messaging & content on Instagram” and “Manage everything on your Page”. No Threads use case appeared in this app's list.
- Instagram permissions table: **Instagram Public Content Access — Add to App Review**; **instagram_basic — Add to App Review**. The current interface explicitly says hashtag tracking requires the Facebook Login setup. Existing Instagram Login business permissions show Ready for testing, which is a separate path.
- Manage Pages permissions table: owned Page scopes show Ready for testing or Add to App Review. A Page Public Content Access approval was not established from this console.

URLs inspected:
- https://developers.facebook.com/apps/1401844428820097/settings/basic/
- https://developers.facebook.com/apps/1401844428820097/app-review/
- https://developers.facebook.com/apps/1401844428820097/use_cases/

Conclusion: Instagram public access is **BLOCKED by actual App Review state**. Facebook PPCA and Threads public access are **UNVERIFIED** pending their exact app/feature/grant evidence. All three remain ineligible for LIVE. No real third-party public observations or JEV provider calls were obtained in this check.
