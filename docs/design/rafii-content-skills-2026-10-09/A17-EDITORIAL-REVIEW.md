# A17 editorial review of composed platform packs (machine-assisted)

> **Status: MACHINE-ASSISTED REVIEW. NOT A HUMAN EDITORIAL SIGN-OFF.**
> An AI agent (Claude Code, model Opus 5.5) performed this review on 2026-10-09. No human editor has reviewed these packs for this document. A17 stays open until the "Human editorial sign-off" section at the end is completed by a person.

Requirement A17 (P0): "Platform-pack review assesses all composed references; no unsupported blanket algorithm claims, required hashtag quotas or fabricated anecdotes."

## 1. Scope and method

**Tree reviewed.** Git worktree `rafii-content-skills-20261009`, HEAD `ea0d753c`. `git diff 5899fa86 HEAD -- skills/` is empty and `skills/` has no uncommitted changes, so the packs reviewed are the ones at `5899fa86`. The branch edits under review are `git diff 220d2de1 5899fa86 -- skills/`: six Chinese-market packs (xiaohongshu 1.1.0→1.2.0, bilibili 1.1.0→1.2.0, douyin, zhihu, weibo, wechat-channels 1.0.0→1.1.0) plus their registry relock.

**What "composed" means here.** I traced the composition in code; I did not assume it.

- `src/postriff_phase2/creation_capabilities.py:222`: each platform row's `skill.required` is `["postriff-content-craft", "postriff-adapter-contract", <channel skill>]`. This is the A17 route: editorial core, then adapter contract, then channel adapter.
- `src/postriff_phase2/skills.py:20-24, 254-269` (`SkillLibrary.bind`): the editorial core is bound with `references/editorial-workflow.md`, `human-voice-pass.md` and `platform-playbooks.md`, always with `algorithm-practice.md`, and with `visual-handoff.md` for visual formats. The adapter contract is bound once, plus one adapter per destination.
- The same `bind` call also adds `postriff-content-engine` (SKILL.md plus `localization.md`, `platform-and-templates.md`, `content-pillars-and-workflows.md`, `research-and-sensitivity.md` and one locale guide per destination language; `skills.py:225-243`), `postriff-research-and-source-log` on cited turns, and, only when `RAFII_SKILL_REGISTRY_V2_ENABLED` is on, the `rafii-humanizer-*` packs (`skill_compiler.py:47-70`). These are not in `skill.required`, but the writer receives them. A17 says "all composed references", so I reviewed them too and score them in separate rows.
- No `postriff-channel-*` package has a `references/` directory (checked with `find`). Each channel pack is a single SKILL.md.
- Native formats advertised per platform come from each adapter's "Native content formats" table (`creation_capabilities.parse_formats`). R2 compares each pack's instructions against that table.

**Method.** I read every file listed in section 6 and scored each pack against R1–R10. A pack's score covers the whole composed route for that platform: a gap in the adapter can be covered by the core (for example, `platform-playbooks.md` covers seven platforms). Wherever a composed shared reference causes a problem, the finding names that file. Evidence quotes are 15 words or fewer, with `file:line` given relative to `skills/`.

**Limits of this review.**
- No builds, tests or network calls were run. I did not open the cited platform URLs in `algorithm-practice.md`, so their existence and content are not independently checked.
- Statements about Mainland China rules (AI-content labelling, advertising disclosure) and about X's automation rules come from the model's training knowledge. They are marked "verify" and are not legal advice.
- A machine reviewer cannot judge whether copy feels native to a reader. That judgement belongs to the human sign-off.

## 2. Rubric

| ID | Criterion | FAIL when | CONCERN when |
| --- | --- | --- | --- |
| R1 | Platform-specific writing conventions present and plausible | Conventions wrong for the platform | Conventions missing/boilerplate only, or rigid enough to misfit common content |
| R2 | Native format compliance with the advertised formats | An instruction contradicts an advertised format | An advertised format has no guidance, or a native field is missing/unexplained |
| R3 | Tone/audience suitability | Tone harmful or clearly wrong for the audience | Tone default may misfit the workspace or conflicts with the core |
| R4 | Chinese localization (Simplified/Traditional, Mainland/TW/HK, written Cantonese) | Wrong script/register instruction | Default could override the destination tag |
| R5 | Mainland China platform conventions (six CN packs; also applied to the other Mainland packs Kuaishou, Tencent QQ, Feishu) | Wrong convention | A material native convention or disclosure is absent |
| R6 | No rigid/mandatory hashtag templates or quotas | Fixed count or mandatory tags | Composed text implies tags are expected by default |
| R7 | No artificial engagement bait | Mandatory bait / fake urgency | Stock CTAs or a compulsory close suggested by default |
| R8 | No unsupported capability or blanket algorithm claims without dated sourcing | Undated, unsourced claim about ranking/penalties stated as fact | Undated enforcement/capability claim, or internally inconsistent capability claim |
| R9 | No instruction that fabricates metrics, testimonials, anecdotes or receipts | Instruction to invent | A default (e.g. mandatory first person) pushes toward invented experience |
| R10 | Scripts vs assets vs drafts vs finished content | Says or implies a script/draft is the finished asset | Distinction absent where a video/asset format is advertised |

