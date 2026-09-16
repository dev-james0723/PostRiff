# Guizang visual reference catalog

## Status and purpose

This is a project-local interoperability catalog for the public
[`op7418/guizang-social-card-skill`](https://github.com/op7418/guizang-social-card-skill)
repository. It lets the conversation director and social-graphics skill expose the
upstream design vocabulary as selectable visual references without copying or
silently installing the upstream skill.

- Reviewed commit: `cf4b810fac1c73fb65a2bb31d8c9278d82cbc4c5`
- Reviewed tree: `37ada2ea99e8370eef709dfb0e222e9db3f95022`
- Review date: `2026-09-12`
- Runtime state: `reference_only`
- Repository license signal: root `LICENSE` and GitHub identify AGPL-3.0.
- Conflicting metadata: `package.json` declares `ISC`.
- Commercial note: the repository separately describes paid terms for deep
  product integration, marketplace listing, revenue sharing, and white-label use.
- Safe default: treat the upstream work as AGPL-3.0 and do not bundle, modify,
  redistribute, white-label, or deploy its code/assets until the intended license
  route is reviewed and recorded.

Reference use means the project may consider the documented visual grammar,
catalog names, content-to-layout routing, and QA concepts. It does not mean that
upstream HTML, CSS, JavaScript, image assets, prompts, or validation scripts are
present locally or licensed for an intended commercial deployment.

Reviewed-file checksums:

| Upstream path | SHA-256 |
|---|---|
| `SKILL.md` | `8311a62184ec81d25d3711cfcf5ec771558d300a3caaf43b464527db1178dd98` |
| `package-lock.json` | `d2a50bb09dd459e876ead7da439a58435cd70c5ffb404af15e4cbb9ad159ae9a` |
| `assets/template-editorial-card.html` | `2d254d9150b58cf4609f19bdec3641b8568685767f88261e4a266905b8a19960` |
| `assets/template-swiss-card.html` | `12ed65272b38c3779e422a56a3cde1fafce013249a6449c3195ac1773f12a7cb` |
| `references/layout-recipes.md` | `8ee0436c901f8c1e3dc5662cbf6dd3e7cb06a49c061c3912891c48981cbc4f6d` |
| `references/theme-presets.md` | `cecf8ae776fb96628cb3ea96ac979a9b97bd4accd647a52aa0fbb9dd12e16430` |
| `validate-social-deck.mjs` | `ddad5dc54e0f16c35fe4bab6e2697db5894ea7064199b52a6b98287dcfde464e` |

## Mandatory consideration, optional application

For every requested visual, `james-au-social-graphics` must load this catalog and
record whether a Guizang option is `eligible`, `not_applicable`, `declined`, or
`unavailable`. The system must not force a graphic when text is stronger, force
Guizang styling onto a conflicting brand identity, or claim that reference-only
rendering used the upstream implementation.

When the choice materially changes the output, show no more than three complete
template combinations plus `No Guizang template / decide for me`. A complete
combination contains:

1. output family and native format;
2. visual system;
3. theme;
4. ordered layout recipe IDs;
5. source-media plan;
6. renderer availability and license state.

For Xiaohongshu and WeChat Official Account cover requests, Guizang combinations
should normally appear among the recommendations. For other platforms, their
composition may be adapted only after rechecking the destination's current format,
safe areas, language density, and brand identity.

## Supported reference outputs

| Reference output | Planning default | Notes |
|---|---:|---|
| Xiaohongshu static card | 1080 x 1440, 3:4 | Cover plus only as many content cards as the argument needs; upstream guidance commonly uses 5–9 total cards. |
| WeChat Official Account main cover | 2100 x 900, 21:9 | Full or near-full title and one visual relationship. This is not WeChat Channels publishing. |
| WeChat Official Account share cover | 1080 x 1080, 1:1 | Shortened title, usually no image or subtitle. Pair with the 21:9 cover. |
| Xiaohongshu Live Photo card | 3:4, upstream guidance up to 5 seconds | User video is preferred; validate current app support and iPhone package path before delivery. |
| WeChat Official Account article Live Photo | 3:4, upstream guidance up to 3 seconds | Draft/export handoff only until current iPhone authoring support is verified. |

All dimensions and duration claims are planning defaults from the reviewed commit,
not permanent platform truth. Current platform checks remain mandatory.

## Visual systems

### Editorial Magazine x E-ink

Use as a slow, considered, tactile editorial stance. Its recognizable ingredients
are restrained paper-and-ink contrast, serif or Songti display type, quiet sans or
serif body treatment, meaningful whitespace, documentary imagery, fine rules,
marginalia, ledgers, pull quotes, and an atmosphere layer beyond a flat fill.

Identity gate:

- display typography is light-to-medium rather than shouty;
- an atmosphere layer is present;
- at least one real editorial structure is present, such as a photo well, pull
  quote, marginalia column, or hierarchical ledger;
- it must not become Swiss-with-a-serif or generic infographic styling.

### Swiss International

Use as an engineered, quantified, decisive stance. Its recognizable ingredients
are strict left-aligned grids, asymmetric whitespace, hairline rules, straight
modules, very light large display type, stronger small labels, proof-oriented
images, and exactly one saturated accent.

Identity gate:

- large display text stays visually light;
- no serif font is used;
- structure comes from grid and hairlines, not rounded cards and shadows;
- exactly one accent is used across the package.

The two systems are visual stances, not topic categories. Choose between them by
editorial intent, and never mix them inside one package unless the user explicitly
requests a reviewed hybrid.

## Theme catalog

| ID | System | Display name | Typical fit |
|---|---|---|---|
| `editorial.ink-classic` | Editorial | Ink Classic | General editorial, business, AI essays, product thinking |
| `editorial.indigo-porcelain` | Editorial | Indigo Porcelain | Technology, research, data, analytical AI topics |
| `editorial.forest-ink` | Editorial | Forest Ink | Nature, sustainability, outdoor and grounded field notes |
| `editorial.kraft-paper` | Editorial | Kraft Paper | Memory, craft, personal essays and warm low-tech subjects |
| `editorial.dune` | Editorial | Dune | Design, objects, portfolio and gallery-like subjects |
| `editorial.midnight-ink` | Editorial | Midnight Ink | The sole dark editorial choice; dark source imagery and cinematic subjects |
| `swiss.ikb` | Swiss | IKB Blue | AI, technology, product, engineering and methods |
| `swiss.lemon-yellow` | Swiss | Lemon Yellow | Young, active, retail, sporty or playful information |
| `swiss.lemon-green` | Swiss | Lemon Green | Ecology, emerging technology, health or highlighter energy |
| `swiss.safety-orange` | Swiss | Safety Orange | Warning, urgency, risk, correction and decision points |

Theme names are selectable references. Exact upstream CSS tokens remain upstream
implementation material and are not copied into this project by this catalog.

## Layout catalog

### Editorial recipes

| ID | Name | Use when |
|---|---|---|
| `M01` | Magazine Issue Cover | A hook needs issue-like hierarchy and one strong visual anchor. |
| `M02` | Field Note Photo | A real photo and compact observation should lead. |
| `M03` | Editorial Essay Split | Image and considered explanation need side-by-side emphasis. |
| `M04` | Pull Quote / Thesis | One verified thesis or quotation deserves the page. |
| `M05` | Checklist / Buying Guide | A compact, useful checklist needs editorial pacing. |
| `M06` | Evidence Wall | Several real artifacts or evidence fragments need one composition. |
| `M07` | Closing Note | The sequence needs a quiet, conclusive landing. |
| `M08` | Tall Ledger | Structured rows should fill a portrait canvas without decorative padding. |
| `M09` | Atmospheric Thesis | A sparse thesis benefits from mood and restrained type. |
| `M10` | Evidence Feature | One primary artifact and its explanation should dominate. |
| `M11` | Marginalia Essay | A main argument benefits from notes, context, or side observations. |
| `M12` | Section Divider | A multi-part sequence needs a real chapter transition. |
| `M13` | Hero Question | One genuine question frames the next section. |
| `M14` | Vertical Pipeline | A process needs a vertically paced editorial explanation. |
| `M15` | Before / After | Real, non-fabricated comparison evidence exists. |
| `M16` | Image-Led Cover | A qualified full-bleed photo has a safe quiet zone for minimal text. |

### Swiss recipes

| ID | Name | Use when |
|---|---|---|
| `S01` | Accent Cover | A concise hook needs strict grid hierarchy and one accent. |
| `S02` | Two Signals / Comparison | Two facts, states, or options need direct comparison. |
| `S03` | Data Layer / File Card | A structured record, specification, or source artifact is central. |
| `S04` | Interface / Browser Mock | A real UI or screenshot needs a legible evidence frame. |
| `S05` | Trap / Warning Rows | Risks, mistakes, or caveats need scannable warning structure. |
| `S06` | Pipeline / Architecture | A real workflow or system relation needs a diagram. |
| `S07` | Takeaway Ledger | Several concise takeaways need ordered ledger rhythm. |
| `S08` | Image Hero | A product render or proof image leads inside a Swiss grid. |
| `S09` | KPI Tower | Verified metrics deserve hierarchical emphasis. |
| `S10` | H-Bar Chart | Comparable measured values support a horizontal bar view. |
| `S11` | Stacked Ledger | Dense categories or steps need a structured vertical stack. |
| `S12` | Matrix + Hero Stat | A real matrix and one verified summary metric work together. |

Recipe IDs never justify invented data, filler cards, fake UI, or fake before/after
evidence. A sequence uses only the recipes needed by the story.

## Source and asset policy

1. Prefer user-provided photos, screenshots, and video when they establish truth.
2. For text-only requests, ask once whether the user wants to supply media, use
   permitted sourced media, use generated conceptual imagery, or proceed without
   an image when the native format allows it.
3. Every sourced asset records URL, creator, license/rights state, retrieval time,
   local asset reference, and permitted destinations.
4. Do not inherit the upstream source-priority list as a rights guarantee.
5. Generated imagery contains image content only; final text and layout remain
   deterministic and reviewable.
6. Text over photography requires a subject map, a quiet zone, deliberate crop,
   phone-size contrast review, and only localized tint when necessary.
7. Screenshots preserve important UI and text, use a suitable fit mode, and never
   become fabricated product evidence.
8. Maps for real routes use a licensed real-map source; schematic maps are labelled
   conceptual and never presented as route proof.

## QA bridge

The local asset receipt must retain the suite's separate mechanical, visual,
factual, localization, accessibility, privacy, and rights results. Where an
approved upstream implementation is later enabled, its validator can provide an
additional mechanical result covering overflow, footer collision, Swiss display
weight, minimum type size, vertical density, display-line caps, default figure
margins, visual bounds, and title gaps. It cannot replace rendered phone-size
inspection or the suite's other gates.

Before final delivery, verify:

- exact dimensions and current platform compatibility;
- no overflow, collision, unreadable type, or unreasoned empty space;
- correct visual-system identity and only one package theme;
- faces, subjects, product objects, UI, and text survive crop;
- visible claims, quotations, metrics, maps, and comparisons are sourced;
- all cards form one coherent but non-repetitive sequence;
- caption/body retains nuance that was intentionally removed from cards;
- source, rights, generated-content, and accessibility metadata are present.

## Upstream reference map

The reviewed upstream system includes `SKILL.md`, two HTML seed templates, one
layout validator, Live Photo helper scripts, and reference files for:

- platform specifications;
- the two style systems;
- theme presets;
- 28 layout recipes;
- typography, spacing, images, screenshots, maps, and metadata components;
- background systems and portrait-fill behavior;
- content planning and title shortening;
- text-on-image subject safety;
- Rednote category routing and capability limits;
- static and Live Photo production;
- QA and delivery.

When exact upstream behavior is required, inspect the pinned source rather than
relying on this summary. A commit change invalidates the review and returns the
provider to `needs_review`.
