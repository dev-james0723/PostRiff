# Worldwide post languages: Stage 1 proposal

Status: **proposal** · 2026-09-16 · decisions 1, 4, 6, 8 and 9 made; 2, 3, 5, 7 and 10 still open (§10)

Companion material:
- Research: [`postriff-language-registers.md`](postriff-language-registers.md). Regional style guides for 55 locales, with sources, confidence levels and native-check lists.
- Picker mockup (artifact): https://claude.ai/artifact/AFGBjnnej7h1uCy5ATbJ1Z

PostRiff writes posts that should read as if the person wrote them. Today the composer offers
`English` or `繁體中文` for the whole message. The drafting prompt calls 繁體中文 the
"Hong Kong / Taiwan register" (`src/postriff_phase2/model_runtime.py:37`), which merges two
different written varieties into one.

This proposal:
- replaces those two strings with regional locale tags;
- gives **every channel its own language**;
- adds a searchable picker;
- loads a researched style guide per locale into the drafting prompt.

Nothing here has been built. Stage 2 starts after the decisions in §10.

---

## 1. What changes for the person using PostRiff

1. **Every selected channel shows its icon, its name, and its language with a flag.** Example:
   `[in] LinkedIn · 🇬🇧 English (UK)`, `[小红书] Xiaohongshu · 🇨🇳 简体中文（中国）`,
   `[IG] Instagram · 🇭🇰 繁體中文（香港）`, `[@] Threads · 🇺🇸 English (US)`. One brief becomes four
   posts, each written natively in its channel's language.
   - A **+** on each chip adds another language to the same channel. For example, Instagram in
     both 🇭🇰 繁體中文（香港） and 🇬🇧 English (UK) makes two Instagram drafts.
2. **Clicking a channel's language opens a list with search on top.**
   - Search matches native names, English names, regions, scripts (繁 / 简 / Traditional /
     Simplified) and nicknames (Canto, Singlish, Aussie, Québécois).
   - It ignores accents, letter case, and full-width vs half-width characters.
   - One button copies the choice to every selected channel.
3. **Each channel remembers its last languages.** A channel used for the first time suggests its
   usual language (Xiaohongshu → 简体中文（中国）). Otherwise it falls back to the workspace
   default.
4. **The chosen language decides the post's language.** An English brief can produce a Taiwanese
   Traditional Chinese post.
5. **A language named in the message wins, and the chip shows it.**
   - Named with channels ("Threads in British English, 小紅書用台灣中文"): those channels only.
   - Named without a channel ("write it in Japanese"): every selected channel.
6. **Nothing is blocked.** Each of these produces a draft plus a reminder: an untuned language, a
   language with no region, no past posts in that language, or a local rule such as ad labelling.

## 2. Locale identity

**Stored value: a canonical BCP 47 tag, never a display string.**

| Kind | Examples | Meaning |
|---|---|---|
| Regional | `zh-Hant-HK`, `zh-Hant-TW`, `zh-Hans-CN`, `en-GB`, `pt-BR` | Language, plus script where needed, plus region |
| Separate written variety | `yue-Hant-HK` | Written colloquial Cantonese (口語粵文), distinct from standard written Chinese in Hong Kong |
| Variant | `en-GB-scotland` | Scottish Standard English (IANA-registered variant) |
| Script choice | `hi-Latn-IN` | Romanized Hindi (Hinglish), which outnumbers Devanagari on social media |
| Macro-region | `ar-001`, `es-419` | Modern Standard Arabic for pan-Arab readers; Latin American Spanish |
| Language only | `en`, `zh-Hant`, `zh-Hans`, `es`, `pt`, `fr`, `de`, `ar` | Valid. Drafts with the family guide and shows a "pick a region" reminder |

Rules, all verified against the IANA registry and Node ICU 78.3 / CLDR 48:

- **Normalise on write** (Python and TypeScript):
  1. Trim.
  2. Map aliases (`zh-HK`→`zh-Hant-HK`, `zh-TW`→`zh-Hant-TW`, `zh-CN`→`zh-Hans-CN`,
     `zh-yue`/`yue`/`yue-HK`→`yue-Hant-HK`, `tl`→`fil`, `iw`→`he`, `arz`→`ar-EG`, `ary`→`ar-MA`,
     `apc`/`ajp`→`ar-LB`).
  3. Run `Intl.getCanonicalLocales`.
  4. Reject `-u-`, `-t-` and `-x-` extensions.
- **Always keep the script subtag for Chinese and Cantonese.** Never store `zh` or `yue` bare.
- **Accept any well-formed tag whose language is in the catalogue.** Unknown regions (`es-CL`)
  fall back through CLDR parent locales: `zh-Hant-MO → zh-Hant-HK → zh-Hant`,
  `es-MX → es-419 → es`.
- **Legacy values are read, never rewritten in hashed data.** `English` → `en`,
  `繁體中文` → `zh-Hant`. The region is not guessed; the person sees a one-time reminder.

## 3. Catalogue

One source of truth: `src/postriff_phase2/locales/catalogue.json`, generated at build time.
- **Names:** CLDR data plus hand-written overrides for about 15 tuned entries.
- **Web copy:** `scripts/sync_locale_catalogue.py` copies it to
  `web/src/lib/locales/catalogue.generated.json`, and a test fails if the two differ.
- **No runtime `Intl.DisplayNames` for tuned entries.** Chrome, Safari and Firefox capitalise
  differently, which breaks server/client rendering in Next.js.

```json
{
  "tag": "yue-Hant-HK",
  "family": "zh",
  "native": "廣東話（香港）",
  "english": "Cantonese (Hong Kong)",
  "promptName": "Written Cantonese as used in Hong Kong (Traditional characters)",
  "aliases": ["cantonese", "canto", "廣東話", "广东话", "粵語", "粤语", "港式", "hk", "香港", "zh-yue"],
  "namedAs": ["cantonese", "廣東話", "粵語", "口語"],
  "tier": "tuned",
  "parent": "zh-Hant-HK",
  "dir": "ltr",
  "countUnit": "characters",
  "glyphs": "hk",
  "gendered": false,
  "guide": "references/locales/yue-Hant-HK.md"
}
```

**Fields:**
- `aliases` feed search.
- `namedAs` are the only words that count as a language named in the message. Region words
  such as "Hong Kong" never do, so "a post about our show in Hong Kong" is not an instruction.
- `countUnit` replaces the `endswith("中文")` test in `learning_extract.py:132`.
- `glyphs` picks the regional CJK font stack; `lang` is still set to the full tag.
- `gendered` says the language's grammar shows the writer's gender (§5.5).

**Display names (decided 2026-09-16).** Script first, then a short place name. Each language is
written in its own script, and no label says "Mainland", "SAR" or "PRC"; those stay search aliases.

| Tag | Name in the language | English |
|---|---|---|
| `zh-Hant-HK` | 繁體中文（香港） | Chinese — Traditional (Hong Kong) |
| `yue-Hant-HK` | 廣東話（香港） | Cantonese (Hong Kong) |
| `zh-Hant-TW` | 繁體中文（台灣） | Chinese — Traditional (Taiwan) |
| `zh-Hans-CN` | 简体中文（中国） | Chinese — Simplified (China) |
| `zh-Hans-SG` | 简体中文（新加坡） | Chinese — Simplified (Singapore) |

**Tiers:**
- **Tuned:** the 55 locales researched in the companion document, with a guide under
  `skills/postriff-content-engine/references/locales/`. The first wave (§10 decision 6) is
  `en-GB`, `zh-Hans-CN`, `zh-Hant-HK`, `en-US`, `yue-Hant-HK`, `zh-Hant-TW`, `zh-Hans-SG`,
  `ja-JP`, `ko-KR`, `es-MX`, `pt-BR` and `fr-FR`.