N/A = criterion does not apply (R4 for non-Chinese packs; R5 outside Mainland China).

## 3. Per-pack results

Versions and sha256 prefixes come from `skills/rafii-registry.json` (`version` equals `lockedVersion` in every row reviewed). "CN-6" marks the six packs edited on this branch.

### 3a. Shared composed references (bound into every route or every route of a language)

| Reference | Version / sha | R1 | R2 | R3 | R4 | R5 | R6 | R7 | R8 | R9 | R10 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| postriff-content-craft (SKILL + 5 refs) | 1.2.0 / 61664bec94c6 | PASS | PASS | CONCERN | N/A | N/A | PASS | PASS | PASS | PASS | PASS |
| postriff-adapter-contract | 1.0.0 / b4d2b01e5d2c | N/A | PASS | N/A | N/A | N/A | PASS | PASS | PASS | PASS | PASS |
| postriff-content-engine SKILL + localization + platform-and-templates | 1.1.0 / bef9fe313584 | PASS | PASS | PASS | CONCERN | N/A | PASS | PASS | PASS | CONCERN | PASS |
| engine locale `zh-Hans-CN.md` | (engine 1.1.0) | CONCERN | N/A | PASS | PASS | CONCERN | CONCERN | CONCERN | FAIL | CONCERN | N/A |
| engine locales `_family-zh`, `zh-Hant-TW`, `zh-Hant-HK`, `yue-Hant-HK`, `zh-Hans-SG` | (engine 1.1.0) | PASS | N/A | PASS | PASS | N/A | PASS | CONCERN | PASS | PASS | N/A |
| postriff-research-and-source-log (cited turns) | registry not inspected | N/A | N/A | N/A | N/A | N/A | PASS | PASS | PASS | PASS | N/A |

### 3b. Channel packs (composed route = shared rows above + this adapter)

