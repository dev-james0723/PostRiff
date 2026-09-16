# Zhihu browser integration receipt

State: installed and locally tested; dedicated browser login started; identity unverified; zero live posts submitted.
Target selected by James: https://www.zhihu.com/people/tie4gka
Route: controlled_browser / zhihu-browser/1. No OAuth/API setup.
Upstream: liuboacean/zhihu-automation-skill @ 9aca95da75ffd0238174ba9ed2438f4c519ce233, MIT. Selective text 想法 adaptation, not unchanged upstream installation. Articles/answers remain draft-only; no media, engagement or schedules.

Installed runtime: /Users/ouxianxing/Documents/James-Au-Studio/src/james_au_social/zhihu_browser.py
Installed orchestrator routing: /Users/ouxianxing/.codex/skills/james-au-social-orchestrator/references/zhihu-browser.md
Studio: http://127.0.0.1:4310 → Channels → Zhihu

Validation:
- 12 Zhihu tests passed: 10 safety tests, Chromium fixture, owner-boundary API. Simulated posting only.
- 8 setup tests and 26 security tests passed.
- Workspace frontend: 51 passed; build passed.
- Installed merged frontend: build passed; 65/66 tests passed. Existing unrelated connections-api.test.ts expects YouTube read-only scopes; existing connector also requests youtube.upload. Neither file changed here.
- Installed UI smoke passed: exact tie4gka/text preview, disabled submit before identity/approval. Screenshot visually inspected.
- python3 scripts/verify_project.py passed with historical baseline preserved and an exact checksum-bound two-file Zhihu overlay check.
- Scoped merge preserves newer installed channel integrations. Backups, candidate diff and checksum receipts are included.

Pending: finish private browser login, close the dedicated browser, reply login complete. No private login surface was observed. Verify authenticated header profile link and own-profile edit control, then obtain approval for live-test-preview.json: exact text, public audience, immediate time, no media/derivatives. Fresh permalink read must match author and complete text. Unknown attempts are retained and reconciled, never retried automatically.

Live selectors and account eligibility remain unverified. Official Zhihu terms page was unavailable to research tool. No official API or platform endorsement claim. The pilot never enables all-format/campaign scheduling readiness.

## Login recovery

User reported Zhihu 10001 on the Testing browser. Exact provider cause unconfirmed. Switched to installed Google Chrome stable via Playwright channel=chrome and a separate owner-only chrome-profile; old profile preserved, no cookie extraction or security bypass. Twelve tests passed including stable Chrome fixture. Live login and posting remain unverified.