- **Available:** every other language CLDR can name. Drafts with `_generic.md` plus the family
  guide, and shows "isn't tuned yet".

## 4. Languages per channel

### 4.1 Behaviour
- **Every selected channel chip carries a language button for each of its languages, then a +.**
  The composer-wide `EN / 繁中` control goes away.
- **Default when a channel is turned on:**
  1. The languages last used on that channel in this workspace (one or more).
  2. The channel's usual language, from the "Planning language" in its channel skill, resolved
     to a region:
     - Xiaohongshu, Weibo, Douyin, Bilibili, Zhihu, WeChat Channels, Kuaishou, Tencent QQ,
       Feishu/Lark → `zh-Hans-CN`
     - Dcard → `zh-Hant-TW`
     - note, LINE Official Account → `ja-JP`
     - Naver Blog, KakaoTalk Channel → `ko-KR`
     - Moj, ShareChat → `hi-IN`
  3. The workspace default.
- **Picking from a channel's list stores that channel's languages.**
  - The list is titled "Language for Xiaohongshu" and suggests last-used and usual first.
  - Its footer has "Use 🇨🇳 简体中文（中国） on all 4 channels".
  - When the channel has more than one language, the footer also has "Remove from Instagram".
  - The **+** opens "Add a language for Instagram". Languages already on the channel show a check
    and aren't added twice.
- **A language named in the message:**
  - Paired within a clause with channels ("Threads in British English", "小紅書用台灣中文寫"):
    applies to those channels.
  - Joined languages ("Instagram in Hong Kong Chinese and British English",
    "Instagram 用繁體中文同英文"): that channel gets one draft per language.
  - In a clause with no channel ("write it in Japanese"): applies to every selected channel.
  - A family name ("Chinese", "中文") keeps a channel's pick when that pick is already in the
    family.
  - **Only a pick made in the composer is remembered**, never a message override.
- **A clause that only sets a channel's language does not change which channels are selected**
  (§10 decision 8). A channel named without a language keeps today's rule: named channels win
  over chips.

### 4.2 Drafting a channel that isn't drafted today
Xiaohongshu has a channel skill (`skills/postriff-channel-xiaohongshu`), an intent alias
(`intent.py:33`) and a post-preview template. But the drafting runtime writes only LinkedIn,
Instagram and Threads (`agent_runtime.py:12`). Supporting your four-channel case needs:
- a text limit in `src/postriff_phase2/contracts.py:11-14` (limits are versioned, so the
  version bumps);
- the platform in `supported_platforms()` once destinations become platforms × any locale (§5.2);
- `Xiaohongshu` in `DRAFT_PLATFORMS` (`web/src/features/agent/composer.tsx:18`).

Publishing to Xiaohongshu is a separate track and out of scope here.

### 4.3 Where the per-channel memory lives
`workspace.settings.channelLocales = { "LinkedIn": ["en-GB"], "Instagram": ["zh-Hant-HK", "en-GB"], … }`
stays on the server. A small command writes it when the person picks, adds or removes a
language. It is keyed by platform for now; keying by connected account can come later, for
someone who runs two accounts on one platform.

### 4.4 One channel in several languages (decided 2026-09-16: build it)
A destination is a (platform, locale) pair, so Instagram in 繁體中文（香港） and English (UK)
is two destinations and two drafts. Most of the pipeline already keys on the pair:
- **Already pair-keyed:**
  - apply/refresh (`ideas.py:514`)
  - the duplicate check (`src/postriff_alpha/domain.py:485`)
  - output matching (`model_runtime.py:287-293`, `cli_runtime.py:139-142`)
  - the plan's variant lookup (`plan.ts:33-34`)
  - learning scope (platform + language)
  - plan-card rows, keyed by index (`plan-card.tsx:261, 282`)