| Pack | Version / sha | R1 | R2 | R3 | R4 | R5 | R6 | R7 | R8 | R9 | R10 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| xiaohongshu (CN-6) | 1.2.0 / 280ce1d0115e | PASS | CONCERN | PASS | PASS | CONCERN | CONCERN | CONCERN | FAIL | CONCERN | PASS |
| douyin (CN-6) | 1.1.0 / 8e7bba89fa4d | PASS | PASS | CONCERN | PASS | CONCERN | PASS | PASS | CONCERN | PASS | PASS |
| bilibili (CN-6) | 1.2.0 / 17516336ea09 | CONCERN | CONCERN | PASS | PASS | CONCERN | PASS | PASS | PASS | PASS | PASS |
| zhihu (CN-6) | 1.1.0 / ec3d5d1a1882 | PASS | PASS | PASS | PASS | CONCERN | PASS | PASS | PASS | PASS | PASS |
| weibo (CN-6) | 1.1.0 / 248871217f83 | PASS | PASS | PASS | PASS | CONCERN | PASS | PASS | PASS | PASS | PASS |
| wechat-channels (CN-6) | 1.1.0 / bbc93a2c74ef | PASS | PASS | PASS | PASS | CONCERN | PASS | PASS | PASS | PASS | PASS |
| linkedin | 1.1.0 / b96a66ed3a87 | CONCERN | PASS | CONCERN | N/A | N/A | PASS | CONCERN | PASS | CONCERN | PASS |
| x | 1.0.1 / f6d4528c36f7 | PASS | FAIL | PASS | N/A | N/A | PASS | PASS | CONCERN | PASS | PASS |
| instagram | 1.0.0 / f3dbecabe43a | PASS | CONCERN | PASS | N/A | N/A | PASS | PASS | PASS | PASS | PASS |
| threads | 1.0.0 / 4f764cf4df1d | PASS | CONCERN | PASS | N/A | N/A | PASS | PASS | PASS | PASS | PASS |
| facebook | 1.0.0 / c941056a4224 | PASS | PASS | PASS | N/A | N/A | PASS | PASS | PASS | PASS | PASS |
| tiktok | 1.0.0 / 4e090b2e2fa8 | PASS | PASS | PASS | N/A | N/A | PASS | PASS | PASS | PASS | PASS |
| youtube | 1.0.0 / c470a0bb8e89 | PASS | PASS | PASS | N/A | N/A | PASS | PASS | PASS | PASS | PASS |
| kuaishou | 1.0.0 / 71c73ecd262f | CONCERN | PASS | PASS | PASS | CONCERN | PASS | PASS | PASS | PASS | PASS |
| tencent-qq | 1.0.0 / 12cfc7a68c73 | CONCERN | PASS | PASS | PASS | CONCERN | PASS | PASS | PASS | PASS | N/A |
| feishu-lark | 1.0.0 / 557d2ddd3f19 | CONCERN | PASS | PASS | CONCERN | CONCERN | PASS | PASS | PASS | PASS | N/A |
| dcard | 1.0.0 / 74d9c1482d7d | CONCERN | PASS | PASS | PASS | N/A | PASS | PASS | PASS | PASS | N/A |
| reddit | 1.0.0 / e250372bc077 | CONCERN | PASS | PASS | N/A | N/A | PASS | PASS | CONCERN | PASS | N/A |
| pinterest | 1.0.0 / 1aa80ea24bf9 | CONCERN | PASS | PASS | N/A | N/A | PASS | PASS | PASS | PASS | PASS |
| bluesky | 1.0.0 / 5c3119dfa19d | CONCERN | PASS | PASS | N/A | N/A | PASS | PASS | PASS | PASS | N/A |
| telegram | 1.0.0 / 2c7539ca2329 | CONCERN | PASS | PASS | N/A | N/A | PASS | PASS | PASS | PASS | N/A |
| mastodon | 1.0.0 / 539d7cdd7d88 | CONCERN | PASS | PASS | N/A | N/A | PASS | PASS | PASS | PASS | N/A |
| snapchat | 1.0.0 / 6f89a11640dd | CONCERN | PASS | PASS | N/A | N/A | PASS | PASS | PASS | PASS | PASS |
| discord | 1.0.0 / e52ac0a08be1 | CONCERN | PASS | PASS | N/A | N/A | PASS | PASS | PASS | PASS | N/A |
| google-business-profile | 1.0.0 / 9b332818d1ec | CONCERN | PASS | PASS | N/A | N/A | PASS | PASS | PASS | PASS | N/A |
| kakaotalk-channel | 1.0.0 / a02ff60e530b | CONCERN | PASS | PASS | N/A | N/A | PASS | PASS | PASS | PASS | N/A |
| line-official-account | 1.0.0 / c921accd7ea6 | CONCERN | PASS | PASS | N/A | N/A | PASS | PASS | PASS | PASS | N/A |
| moj | 1.0.0 / 864823759e37 | CONCERN | PASS | PASS | N/A | N/A | PASS | PASS | PASS | PASS | PASS |
| naver-blog | 1.0.0 / 4060c40667f8 | CONCERN | PASS | PASS | N/A | N/A | PASS | PASS | PASS | PASS | N/A |
| note-jp | 1.0.0 / 86f5d6b06af4 | CONCERN | PASS | PASS | N/A | N/A | PASS | PASS | PASS | PASS | N/A |
| pixelfed | 1.0.0 / cf18512fd779 | CONCERN | PASS | PASS | N/A | N/A | PASS | PASS | PASS | PASS | PASS |
| sharechat | 1.0.0 / d6fea72b73e3 | CONCERN | PASS | PASS | N/A | N/A | PASS | PASS | PASS | PASS | N/A |
| whatsapp-channels | 1.0.0 / 1271ab5a2d96 | CONCERN | PASS | PASS | N/A | N/A | PASS | PASS | PASS | PASS | N/A |

**Cell totals, channel table (33 packs × 10):** FAIL 2 (X R2, Xiaohongshu R8). CONCERN 46. **Shared-reference table (6 rows):** FAIL 1 (`zh-Hans-CN.md` R8). CONCERN 9. Many cells come from the same root cause, so the 2 FAIL findings and 19 CONCERN findings below are counted as distinct findings.

**What the branch changed, confirmed:** the old Xiaohongshu rule "End with one line of three to six topic tags" and its compulsory closing line (`220d2de1`, xiaohongshu SKILL.md:31) are gone. Tags and the closing line are now optional (`postriff-channel-xiaohongshu/SKILL.md:31`, "no fixed number is required"). No channel pack now contains a hashtag quota (R6) or an instruction to invent metrics, testimonials, anecdotes or receipts (R9). A fixed tag-count FAIL that existed before this branch is resolved.

## 4. Findings, ranked by severity