- **Changes needed:**
  - `resolve_destinations` expands each channel's languages into pairs and de-duplicates on
    (platform, canonical tag).
  - `parse_request` de-duplicates destinations by platform only (`intent.py:243`); language
    pairing happens after that, so the de-duplication stays.
  - `build_plan` matches a time slot by platform (`intent.py:309`), so both drafts share the
    channel's time. The plan row's time picker can move one of them.
  - Composer state becomes `{platform, languages: LocaleTag[]}[]`. Conversation restore rebuilds
    it from all stored destinations (today it reads only `destinations[0].language`,
    `conversation-view.tsx:126-132`).
  - Scheduling: with the language gate removed (§6), both drafts can be scheduled on the same
    connected account. The schedule dialog labels each by its language badge.
  - The prompt payload may list the same platform twice. Rule 3 already says one variant per
    destination; its example output gains a same-platform pair so models don't merge them.

### 4.5 Channel icons
Each chip, plan row, draft card header and schedule row shows the channel's brand mark to the
left of its name. It uses the existing `ChannelIcon` (`web/src/components/channel-icon.tsx`,
size `xs`), from simple-icons plus the hand-drawn LinkedIn mark.
- The connection dot that sits before the name today (`composer.tsx:108`) becomes a small badge
  on the icon's corner: green ready, amber needs attention, grey not connected.
- **Dark-mode fix:** `ChannelIcon` tints black marks (Threads, X) with `#000000` on a
  `#0000001f` background, which disappears on a dark background. Brands whose colour is black
  use `currentColor` instead.

## 5. Drafting pipeline

### 5.1 Which language each destination gets
`src/postriff_phase2/intent.py`:
- **`parse_request` pairs languages with channels inside a clause,** as it already pairs channels
  with times. It returns `languages: [{tags: [...], said, platforms: [...]}]`. `tags` holds
  joined languages ("… and British English", "同英文"); an empty `platforms` means all channels.
- **`resolve_destinations(parsed, requested, default)`** gives each destination its language in
  this order:
  1. A language paired with that channel in the message.
  2. A clause language with no channel.
  3. The destination's own language in the request (the chip).
  4. `channelLocales` for that platform.
  5. The channel's usual language.
  6. The workspace default.
  7. A suggestion from the text's script, used only when nothing above exists.
- **Today's bug is removed.** Channels named in the message all get the top-level language
  (`intent.py:297`); each channel now keeps its own. The top-level `language` field stays
  accepted for old clients, and new clients stop sending it.
- **`detect_language` stops deciding.** The web stops auto-switching while the person types
  (`web/src/features/agent/home-view.tsx:123-126`).

### 5.2 Validation
Replace the hard-coded lists with `locales.is_valid(tag)`:
- `intent.py:14` `LANGUAGES`, and `src/postriff_alpha/generation.py:5`.
- `agent_runtime.py:12` and `model_runtime.py` `DESTINATIONS` pairs: supported platforms × any
  valid locale.
- `src/postriff_phase3/contracts.py:64, 105-107` and `adapters.py:18` enum: a catalogue check.
- `ideas.py:346-347, 542-543`, plus a check on each destination's language, which isn't
  validated at all today.

### 5.3 Prompt
- **Locale name:** `model_runtime.py:37` `LANGUAGE_NAMES` → `catalogue[tag].promptName`. The
  payload keeps `languageId`.
- **Rule 3** of `SYSTEM_PROMPT` (`model_runtime.py:73`) and `cli_runtime.py:74-75` become:
  "Write each variant natively in its destination's locale (`languageId`, a BCP 47 tag),
  following that locale's guide. The brief's own language never decides a variant's language.
  Write every variant from the brief and facts; never translate one variant from another."
- **Output matching** (`model_runtime.py:287-293`, `cli_runtime.py:139-142`) keys on the
  canonical `languageId` and still accepts the display name.

### 5.4 Locale guides as skill references
- **Binding:** `SkillLibrary._engine_references` (`skills.py:163-175`) adds
  `references/locales/<tag>.md` once per distinct destination locale. Available or language-only
  locales get the family guide plus `_generic.md`.
- **Size:** each guide is at most 3,000 characters. It holds the prompt guide, decisive markers,
  the region word list, formats, local rules, and what never to assume. Full research stays in
  `docs/`. Four channels in four locales add at most 12 KB against the 60 KB skills budget.
- **Recorded:** guides are hashed and recorded on the binding.
- **Drop order:** they drop **last** among optional references, after `localization.md`,
  because they decide whether a post reads as local.
- **`references/localization.md`** keeps the cross-language rules (native, not translated; never
  strengthen a claim). It loses the paragraphs that merged Hong Kong and Taiwan.

### 5.5 Voice across languages
- **Samples:** `writingExample` samples get an optional `language` tag.
- **VOICE.md** splits observations in two:
  - traits that carry across languages: length, structure, humour, emoji habits, sign-offs;
  - traits that apply to one tag only: particles, English mixing, spelling, formality.
- **No samples in a channel's locale:** the draft runs with "No past posts in 简体中文（中国）
  yet. Adding a few makes drafts sound more like you."
- **Gendered grammar.** Hindi, Urdu, Marathi, Polish, Russian, Ukrainian, Arabic and Hebrew
  verbs, Romance-language adjectives, Thai particles, and Japanese and Vietnamese self-reference
  all reveal the writer.
  - The guides tell the model never to assume.
  - An **optional** IDENTITY field, "How you refer to yourself in languages that mark it", stores
    the answer the person gives; §10 decision 10 decides whether to add it. Without it, drafts
    use neutral constructions and add a reminder when a sentence can't avoid it.
- **Names of people and works** an author uses often go in the author's own glossary in memory,
  not in locale guides. The research shows names don't follow script: the Hong Kong Philharmonic
  writes 莫扎特 but 蕭邦.

## 6. Stored data and migration

No table has a language column. Values live in JSONB, and two of those places are hashed:
`payloadDigest` (`src/postriff_phase2/store.py:374`) and `artifact_hash` (`ideas.py:262`, checked
at `:500`).

- **Never rewrite** `variants[].language`, manifests, runs or messages. New writes use tags.
  Every comparison goes through `locales.same(a, b)`, which canonicalises legacy values first:
  `ideas.py:514`, `plan.ts:33-34`, `phase3/contracts.py:197`, `store.py:353, 402`.
- **Learning scope must migrate,** because it is keyed text with a unique index:
  - **Matching.** `learning.py` `applies()` falls back through parents, so a `zh-Hant` scope
    applies to `zh-Hant-HK` and `en` applies to `en-GB`. A `zh` family scope also covers
    `yue-Hant-HK` (§10 decision 5).
  - **Workspace state.** `learning.py` `_migrate` rewrites `scope.language` and `scopeKey`.
  - **Database.** `migrations/postriff/011_locale_tags.sql` rewrites
    `pr_memory_proposals.scope_key` / `pr_memory_versions.scope_key` and
    `body.scope.language`. When two current versions collide, the newer stays current.
  - **Events.** `pr_learning_events.scope` is left alone (180-day TTL) and canonicalised on read
    (`learning_extract.py:59-61`). The "two languages → workspace-wide" promotion
    (`:206-208`) then never counts `繁體中文` and `zh-Hant` as two languages.
  - **Chat instructions.** `learning_chat.py:15` `LANGUAGE_WORDS` → catalogue `namedAs`.
- **Analytics** cohorts (`insights.py:74-91`) compare canonical tags.
- **Channels.** Scheduling requires `variant.language == channel.language` (`store.py:353`,
  re-checked at `:402`), and every OAuth channel is created with `"language": "English"`
  (`oauth.py:146`). A Chinese draft can't be scheduled on a real connected account today.
  **Decided:** language comes out of the scheduling match, in `store.py:353` and the re-check at
  `:402`. The channel remembers its last languages instead (§4.3), and the hard-coded
  `"language": "English"` on new OAuth channels goes away.