Severity: **FAIL-H** (breaks A17 or a format), **CONCERN-H/M/L**.

### F-1 — FAIL-H — Blanket, unsourced algorithm claim in a composed locale guide (R8; also R9)
- File: `postriff-content-engine/references/locales/zh-Hans-CN.md:28`, bound for every `zh-Hans-CN` destination (all CN-6 routes, plus Kuaishou, QQ and Feishu).
- Evidence: "Xiaohongshu rewards a first-person "I tried it" tone … obvious ads get penalised."
- Why: it states ranking behaviour ("rewards", "penalised") as fact with no date or source. That is the kind of claim A17 forbids, and it contradicts the Xiaohongshu adapter's own disclaimer: "not current ranking rules: nothing here is an algorithm guarantee" (`postriff-channel-xiaohongshu/SKILL.md:35`). Pushing an "I tried it" tone also invites invented first-hand use when the author has supplied none (R9).
- Proposed wording: "- Xiaohongshu readers tend to trust practical, first-hand detail **when the author has supplied it**; never imply use or results the facts do not support. Undisclosed advertising can break platform rules: add a warning for the author. (Editorial observation, not a ranking rule.)"

### F-2 — FAIL-H — X adapter forbids the `x.thread` format it advertises (R2)
- File: `postriff-channel-x/SKILL.md:27` advertises `x.thread` with `sequence`, and `creation_capabilities.py:45` gives it a `segments` slot. But `postriff-channel-x/SKILL.md:31` says: "returns one `x.post` per destination in `text`: a single post, not a thread."
- Why: a user who picks the advertised thread format gets instructions to write one post. Either the format is dishonest or the instruction is wrong.
- Proposed wording (choose one): (a) "A writing run returns the selected format. `x.post`: one post within the 280-weighted-character `characterLimit` … `x.thread`: ordered segments in `segments`, each within the limit and understandable alone; use a thread only when the idea needs sequential beats." or (b) remove the `x.thread` row from the native-format table (and `channel_adapters.py:40`) until thread drafting is supported.

### C-1 — CONCERN-H — Mainland packs say nothing about AI-content or commercial disclosure (R5)
- Files: all CN-6 §5 sections, plus kuaishou, tencent-qq and feishu-lark. Only Zhihu has a disclosure field: "`zhihu.answer` … `promotion_disclosure`" (`postriff-channel-zhihu/SKILL.md:26`).
- Why: the drafts are AI-written. To the reviewer's knowledge (training data, **verify**), Mainland rules on labelling AI-generated synthetic content took effect 2025-09-01. Major platforms offer AI-content and commercial-cooperation declarations, and the Internet Advertising Measures (2023) require paid content to be marked as advertising. None of the packs reminds the author about these declarations at publish time.
- Proposed wording, for each Mainland pack §5: "- If the post is sponsored, gifted or affiliated, or any part was AI-generated or AI-assisted, add a `notes` reminder that the author applies the platform's own declaration (commercial cooperation, AI content) when publishing. Don't put a label in `text` unless the author asks. Check current platform rules before relying on this reminder."

### C-2 — CONCERN-H — X capability claims are undated and contradict each other (R8)
- Evidence: "It publishes to X only through its hosted X connector" (`postriff-channel-x/SKILL.md:31`). Against that: "The free route uses X's own web composer and native scheduler" (`:35`), and the controlled-browser route at `:49-51`. The override also hard-codes UI labels "`Schedule post` … `Confirm`, the final `Schedule` control" (`:39`) with no observation date, and it overrides the contract's "contains no qualified browser selectors or final-submit action" (`postriff-adapter-contract/SKILL.md:26`).
- Also: to the reviewer's knowledge (**verify**), X's automation rules prohibit non-API automation such as scripting the X website. Product and policy review should check this route against X's current terms.
- Proposed wording: §4 → "PostRiff publishes to X only through a route this workspace has connected and qualified: the hosted X connector or the companion's controlled browser. A draft is never a publishing promise." Add to §7: "UI labels observed on <date>; re-verify before each live use."

### C-3 — CONCERN-M — The composed locale guide prescribes a fixed Xiaohongshu/Douyin template (R6, R1)
- File: `postriff-content-engine/references/locales/zh-Hans-CN.md:10`. Evidence: "Xiaohongshu gets an emoji-rich title (often 【】), short paragraphs, emoji bullets, #tags at the end"; "Douyin a short caption plus #tags."
- Why: this rides into the same prompt as Xiaohongshu adapter 1.2.0, which made tags optional, and the human-voice pass, which removes "emoji labels or forced hashtags" (`postriff-content-craft/references/human-voice-pass.md:33`). The writer gets contradictory instructions, and the locale text reads as a default template.
- Proposed wording: "- Platform conventions vary; the channel adapter decides. Common, optional patterns: Xiaohongshu titles sometimes use 【】 or an emoji; Weibo topics are written #话题#; Douyin captions are short. Tags and emoji only when the author uses them or they help readers find the post."