## 7. Web

### 7.1 New code
- **`web/src/lib/locales/`:**
  - `catalogue.generated.json`
  - `locale.ts`: types, `canonical`, `same`, `legacy`, `parents`
  - `search.ts`: precomputed search keys; match word starts, then substrings; tag match first,
    then tuned
  - `suggest.ts`: last used, usual for channel, `navigator.languages`, time zone.
    `suggest.ts` computes on the client only and never sends the browser's language list or
    time zone to the server.
- **`web/src/components/application/language-picker/`:**
  - `language-picker.tsx`:
    - a trigger opens a dialog popover with an editable combobox driving a grouped listbox;
    - a polite status announces the result count;
    - below 768 px (`hooks/use-media-query.ts`) the same list opens as a modal `Drawer`;
    - `react-aria-components` is already a dependency and is used in the calendar; Base UI
      `Popover` + cmdk (`components/forms/fields/combobox-field.tsx`) is the fallback;
    - motion comes from `t-dropdown` / `t-panel`.
  - `channel-language-chip.tsx`: the channel toggle plus its language trigger.
  - `language-badge.tsx`: flag emoji, then the native name with `lang`, `dir` and the glyph stack.

### 7.1a Flags (decided 2026-09-16)
A flag emoji sits to the left of every language name: in picker rows, channel chips, plan rows,
badges and reminders. The standards research recommends no flags, because a flag names a country
rather than a language. The product shows them anyway, as the person's clear visual cue, and
handles the gaps this way:
- **Flag source:** the tag's region subtag becomes regional-indicator emoji
  (`zh-Hant-HK` → 🇭🇰, `en-GB` → 🇬🇧).
- **Scotland:** `en-GB-scotland` uses the tag-sequence flag 🏴󠁧󠁢󠁳󠁣󠁴󠁿.
- **No region:** `en`, `zh-Hant` and every untuned base language show 🌐.
- **Macro-regions:** `es-419` → 🌎, `ar-001` → 🌍.
- **Screen readers:** the flag is decorative (`aria-hidden`); the name carries the meaning.
- **Rendering:** Windows has no flag emoji and shows letters (HK) instead. The flag span uses
  `"Apple Color Emoji", "Noto Color Emoji", "Segoe UI Emoji"`, with Noto Color Emoji loaded only
  for the flag code points (`unicode-range: U+1F1E6-1F1FF, U+1F3F4, U+E0061-E007F`).
- **Known limit:** iPhones set to the mainland China region hide 🇹🇼. The name still shows.

### 7.2 Replaced
| Surface | Today | After |
|---|---|---|
| Composer | `composer.tsx:15, 36-40, 90-131`: platform chips + one radiogroup | `destinations: {platform, language}[]`, `ChannelLanguageChip` per channel |
| Home | `home-view.tsx:82-83, 123-131, 170-178`: one language, auto-detect | per-channel map seeded from `channelLocales`; no auto-switch |
| Conversation | `conversation-view.tsx:113, 126-132`: restores `destinations[0].language` only | restores every destination's language |
| Ideas | `ideas-view.tsx:38, 61, 85, 117, 326-333`: second toggle | chips |
| Variant tabs, inspector | `variant-card.tsx:12, 30`, `conversation-view.tsx:386` (`繁中/EN`) | `LanguageBadge` |
| Plan rows | `plan-card.tsx:188, 288` | `LanguageBadge` + per-row picker |
| Pipeline, edit dialog | `pipeline-view.tsx:104`, `edit-draft-dialog.tsx:53` | `LanguageBadge` |
| Schedule dialog, review card | `schedule-dialog.tsx:135, 143`, `queue-view.tsx:121` | `LanguageBadge` |
| Memory scope label | `learning-panel.tsx:16-19` | display name |
| Analytics | `analytics-view.tsx:118` | display name |
| Types | `lib/api/types.ts:61, 102, 223, 234, 346, 381, 557` | `LocaleTag` |

### 7.3 Rendering post text
- **Previews:** `PreviewPost` gains `language`. `PhoneFrame` takes the post's tag for `lang`
  instead of the template's market default. `FONT_BY_LANG` keys by glyph family:
  hk / tw / cn / ja / ko, plus Nastaliq for Urdu.
- **Draft text:** every preview body and draft textarea gets `lang="<tag>"` and `dir="auto"`,
  and textareas also get `unicode-bidi: plaintext`. No `word-break: break-all` or letter-spacing
  on post text; truncate with `Intl.Segmenter`.
- **Android fonts:** stock Android has no Hong Kong Chinese font and no Nastaliq font, so the
  font stack names web fallbacks for those two.

### 7.4 Character counts
Python counts code points and the web counts UTF-16 units, so they disagree on emoji. Platforms
disagree too:
- X weights CJK characters as 2.
- Bluesky counts graphemes and caps bytes.
- LINE and TikTok count UTF-16 units.
- Threads may count UTF-8 bytes. If so, a Chinese post tops out near 166 characters; this needs
  one live API test.

One `measure(platform, text) → {used, limit, unit}` in both languages replaces `len` and
`.length`. Drafting shows the count as a reminder. The existing review-time check
(`store.py:356`) uses the same measure.

### 7.5 Tests
The web has no test runner. Node 25 runs TypeScript directly, so `search.ts`, `locale.ts` and
`suggest.ts` get `node --test` files with no new dependency.

## 8. Reminders, never blocks

| Situation | Reminder | Where |
|---|---|---|
| Language with no region | "LinkedIn: English has no region. Pick one so spelling and wording match your readers." | Composer hint, plan row |
| Available, not tuned | "Instagram: Kiswahili isn't tuned yet. PostRiff still writes it; check the wording before you post." | Composer hint, draft warning |
| No samples in locale | "Xiaohongshu: 简体中文（中国） has no past posts yet. Adding a few makes drafts sound more like you." | Composer hint, plan row |
| Named in message | "Threads: named in your message, so this draft uses English (UK)." | Composer hint, chip marker |
| Legacy 繁體中文 data | "Older drafts are marked 繁體中文 with no region. Pick one so new drafts use the right wording." | One-time banner |
| Wrong script | Simplified characters in a `zh-Hant-*` draft | Draft warning |
| Another region's words | 軟件 in `zh-Hant-TW`; "color" in `en-GB`; a Portugal word in `pt-BR` | Draft warning |
| Local rules | Undisclosed ad in `ja-JP` / `ko-KR`; price without tax in `ja-JP`; 国家级 / 最佳 in `zh-Hans-CN`; WeChat ID in a Xiaohongshu post | Draft warning |
| Over a platform's count | "≈ 34 over the Threads API limit" | Draft warning |

**Sources for the lint rules:**
- **Chinese:** OpenCC's official Python binding (Apache-2.0); its inspect stage flags likely
  mainland terms, with Hong Kong flags kept low-severity because its Hong Kong list is small.
- **English:** VarCon, common levels only. Both -ise and -ize pass for `en-GB`.
- **Portuguese:** LanguageTool's pt-PT / pt-BR lists (CC BY-SA, attributed in a NOTICE file).
- **Spanish and the local rules:** short hand-made lists from the research.

The results add to the variant's existing `warnings` and never fail a run.

## 9. Delivery slices

Each slice ships on its own and keeps every existing workspace working.

1. **Catalogue and canonicalisation.** `locales` module (Python + web), aliases, parents, legacy
   mapping, sync script, tests. No behaviour change.