### C-4 — CONCERN-M — Stock engagement CTAs listed as the convention (R7)
- File: `zh-Hans-CN.md:31`. Evidence: "Calls to action: 点赞收藏, 评论区聊聊."
- Why: it reads as the expected close, and it conflicts with "a complete observation may end with no CTA" (`postriff-content-craft/references/editorial-workflow.md:45-46`).
- Proposed wording: "- A call to action is optional. When the author wants one, a plain specific ask fits better than a stock 点赞收藏 / 评论区聊聊."

### C-5 — CONCERN-M — Undated enforcement claims about off-platform links (R8)
- Evidence: "Xiaohongshu hides notes that send readers away" (`postriff-channel-xiaohongshu/SKILL.md:31`) and "Xiaohongshu penalises moving users off-platform" (`zh-Hans-CN.md:50`).
- Why: the advice (keep contact details out) is reasonable and consistent with community rules. The mechanism ("hides", "penalises") is stated as fact without a source or date.
- Proposed wording: "Keep WeChat IDs, phone numbers, links and other off-platform contact out of the text; Xiaohongshu's community rules restrict diverting readers off-platform (check the current rules). Add a warning when the author supplies them."

### C-6 — CONCERN-M — Xiaohongshu requires first person (R9)
- Evidence: "first person, practical, warm and specific" (`postriff-channel-xiaohongshu/SKILL.md:31`).
- Why: a brand, institution or neutral-summary workspace (`postriff-content-engine/SKILL.md:109-114`) may have no first-person experience to draw on. Together with F-1, a required first-person voice pushes the writer toward invented first-hand experience. The pack's later "Do not invent personal experience" lessens the risk but doesn't remove the conflict.
- Proposed wording: "first person when the author supplies first-hand experience; otherwise the workspace's own voice. Practical, warm and specific."

### C-7 — CONCERN-M — LinkedIn: rigid structure and a required closing question/takeaway (R1, R3, R7, R9)
- Evidence: "Give the idea more room than it gets on X or Threads" and "close with one specific question or takeaway for peers" (`postriff-channel-linkedin/SKILL.md:31`).
- Why: this conflicts with the composed core's "use the space the thought needs" and "No compulsory confession, numbers, … closing question or P.S." (`postriff-content-craft/references/platform-playbooks.md:13-15`). The required "longer reflection on what the person learned" asks for content the author may not have supplied.
- Proposed wording: "Open with the point in one or two lines. Add the professional context the facts support (situation, stakes, what changed and for whom) and any reflection the person supplied. Length follows the thought. End on a specific takeaway, a real question, or simply the last useful sentence."

### C-8 — CONCERN-M — Xiaohongshu `video` format and `originality` field have no guidance (R2)
- Evidence: the table advertises "`xiaohongshu.video` | video | `title`, `originality`" (`postriff-channel-xiaohongshu/SKILL.md:27`), but §4–§5 cover only image notes ("Image notes carry the sequence", `:39`). Nothing explains `originality`.
- Risk: the writer may assert an originality declaration it can't verify, or treat a video caption as an image note.
- Proposed wording, §5: "- A video note is a script and caption for a real video: give the spoken script, on-screen text and cover text as separate fields. The video itself is a media need. `originality` is the author's own declaration: leave it unresolved and never assert it."

### C-9 — CONCERN-M — Bilibili: a required chaptered script; missing native upload fields (R1, R2, R5)
- Evidence: "Write a chaptered spoken script" (`postriff-channel-bilibili/SKILL.md:37`).
- Why: vlogs, performances and short hobby clips don't fit an explainer structure. To the reviewer's knowledge (**verify**), a Bilibili upload also asks for an original/repost type (自制/转载, with a source for 转载) and tags. Neither appears in the native fields (`:26`).
- Proposed wording: "- For an explainer, a chaptered script works well: … For a performance, vlog or short clip, follow the video's own shape." Consider adding a `source_type` binding field (left unresolved, never guessed).

### C-10 — CONCERN-M — 20 packs have only boilerplate writing rules (R1); three of them are Mainland platforms (R5)
- Packs: kuaishou, tencent-qq, feishu-lark, dcard, reddit, pinterest, bluesky, telegram, mastodon, snapchat, discord, google-business-profile, kakaotalk-channel, line-official-account, moj, naver-blog, note-jp, pixelfed, sharechat, whatsapp-channels.
- Evidence: each §4 repeats the generic rule plus its §1 purpose line. Bluesky's is purely technical: "AT Protocol identity and rich-text facets; verify AT URI and CID separately" (`postriff-channel-bluesky/SKILL.md:14`). The core playbooks cover only seven platforms: "Shared voice review applies to all seven" (`postriff-content-craft/references/platform-playbooks.md:4`).
- Why: nothing in these routes is unsafe (R6–R9 pass because the core forbids bait, quotas and invention). But the writer gets almost no platform-native guidance. Kuaishou, Tencent QQ and Feishu are Mainland platforms that missed the §5 treatment the CN-6 got on this branch.
- Proposed fix: add a dated "§5 Native reasoning" section to each, in the CN-6 pattern, starting with the three Mainland packs and Reddit (community-rule and self-promotion norms).

### C-11 — CONCERN-L — Threads `reply` and Instagram `story` formats have no guidance (R2)
- Evidence: "`threads.reply` | optional | `parent_ref`" (`postriff-channel-threads/SKILL.md:27`); "`instagram.story` | image" (`postriff-channel-instagram/SKILL.md:28`). The playbooks cover posts, carousels and video only (`platform-playbooks.md:35-46, 68-78`).
- Proposed wording: Threads: "A reply answers the parent post's actual point, in one or two sentences; it never promotes off-topic and is drafted only on request." Instagram: "A Story is a short sequence of frames: one line of on-image text per frame, with the frame media as a need; a Story isn't a feed caption."

### C-12 — CONCERN-L — Reddit description claims a publishing route (R8)
- Evidence: "approval-gated controlled-browser publishing route" (`postriff-channel-reddit/SKILL.md:3`); the readiness signals are at `:36`.
- Why: the claim enters a writing prompt with no date and no qualification status. Writing runs are draft-only.
- Proposed wording: "Prepare and validate Reddit drafts. A controlled-browser route exists only where this workspace has qualified it; drafting never implies it."

### C-13 — CONCERN-L — Douyin purpose: "rapid hook", "account-verified short video" (R3, R8)
- Evidence: "Chinese on-screen captions, rapid hook and account-verified short video" (`postriff-channel-douyin/SKILL.md:14`, repeated in §4 at `:30`).
- Why: "rapid hook" leans against "without requiring frantic pacing" (`platform-playbooks.md:86`). "account-verified" sounds like a capability or verification state that the writing route doesn't have. Repeating the purpose line in §4 adds no rule.
- Proposed wording: "Spoken short video with on-screen text; an opening that says early what the viewer gets." Delete the repeated purpose sentence from §4.

### C-14 — CONCERN-L — Engine says "Use Simplified Chinese" for every Mainland platform (R4)
- Evidence: "Mainland Chinese platforms | Use Simplified Chinese and platform-native structure" (`postriff-content-engine/references/platform-and-templates.md:22`).
- Why: it can override a `zh-Hant-TW`/`zh-Hant-HK` destination on Weibo or Xiaohongshu, which the CN packs handle correctly ("zh-Hant-TW and zh-Hant-HK readers need their own wording", `postriff-channel-xiaohongshu/SKILL.md:40`).
- Proposed wording: "Write in the destination's language tag (Simplified for Mainland audiences by default) with platform-native structure."

### C-15 — CONCERN-L — Feishu/Lark planning language ignores region (R4)
- Evidence: "Planning language: `zh-Hans`" (`postriff-channel-feishu-lark/SKILL.md:18`), although the pack separates `feishu_cn` and `lark_global` (`:14`).
- Proposed wording: "Planning language: `zh-Hans` for `feishu_cn`; for `lark_global`, the tenant's language. Workplace register, not social-feed tone."

### C-16 — CONCERN-L — Engine voice defaults lean toward lived experience (R9)
- Evidence: "after actually living through the problem" (`postriff-content-engine/SKILL.md:131-132`); "first-person and concrete" (`:139`); "Use "I" freely" (`:152`).
- Why: strong guards exist ("Never invent a personal anecdote", `:233-234`), but the defaults pull against neutral, brand and Zhihu-style answers.
- Proposed wording: "Use "I" freely in a personal workspace when the supplied context supports the claim."

### C-17 — CONCERN-L — Core playbooks carry examples specific to one creator (R3)
- Evidence: "A real rehearsal photo can carry atmosphere" (`platform-playbooks.md:44`); "listeners, students, local community" (`:99`).
- Why: product skills should carry the method, not one person. Generic examples suit every workspace.
- Proposed wording: "A real behind-the-scenes photo can carry atmosphere"; "the actual audience: customers, students, local community, friends or product users."