2. **Per-destination languages in the backend.**
   - Clause pairing, joined languages and resolution order (§5.1)
   - Several languages per channel (§4.4)
   - Validation (§5.2) and prompt (§5.3)
   - `channelLocales`
   - Learning scope fallback + migration 011 (§6)
   - Removing the scheduling language gate (§6)
3. **Xiaohongshu drafting.** Limit, supported platform, composer platform list (§4.2).
4. **Locale guides, first wave.** Reference files, binding, drop order, `localization.md` rewrite.
5. **Composer chips, picker and badges.**
   - Channel icons (§4.5), the + per channel, and "Remove from …"
   - §7.1–7.3
   - One-time legacy banner
6. **Reminders, counts and lint.** §7.4 and §8.
7. **Remaining guides,** in batches after native review.

**Acceptance (Stage 3):**
- Your four-channel case, run through a real route and saved to `docs/` for review: LinkedIn
  `en-GB`, Xiaohongshu `zh-Hans-CN`, Instagram `zh-Hant-HK`, Threads `en-US`. Then the same case
  with Instagram also in `en-GB`, giving five drafts. Both Instagram drafts must schedule.
- The six-locale Chopin brief, also saved to `docs/`: `zh-Hant-HK`, `yue-Hant-HK`, `zh-Hant-TW`,
  `zh-Hans-CN`, `en-US`, `en-GB`.
- Search: `canto`, `廣東`, `hk`, `繁`, `brasil`, `scot`, `espanol`.
- Languages named in the message, both per channel and for all channels, and the "Japanese food"
  case that must not trigger.
- Legacy workspaces load, display and regenerate.
- Keyboard; VoiceOver on macOS and iOS; 375 px; light and dark.

**Coordination.** Other sessions have uncommitted changes in most files that slices 2 and 5
touch: `intent.py`, `model_runtime.py`, `cli_runtime.py`, `ideas.py`, `memory.py`, `learning.py`,
`lib/api/types.ts` and `queue-view.tsx`. Stage 2 starts after those land, stages only its own
paths, and never commits the whole tree.

## 10. Decisions

**Made 2026-09-16**

1. **Channel language gate:** removed. Channels remember their last languages (§4.3, §6).
4. **Chinese display names:** script first, short place name, no "Mainland": 繁體中文（香港）,
   廣東話（香港）, 繁體中文（台灣）, 简体中文（中国）, 简体中文（新加坡）. Each is written in its own
   script (§3).
6. **First wave of tuned guides:** `en-GB`, `zh-Hans-CN`, `zh-Hant-HK`, `en-US`, `yue-Hant-HK`,
   `zh-Hant-TW`, `zh-Hans-SG`, `ja-JP`, `ko-KR`, `es-MX`, `pt-BR`, `fr-FR`.
8. **A language named for one channel in the message** sets only that channel's language; the
   other selected channels stay.
9. **One channel in several languages:** in scope now (§4.4).
- **Also decided:** a flag emoji beside every language (§7.1a) and a channel icon beside every
  channel name (§4.5).

**Still open**

2. **Where defaults live.**
   - *Recommended:* the workspace default and `channelLocales`, both on the server.
   - *Alternative:* per browser.
3. **Script entries.**
   - *Recommended, per the research:* `hi-Latn-IN` (Hinglish) as its own entry, with Roman Urdu
     as a later candidate. Arabizi is **not** an entry; add an optional "Latin letters" setting on
     `ar-LB`, `ar-EG` and `ar-MA` later.
5. **Do Chinese-wide learned rules cover Cantonese?**
   - *Recommended:* yes. "No hashtags on my Chinese posts" applies to `yue-Hant-HK` too.
7. **When a guide earns "Tuned".**
   - *Recommended:* a guide loads as soon as it's written, but the badge appears only after a
     native speaker clears its "Native check" list.
10. **Gendered self-reference.**
    - *Recommended:* an optional IDENTITY field, answered by the person and never inferred.
    - *Alternative:* neutral constructions plus reminders only.