### C-18 — CONCERN-L — HK/Cantonese locale guides describe CTA and hashtag templates as "typical" (R7)
- Evidence: "closes with a Cantonese call to action (想嚟嘅快啲留位啦" (`locales/yue-Hant-HK.md:27`); "call to action (詳情請瀏覽). Hashtags at the end" (`locales/zh-Hant-HK.md:32`).
- Why: these describe conventions rather than mandate them, but "快啲留位" can read as urgency. These guides ride with any HK destination, Weibo and Xiaohongshu included.
- Proposed wording: prefix with "When the author wants a call to action, a typical one is …" and "hashtags, if used, go at the end".

### C-19 — CONCERN-L — Xiaohongshu limits stated as fact next to a "limits unverified" disclaimer (R8, consistency)
- Evidence: "at most 20 characters" and "within the `characterLimit` (1,000)" (`postriff-channel-xiaohongshu/SKILL.md:31`) vs "any platform limit stays unverified" (`:35`). The limits do match the versioned record `wave4c-draft-2026-09-28` in `src/postriff_phase2/contracts.py:17`.
- Proposed wording, §5: "…any limit not in the run's versioned `characterLimit` record stays unverified."

### Positive observations (no action)
- `algorithm-practice.md` dates its review ("Reviewed 2026-09-13", `:4`), tiers its evidence, and says its applications are "our editorial inferences, not platform-authored instructions" (`:35`). It meets R8's sourcing bar, with the caveat that its URLs were not fetched in this review.
- The script/asset/draft distinction is stated clearly and repeatedly. Examples: "A script/cover brief is not a rendered video" (`platform-playbooks.md:92-93`); "A writing run describes media; it never supplies it" (`postriff-adapter-contract/SKILL.md:18`); "a script never stands in for the video" (`postriff-channel-wechat-channels/SKILL.md:37`).
- Weibo's `#话题#` form (`postriff-channel-weibo/SKILL.md:38`) and the Simplified/Traditional/Cantonese separation in `_family-zh.md`, `zh-Hant-TW.md`, `zh-Hant-HK.md` and `yue-Hant-HK.md` look correct to a machine reviewer, including "never make a Traditional post by converting a Simplified one" (`_family-zh.md:12`).
- Dcard: "no fabricated anonymous story" (`postriff-channel-dcard/SKILL.md:14`). Zhihu's disclosure rule (`postriff-channel-zhihu/SKILL.md:39`). Both are strong R9 guards.

## 5. A17 status recommendation (machine view)

- **"No required hashtag quotas":** met in every channel pack. Residual template pressure comes from `zh-Hans-CN.md:10` (C-3).
- **"No fabricated anecdotes":** no instruction to fabricate. Defaults that push toward invented experience remain (C-6, C-7, C-16, F-1).
- **"No unsupported blanket algorithm claims":** **not met** while `zh-Hans-CN.md:28` stands (F-1). Undated enforcement claims also remain (C-5).
- **"Assesses all composed references":** this review covers the required route (core, contract, 33 adapters) and the engine/locale/research references that are composed with it. Gaps are listed in section 6.

Recommendation: fix F-1 and F-2 (and ideally C-1 to C-5), bump and relock the affected skills, then do the human editorial sign-off below. Until then, A17 should stay **unverified (human editorial)**, as `ACCEPTANCE-EVIDENCE.md:67` already records.

## 5a. Resolutions after this review (commit `cf9d0e0a`)

Text edits were made by the same AI session that commissioned this review; they are fixes to the findings, not a re-review, and they do not change the human sign-off below.

| Finding | Resolution | Version |
| --- | --- | --- |
| F-1 | `zh-Hans-CN.md` no longer states how Xiaohongshu ranks or penalises posts. It now says a first-person, practical tone fits only for what the author actually did, never presents promotion as personal experience, and makes no claim about ranking. | `postriff-content-engine` 1.1.0 → 1.2.0, relocked |
| F-2 | The X adapter now describes `x.thread`: `text` is the first post, `nativeFields.sequence` holds the following posts in order, and threads are drafted for review and export only. | `postriff-channel-x` 1.0.1 → 1.1.0, relocked |
| C-3 | The fixed "emoji-rich title… #tags at the end" template is replaced: the channel adapter decides; emoji, 【】 and topic tags are optional and follow the author's habit, never a fixed template or count. | content-engine 1.2.0 |
| C-4 | Stock CTAs: a call to action is optional, at most one, only when the post invites a real reply; never a stock 点赞收藏 line. | content-engine 1.2.0 |
| C-1, C-2, C-5 … C-19 | Open for the human editor. C-1 (Mainland AI-content and commercial-disclosure reminders) and C-2 (X capability claims) are the highest priority. The coverage gap on whether `visual-handoff.md` is bound for native video/carousel IDs (section 6) is also open. | — |

After these edits, the machine view of "no unsupported blanket algorithm claims" is met for the composed `zh-Hans-CN` route; undated enforcement claims (C-5) remain. A17 stays **partially verified (machine) / unverified (human editorial)**.

## 6. Coverage note

**Read in full (paths under `skills/` unless noted):**
- `rafii-registry.json`: the entries for `postriff-content-craft`, `postriff-adapter-contract`, `postriff-content-engine`, all 33 `postriff-channel-*` and the humanizer packs (version, lockedVersion, sha256)
- `postriff-content-craft/SKILL.md`; `references/editorial-workflow.md`, `human-voice-pass.md`, `platform-playbooks.md`, `algorithm-practice.md`, `visual-handoff.md`
- `postriff-adapter-contract/SKILL.md`
- All 33 channel packs, `postriff-channel-<id>/SKILL.md`: bilibili, bluesky, dcard, discord, douyin, facebook, feishu-lark, google-business-profile, instagram, kakaotalk-channel, kuaishou, line-official-account, linkedin, mastodon, moj, naver-blog, note-jp, pinterest, pixelfed, reddit, sharechat, snapchat, telegram, tencent-qq, threads, tiktok, wechat-channels, weibo, whatsapp-channels, x, xiaohongshu, youtube, zhihu (no channel pack has a `references/` directory)
- `postriff-content-engine/SKILL.md`; `references/localization.md`, `platform-and-templates.md`; `references/locales/_family-zh.md`, `zh-Hans-CN.md`, `zh-Hant-TW.md`, `zh-Hant-HK.md`, `yue-Hant-HK.md`, `zh-Hans-SG.md`
- `postriff-research-and-source-log/SKILL.md`, `references/provenance-ledger.md`
- `rafii-humanizer-zh/references/register.md`
- Code (outside `skills/`): `src/postriff_phase2/skills.py` lines 1–140 and 200–345; `src/postriff_phase2/creation_capabilities.py` lines 1–130 and 155–240; `src/postriff_phase2/contracts.py` `LIMITS`; `src/postriff_phase2/skill_compiler.py` `writer_extras`; `src/james_au_social/channel_adapters.py` lines 37–40 (grep)
- `git diff 220d2de1 5899fa86 -- skills/` (all six CN pack diffs and the registry stat)

**Keyword-scanned only, not read line by line** (scanned for hashtag, algorithm, CTA, urgency, testimonial and fabrication terms; nothing found beyond the findings above): `postriff-content-engine/references/content-pillars-and-workflows.md`, `research-and-sensitivity.md`; `rafii-humanizer-zh/SKILL.md`, `references/patterns.md`; `rafii-humanizer-en/SKILL.md`, `references/patterns.md`, `references/meaning-check.md`.

**Not reviewed (composed in some routes):**
- The other ~45 locale guides under `postriff-content-engine/references/locales/` (for example `ja-JP`, `ko-KR`, `hi-IN`, `en-*`). They are bound for the Japanese, Korean, Indian and English packs, so R6–R9 are **unassessed** for those language routes.
- `rafii-*` workflow skills that `writer_extras` adds when a coworker workflow is active (for example `rafii-trend-intelligence`, `rafii-source-to-campaign`, `rafii-weekly-operator`, `rafii-engagement-triage`, `rafii-listening-opportunity`).
- Whether `visual-handoff.md` is actually bound when a native video or carousel format is selected. `VISUAL_FORMATS` (`skills.py:25`) lists generic names such as `short_video`, while native IDs look like `xiaohongshu.video`. I did not trace which value reaches `bind()`.
- External sources cited in `algorithm-practice.md:73-80`. No network access was used.
- Not composed into writing runs, so out of scope: `postriff-content-craft/references/source-review.md`, `source-lock.json`, `LICENSE`; `postriff-content-engine/references/operations.md` (documented as never bound).

## 7. Human editorial sign-off

**PENDING.** No human has reviewed these packs for A17. This document is machine-assisted input to that review, not a substitute for it.

| Field | Value |
| --- | --- |
| Reviewer name | PENDING |
| Reviewer role / languages (e.g. zh-Hans-CN, zh-Hant-TW/HK, yue) | PENDING |
| Date | PENDING |
| Commit / registry release reviewed | PENDING |
| Findings accepted / rejected / deferred (by ID) | PENDING |
| Decision (approve / approve with changes / reject) | PENDING |
| Signature or recorded approval reference | PENDING |
