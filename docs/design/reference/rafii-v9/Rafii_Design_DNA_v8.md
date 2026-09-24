---
title: Rafii Design DNA — App-wide Design System
version: 1.0.0
reference: Rafii interactive prototype v8
reference_sha256: 7266e550f2ff83deb68d11bcc8cd7f00689da07da8e7c248b026c39d4ee20d20
reference_bytes: 784398
prepared: 2026-09-22
language: English
scope: Visual foundations, interaction principles, reusable components, page templates, and implementation acceptance criteria
status: Design specification derived from the approved prototype; not a claim that other application pages have been implemented
---

# Rafii Design DNA
## A complete design system for extending the v8 language across the application

> **Rafii is a quiet, monochrome creative studio: precise enough to work in, warm enough to think in, and fluid enough that every change feels connected.**

The approved v8 prototype is the visual reference. This document extracts its repeatable rules and turns them into an application-wide specification. The aim is not to make every page look like the homepage. It is to make every page feel as though it belongs to the same product, with the same materials, hierarchy, typography, controls, behavior, and respect for the user's work.

**The central rule:** preserve **clarity first, editorial character second, dimensional polish third**. A beautiful surface must never make a task harder to find, a state harder to understand, or an action easier to trigger accidentally.

---

## Contents

1. [How to use this specification](#1-how-to-use-this-specification)
2. [The design DNA in one page](#2-the-design-dna-in-one-page)
3. [What v8 actually establishes](#3-what-v8-actually-establishes)
4. [Theme and color architecture](#4-theme-and-color-architecture)
5. [Liquid-glass material system](#5-liquid-glass-material-system)
6. [Typography and editorial expression](#6-typography-and-editorial-expression)
7. [Spacing, shape, density, and grids](#7-spacing-shape-density-and-grids)
8. [Application shell and navigation](#8-application-shell-and-navigation)
9. [Universal page anatomy and action hierarchy](#9-universal-page-anatomy-and-action-hierarchy)
10. [Buttons and controls](#10-buttons-and-controls)
11. [Forms, selectors, and staged settings](#11-forms-selectors-and-staged-settings)
12. [Dialogs, filters, tooltips, and overlays](#12-dialogs-filters-tooltips-and-overlays)
13. [Collections: Gallery, List, and Pairings](#13-collections-gallery-list-and-pairings)
14. [Illustration and icon system](#14-illustration-and-icon-system)
15. [Composer and AI controls](#15-composer-and-ai-controls)
16. [Language and localization](#16-language-and-localization)
17. [Native social-app previews](#17-native-social-app-previews)
18. [Motion system](#18-motion-system)
19. [Responsive and touch behavior](#19-responsive-and-touch-behavior)
20. [System states and data truthfulness](#20-system-states-and-data-truthfulness)
21. [Page-by-page application recipes](#21-page-by-page-application-recipes)
22. [Copy, tone, and information design](#22-copy-tone-and-information-design)
23. [Accessibility and reduced effects](#23-accessibility-and-reduced-effects)
24. [Reusable implementation architecture](#24-reusable-implementation-architecture)
25. [Copy-ready token and component foundation](#25-copy-ready-token-and-component-foundation)
26. [Migration and rollout](#26-migration-and-rollout)
27. [Design QA and acceptance criteria](#27-design-qa-and-acceptance-criteria)
28. [Anti-patterns and corrections](#28-anti-patterns-and-corrections)
29. [Agent implementation brief](#29-agent-implementation-brief)
30. [Reference measurements and sources](#30-reference-measurements-and-sources)

---

## 1. How to use this specification

### 1.1 Evidence labels

The guide deliberately separates extraction from extrapolation:

- **Observed:** present in the inspected v8 HTML, source, or computed browser styles.
- **Standardized:** a reusable rule adopted here to consolidate v8's component-specific values and make the system maintainable.
- **Extension:** a proposed application of that language to a page or state not fully implemented in v8.

An extension is not an assertion that a feature, page, route, provider, capability, or backend already exists. Inspect the actual application before implementing it.

The page recipes in Section 21 are **extensions**, except where they explicitly refer to an existing prototype component. They specify the design outcome, not a new mandatory sitemap.

### 1.2 Priority order

When implementation details conflict, use this order:

1. Preserve user data, permissions, accessibility, and correct task behavior.
2. Preserve the product's approved scope and existing working workflows.
3. Follow the design invariants in this document.
4. Use shared components and semantic tokens.
5. Use v8 measurements for close visual matching where appropriate.
6. Use page-specific judgment only where no shared rule applies.

Do not reproduce a prototype limitation solely because it is visible in v8. For example, v8 contains very small auxiliary labels, demo-only states, and inherited component overrides. Those are not instructions to reduce readability, fabricate production state, or stack eight global stylesheets in the real application.

### 1.3 Two implementation modes

**Reference matching:** reproduce the approved v8 component at a specified viewport. Use its exact resolved measurements and compare screenshots.

**App-wide application:** reuse the material, hierarchy, proportions, interaction contracts, and standardized tokens. Adapt layout to the task. A settings form, calendar, and inbox should not all inherit the homepage's large greeting or dual-column preview composition.

### 1.4 Source-of-truth boundary

This guide was produced from the actual library files `rafii-prototype-v8.html` and `rafii-prototype-v8-source.zip`. The standalone HTML and the archive's `index.html` are byte-identical, with the SHA-256 listed in the front matter.

The HTML was rendered at **1440 × 1000** and **390 × 844**, in both dark and light appearances, to inspect the resolved CSS cascade and capture reference images. This is a fresh design extraction, not a re-run of every inherited test or a physical iPhone/Safari certification. The complete production repository and its current route map were not audited for this document. [^v8-reference]

---

## 2. The design DNA in one page

### 2.1 Identity

| Dimension | Rafii expression | Avoid |
|---|---|---|
| Personality | Thoughtful creative coworker; composed, helpful, capable | Hype, relentless enthusiasm, robotic administrative language |
| Palette | Black, white, charcoal, warm-neutral paper, restrained gray | Purple AI glow, neon gradients, rainbow category chrome |
| Material | Borderless translucent surfaces with soft reflection | Hard outlined boxes everywhere; opaque slabs stacked without hierarchy |
| Typography | Clear sans-serif interface with a selective serif-italic accent | Entire interfaces in display serif; novelty fonts on controls |
| Geometry | Rounded rectangles, small capsules, generous internal spacing | A pill around every label; inconsistent corner shapes |
| Layout | Clear task hierarchy and progressive disclosure | Several equally dominant toolbars; duplicate controls |
| Motion | Continuity, soft acceleration, persistent selected-state lenses | Flash cuts, bouncy attention seeking, endless unrelated motion |
| Imagery | Original semantic SVGs and honest destination previews | Generic placeholders, unrelated stock photos, invented provider branding |
| AI behavior | Suggestions and drafts under user control | Unexplained autonomous publishing or false success claims |
| Information density | Calm, organized, adjustable to task | Tiny text used to hide an overcrowded layout |

### 2.2 Ten non-negotiable rules

1. **Rafii chrome stays monochrome.** Real content, flags, and faithful native-platform previews may retain their own colors.
2. **Resting surfaces are borderless, not boundary-less.** Use fill, spacing, reflection, and depth to distinguish them; keep visible focus outlines.
3. **One task should have one dominant commitment action in its active surface.** Secondary navigation and exploration must not compete with it.
4. **Separate what, where, how, and how to browse.** An editorial type, a native format, a channel, and a Gallery/List toggle are different decisions.
5. **Keep advanced controls discoverable but out of the default reading path.** A labelled Filters surface is better than permanently scattered selects.
6. **Preserve selection and work through view changes.** Switching views or preview platforms must not silently reset content.
7. **Animate the actual state change.** A smooth incoming-only animation is not a crossfade; preserve the outgoing layer when continuity matters.
8. **Show honest content.** Never use a decorative animation as evidence of a completed job, connected account, accepted permission, or published post.
9. **Design both themes and mobile at the same time.** Light mode is not a screenshot inversion; mobile is not a scaled desktop.
10. **Reuse components, not just colors.** A shared system includes behavior, accessibility, state, sizing, and content rules.

### 2.3 The signature composition

A typical Rafii screen should read in this order:

**A clear purpose → a focused work surface → contextual choices → a trustworthy preview or result → an explicit next action.**

The expressive moment belongs near the purpose or creative artifact. The working controls stay precise and economical.

---

## 3. What v8 actually establishes

### 3.1 The four-layer hierarchy

V8's library stylesheet explicitly separates **WHAT, FIND, VIEW, and COMMIT**. This is the most important reusable improvement, not merely a smaller header. [^v8-library]

| Layer | Question answered | V8 example | App-wide equivalent |
|---|---|---|---|
| What | Which collection or task am I in? | Editorial type / Native format | Inbox folder, Queue state, Settings section |
| Find | How do I locate or narrow items? | Search plus a labelled Filters trigger | Search messages, filter scheduled posts |
| View | How should the same items be presented? | Gallery / List / Pairings | Calendar / agenda, grid / list |
| Commit | What happens when I accept the choice? | Selected-pair summary + Use these choices | Save changes, schedule, approve |

Do not style the View layer as more important than the task itself. Do not hide commitment inside an icon-only overflow menu.

### 3.2 Exact v8 library arrangement

**Desktop, wider than 800 CSS pixels:** search occupies the flexible side of the workbar; Gallery/List/Pairings and Filters occupy the other side. Category, suggested app fit, artwork pause/play, and research access sit inside the temporary Filters surface.

**At 800 CSS pixels and below:** the workbar becomes one column. Search gets its own row; the three view controls and Filters align beneath it.

**At 600 CSS pixels and below:** the library uses a near-full-height mobile dialog, compact dimension tabs, hidden secondary tab eyebrows, a scrollable collection, and a two-part summary above one full-width confirmation button.

The actual v8 uses a **temporary filter popover layer**, not the inline category row or floating unlabelled play button from earlier designs. Do not reintroduce those earlier layouts based on older screenshots. [^v8-library]

### 3.3 Resolved mobile proportions

At 390 × 844, the inspected default library measured:

| Area | Height |
|---|---:|
| Dialog | 810.23px |
| Header and controls | 253.69px |
| Scrollable collection | 449.55px |
| Summary and confirmation footer | 107px |

The browsing region is roughly **55% of the dialog** in that state. Treat this as a useful reference composition, not a rigid quota under longer translations, accessibility text sizing, errors, or the virtual keyboard. [^measured]

### 3.4 Preserve these established distinctions

- Draft destinations are multi-selected in Channel Bloom.
- Model, Language, and Writing Voice are independent controls.
- Content Library contains 31 editorial types and 20 native formats, with distinct local visual identities.
- App-fit badges describe suggested fit; evidence separates usage from engagement.
- Provider marks identify companies/products; they do not prove live integration.
- Native social previews maintain their own in-app appearance within Rafii's frame.
- The prototype's main navigation includes Create, Calendar, Queue, and Inbox, but navigation presence does not make every page a completed production workflow.

---

## 4. Theme and color architecture

### 4.1 Observed semantic color values

These values are extracted from `src/glass.css`, after the later theme layer overrides the original base stylesheet. [^v8-theme]

| Role | Dark | Light |
|---|---|---|
| Application background | `oklch(0 0 0)` | `oklch(.99 0 0)` |
| Primary foreground | `oklch(1 0 0)` | `oklch(0 0 0)` |
| Declared card token | `oklch(.14 0 0)` | `oklch(1 0 0)` |
| Declared popover token | `oklch(.18 0 0)` | `oklch(.99 0 0)` |
| Primary action foreground/background relationship | White action / black text | Black action / white text |
| Muted interface text | `#a1a1a1` | `#626262` |
| Dim tertiary text | `#848484` | `#777777` |
| Panel RGB channels | `19 19 19` | `245 245 245` |
| Highlight RGB channels | `255 255 255` | `0 0 0` |
| Resting line token | `transparent` | `transparent` |
| Preferred browser control appearance | `color-scheme: dark` | `color-scheme: light` |

The declared card/popover tokens are not a complete description of every rendered surface: the composer, dialogs, library, and controls use layered neutral gradients. Preserve the material recipes as well as the base colors.

### 4.2 Alias cleanup

V8 still contains historical names such as `--lavender`, `--cream`, and `--mint`. Their final values are neutral; **they are not permission to bring purple or green back into the product**.

For the app-wide system, migrate toward semantic names:

| Prototype variable | New semantic alias |
|---|---|
| `--background` / `--bg` | `--rafii-bg` |
| `--foreground` / `--ink` | `--rafii-text-primary` |
| `--muted` | `--rafii-text-secondary` |
| `--dim` | `--rafii-text-tertiary` |
| `--primary` | `--rafii-action-bg` |
| `--primary-foreground` | `--rafii-action-fg` |
| `--panel-rgb` | `--rafii-panel-rgb` |
| `--highlight-rgb` | `--rafii-highlight-rgb` |
| `--glass` | `--rafii-surface-glass` |
| `--glass-selected` | `--rafii-surface-selected` |
| `--glass-shadow` | `--rafii-shadow-glass` |
| `--glass-blur` | `--rafii-blur-surface` |

Keep compatibility aliases during migration, then remove obsolete names once all consumers use the semantic system. Do not create a separate palette per page.

### 4.3 Color permissions

**Allowed:** grayscale Rafii UI; authentic uploaded images and video; native app preview colors; language-region flags; approved original brand marks; necessary semantic distinctions with text and icons.

**Not the default:** colored hero gradients, colored navigation pills, pastel dashboards, purple focus rings, colored status chips chosen merely for visual variety.

For future semantic warning/danger tints, require an explicit product-wide token decision. Until then, use icon + clear status text + hierarchy in the monochrome system. Never encode success or failure through an indistinguishable gray dot alone.

### 4.4 Theme behavior

The visible theme switch changes all Rafii-owned surfaces together. It must not alter selected channels, models, language settings, search, filters, draft text, or the current route.

In production, persist the appearance preference intentionally and define how it relates to system preference. V8 demonstrates a theme toggle; persistence across sessions is an **extension**, not inherited behavior.

Do not recolor the inside of an Instagram or LinkedIn mockup merely because Rafii changes appearance. The frame belongs to Rafii; the simulated app page has a different fidelity contract.

---

## 5. Liquid-glass material system

### 5.1 What liquid glass means here

Rafii glass is a controlled combination of translucent fill, a neutral reflection gradient, soft internal light, and selective background blur. It is not literal refraction, constant distortion, or a glossy effect on every pixel.

Use the material to explain layering: a control rises gently from a work surface; a dialog separates from the page; a selected segment catches more light than its neighbors.

**Borderless means no permanent decorative stroke. It does not mean invisible fields, absent focus rings, or no separation between overlapping surfaces.**

### 5.2 Material roles

| Material | Use | Treatment |
|---|---|---|
| Canvas | Page background, large breathing areas | Near-black or near-white; no blur |
| Quiet panel | Lists, settings sections, dense reading areas | Low-contrast fill; little or no reflection |
| Glass work surface | Composer, contextual cards, compact tool groups | Standard glass gradient + soft inset/outset shadow |
| Selected glass | Active tab, chosen tile, current navigation lens | Brighter/lighter-in-dark fill; stronger but restrained reflection |
| Elevated glass | Dialogs and nested filter panels | More opaque fill + blur + separation shadow |
| Paper | Semantic thumbnail artwork | Soft off-white/gray, tangible card geometry; no UI blur needed |
| Native preview | Third-party app content | Preserve destination-specific rules; not Rafii glass |

### 5.3 Observed glass recipes

**Dark resting glass:**

```css
linear-gradient(
  135deg,
  rgb(255 255 255 / .13),
  rgb(255 255 255 / .055) 40%,
  rgb(255 255 255 / .04) 65%,
  rgb(255 255 255 / .08)
)
```

**Dark selected glass:**

```css
linear-gradient(
  140deg,
  rgb(255 255 255 / .23),
  rgb(255 255 255 / .10) 60%,
  rgb(255 255 255 / .17)
)
```

**Light resting glass:** `linear-gradient(135deg, #fff9, #ffffff45 50%, #eeeeee55)`.

**Light selected glass:** `linear-gradient(140deg, #fff, #ddd8)`.

**Observed dark glass shadow:**

```css
0 15px 40px -22px #000c,
inset 0 5px 17px -13px #ffffffa0,
inset 0 -5px 18px -14px #fff4
```

**Observed light glass shadow:** `0 12px 28px -19px #0005, inset 0 9px 22px -19px #fff`.

These recipes are extracted; the reusable naming in Section 25 is standardized. [^v8-theme]

### 5.4 Blur hierarchy

| Existing role | Observed blur |
|---|---:|
| General glass surface | 24px |
| Desktop navigation rail | 28px |
| Mobile navigation | 30px |
| Main dialog | 40px |
| Main dialog backdrop | 12px |
| Library filter layer | 3px |
| Library filter panel | 25px |
| Information tooltip | 22px |

Use these as roles, not an invitation to add multiple nested blur layers. A dense table should usually use quiet opaque-enough rows inside a single elevated panel.

`backdrop-filter` affects the pixels behind the element, so its visual result depends on what is behind the translucent fill. A transparent blur layer without sufficient foreground/background separation is not a readable control. [^mdn-backdrop]

### 5.5 Surface budget

**Standardized:** in a normal page section, limit the composition to a canvas, one work surface, and its controls. Use an additional surface only when it conveys a real subtask or relationship.

Do not wrap a heading, paragraph, metadata row, button row, and every individual value in separate glass cards. Spacing and typography should do most of the organizational work.

Use a stronger surface for the selected state, not a large glow. Small inset reflections should not look like hard white outlines.

### 5.6 Fallbacks

When blur is unavailable or reduced effects are requested, use sufficiently opaque neutral fills. V8 already includes non-blur fallback styles. Extend them to every new glass component, not just the original composer.

A fallback must preserve boundaries, text contrast, controls, and selection states. Removing blur must not remove the interface.

---

## 6. Typography and editorial expression

### 6.1 The two voices

**Interface voice:** a contemporary, neutral sans-serif for navigation, buttons, labels, lists, tables, data, helper text, and most headings.

**Editorial voice:** a serif, often italic, used to emphasize a short phrase or give a creative canvas a more personal tone.

The contrast is the identity. It should feel like a clear working interface with a human editorial accent, not a magazine article wrapped around administrative controls.

### 6.2 Observed font stacks

```css
/* Interface: declared by the resolved v8 root. */
font-family:
  Geist,
  -apple-system,
  BlinkMacSystemFont,
  "Segoe UI",
  Arial,
  sans-serif;

/* Editorial fragments and the original creative input. */
font-family: Georgia, "Times New Roman", serif;
```

The inspected HTML does not bundle a Geist font file or load a font CDN. A declared stack is not proof that Geist rendered on every device. Use the application's existing licensed font assets where available; otherwise preserve the fallback stack and validate the result. Never silently add an external font dependency. [^v8-type]

### 6.3 Observed versus standardized scale

| Role | Observed v8 | App-wide standard |
|---|---|---|
| Creative homepage hero | 49px desktop; 43px at 390px viewport | 40–52px, responsive; only on creation/intro surfaces |
| Library heading | 29px desktop; 25px mobile | 24–32px, according to task density |
| Filter heading | 20px desktop; 19px mobile | 18–22px |
| Original creative idea input | 26px desktop; 25px mobile; serif italic | Optional creative mode; use 16–18px regular for sustained editing |
| Default body | 14px desktop; 13px mobile in v8 | 16px for reading-heavy pages; 14px for compact working UI |
| Input/select text | 16px for library selects and mobile search | 16px for text entry and touch selects |
| Primary label | Often 12–14px | 14px default; do not solve crowding with tiny labels |
| Secondary metadata | Often 10–12px | 12–13px preferred |
| Eyebrow / compact summary | As small as 7–8px | 11–12px preferred when it must be read; smaller only for nonessential accents |

**Do not promote v8's 7px summary labels into a universal production rule.** Preserve the hierarchy by making the control area simpler, not by making essential text microscopic.

### 6.4 Rules for emphasis

- Use serif italic for one meaningful phrase, such as “your next idea,” not every word in the page title.
- Do not italicize button labels, metric values, timestamps, navigation items, or long form descriptions.
- Keep heading weight mostly 400–500; use 600–700 for the wordmark or truly compact emphatic labels.
- Negative tracking belongs to large Latin headings, not small labels or every locale.
- Numbers in tables, counters, times, and state metrics should use tabular numerals where useful.
- Use sentence case for interface labels; reserve small uppercase for a short section eyebrow.

### 6.5 Text layout

**Standardized:** regular body line height around 1.5–1.65; compact labels around 1.3–1.4; large headings around 1.05–1.2. Avoid long paragraph lines wider than approximately 65–75 characters when a reading task is dominant.

Titles and important settings wrap. Do not crop “Traditional Chinese (Hong Kong)” or a selected content type until it becomes ambiguous. Supporting metadata may truncate only when the complete value remains accessible through a clear detail view.

### 6.6 Non-Latin typography

Use appropriate CJK and RTL fallbacks; do not force Latin display styling onto scripts for which it renders poorly. Chinese text should not automatically inherit tight negative letter spacing. A serif-italic accent may become a regular localized emphasis rather than a faux-slanted CJK heading.

Use `lang`, `dir`, and logical layout properties deliberately. The chosen output language is separate from the interface locale; switching one must not silently change the other.

---

## 7. Spacing, shape, density, and grids

### 7.1 Spacing scale

V8 contains component-tuned values such as 13px, 15px, 19px, 26px, and 52px. Keep those in exact-reference components until visual comparison permits consolidation.

For new components, use a **standardized 4px rhythm**:

`4, 8, 12, 16, 20, 24, 32, 40, 48, 64, 80`.

Small optical corrections may use 2px. Control heights of 44px, 46px, and 48px are deliberate interaction sizes, not spacing errors.

| Relationship | Preferred gap |
|---|---:|
| Icon to short label | 6–8px |
| Field label to input | 7–8px |
| Related compact controls | 8–12px |
| Card content group | 12–16px |
| Standard panel padding | 20–24px |
| Large desktop work-surface padding | 24–32px |
| Between sections | 24–40px |
| Between major page regions | 40–64px |

### 7.2 Radius roles

| Role | Reference values | Standardized token |
|---|---|---|
| Micro artwork/badge | 5–8px | 8px |
| Inner selected lens | 10–12px | 10px or container radius minus inset |
| Search / select / standard button | 12–14px | 12px default |
| Segmented group | 12–17px | 16px primary / 12px secondary |
| List tile / medium card | 18–22px | 20px |
| Composer | 30px desktop / 28px mobile | 28–30px creative surface |
| Dialog | 28px library desktop / 24px mobile | 28px / 24px |
| Filter popover | 22px desktop / 20px mobile | 22px / 20px |
| Circle / pill | 50% / 999px | Only for a semantic circular/pill role |

Nested corners should be geometrically related. A 16px segmented group with 4px inset naturally contains a 12px lens. Do not mix a 30px outer shell with sharp 2px interior controls without a reason.

### 7.3 Density modes

**Comfortable:** creation, onboarding, empty states, brand/voice setup, and longer descriptions.

**Standard:** most forms, settings, queue lists, source lists, and article management.

**Compact:** calendar cells, desktop tables, and metadata-rich navigation. Compact mode shortens whitespace and changes information presentation; it does not remove touch alternatives or make essential copy illegible.

Do not globally set every page to the content library's compact typography. A visually restrained product can still have comfortably readable body text.

### 7.4 Alignment rules

Controls that share a row share a visual baseline and height. All inputs in a filter form use the same label gap and field height. Card titles align through consistent internal padding, not arbitrary minimum heights that create clipped descriptions.

Rows with independent actions use a dedicated action slot. Do not nest an information button inside a selection button, and do not let a trailing icon push the text outside the available width.

---

## 8. Application shell and navigation

### 8.1 Observed shell

- Desktop rail: **88px**, fixed, with a compact brand mark and icon-plus-label navigation.
- Desktop topbar: **91px** in the final theme layer.
- Mobile topbar: **84px**.
- Main workspace maximum width: **1192px**.
- Outer desktop shell padding: **52px**, reduced to 32px at the narrower desktop breakpoint.
- Mobile shell padding: **23px**, reduced to 17px on the smallest phones.
- Mobile primary navigation uses a fixed bottom surface with safe-area padding.
- The creative workspace becomes one column at 980px and below. [^v8-shell]

These are extracted reference values. A dense operational page may use more of the available width while retaining the shell padding, rhythm, and navigation treatment.

### 8.2 Standard application shell

Provide shared slots rather than copying a page's DOM:

```text
AppShell
├─ DesktopRail / MobileNavigation
├─ Topbar
│  ├─ Product / workspace identity
│  ├─ Current page context where needed
│  └─ Global utilities
└─ PageContent
   ├─ PageHeader
   ├─ Workbar
   ├─ Main task surface
   └─ Optional inspector / task footer
```

Theme switching, workspace identity, navigation, and notifications are global. A calendar's date navigation or a source library's format filter is local. Avoid putting local workflow settings into the application topbar.

### 8.3 Navigation behavior

**Standardized:** route changes preserve browser back/forward behavior and meaningful deep links. A refresh should remain on the current page. Do not replay creative onboarding on every navigation or page refresh.

Show the active destination using both a selected glass state and an accessible current-page state. Do not rely on an unlabelled glow or dot.

The bottom navigation should contain the small set of frequent top-level destinations. Less frequent tools can live in More. Do not turn the five-item prototype navigation into ten cramped mobile icons as the app grows.

### 8.4 Long-page and keyboard behavior

Keep page content clear of fixed bottom navigation and any sticky primary action. The virtual keyboard must not cover the focused input or commitment action. Scroll the active field into view without jumping the user's document to the top.

The production app should have a skip link targeting the relevant main content, not permanently targeting `#idea` on every page. The prototype's skip destination is specific to its composer.

---

## 9. Universal page anatomy and action hierarchy

### 9.1 The reusable page frame

```text
Identity and context
    Page title + optional concise explanation

Primary workspace controls
    Task/dimension tabs where needed
    Search + view + labelled Filters
    Active filter summary, only when relevant

The work
    Collection / form / calendar / conversation / editor
    Optional contextual inspector

Commitment
    Selection or change summary
    One dominant next action for the current task
```

Do not automatically render every slot. A simple profile form may need only a title, grouped fields, and Save changes.

### 9.2 Action ladder

| Level | Visual weight | Use |
|---|---|---|
| Primary commitment | Inverted monochrome filled action | Save, approve, schedule, create draft |
| Secondary task | Quiet glass / neutral filled control | Connect channel, open filters, inspect |
| View/state navigation | Segmented lens or quiet tabs | Gallery/List, week/month, category |
| Tertiary utility | Text + optional icon | Clear filters, details, manage settings |
| Context action | Small labelled icon or overflow | Info, close, item-specific options |

“One primary action” means one dominant commitment action **per active task surface**. It does not mean the entire application can contain only one visible button. A global Create control and a local modal Save button may coexist if the inactive background is appropriately separated.

### 9.3 Rules that stop clutter returning

- Do not duplicate the same language or model control in two adjacent toolbars.
- Do not show a long settings summary that repeats all three full setting buttons directly below it.
- Do not keep every select open in the header after a labelled Filters trigger exists.
- Do not give a view-mode toggle the size and contrast of the main task tabs.
- Do not repeat the same research link in the header, filter panel, item card, and footer without a distinct contextual reason.
- Do not hide applied constraints. Show an active-filter count and a concise summary with Clear.
- Do not erase the distinction between applying a view filter and applying a change to the user's content.

### 9.4 Choosing the right layout

| Task | Layout archetype |
|---|---|
| Make/edit something | Creative work surface + optional preview |
| Browse many items | Collection + toolbar + optional inspector |
| Compare or configure | Grouped settings sections + review/save |
| Manage time | Calendar/agenda + selected-event detail |
| Communicate | Conversation list + thread + optional context |
| Learn or verify | Reading/evidence surface with references |

Reuse these archetypes across features instead of inventing a new dashboard style for each page.

## 10. Buttons and controls

### 10.1 Primary action

A primary action is a rounded rectangle with strong monochrome inversion. V8's dark-theme actions use a white-to-light-gray gradient with dark text; light-theme actions use a charcoal-to-black gradient with white text. It should be the clearest actionable object in the local task surface.

**Reference:** general generate action minimum height 56px; standard dialog primary approximately 51px before component overrides; library Apply 48px desktop and 46px mobile. [^v8-controls]

**Standardized:** 48px for ordinary primary actions; 52–56px for the main creative action. Use 14px text as the production default. The library's compact reference labels can remain when matching that component, but do not use 12px everywhere.

Rules:

- Use a clear verb and object: “Save changes,” “Generate drafts,” “Schedule post.”
- A trailing arrow or checkmark may reinforce the action; it does not replace the label.
- A busy action preserves its width, announces progress, and prevents accidental repeated submission.
- A disabled action includes nearby explanatory context when the reason is not obvious.
- Do not visually imply a destructive confirmation is harmless simply because the product is monochrome.

### 10.2 Secondary and tertiary actions

Secondary actions use quiet glass, not the full high-contrast primary fill. Tertiary actions are text or text-plus-icon. Secondary buttons in a row should match heights even when one is an input-like filter trigger.

A secondary action may be visually smaller but must remain operable. Distinguish the visible icon's size from its interactive hit area.

### 10.3 Icon buttons

The primary compact icon-button reference is **44 × 44px** with a centered icon around 18–22px. The closed state uses restrained glass. Labels belong in the accessible name and, when needed, a visible tooltip.

Only use icon-only controls for familiar or clearly contextual actions: close, theme, expand, information. A model switch, language choice, or complex workflow action should have a visible label and current value.

Do not use a bare play/pause triangle whose purpose is unclear. V8 moved artwork controls into a labelled Filters panel; retain that clarity when adding other motion preferences.

### 10.4 Segmented controls

A segmented control consists of a stable background, sibling buttons, and one persistent selection lens.

The lens moves; buttons do not remount or jump. All segments have equal height. Labels may vary in width when the options are genuinely uneven, but equal-width segments are the default for two or three short choices.

Semantics matter:

- Use a tab pattern when switching between associated panels.
- Use pressed buttons or a radio-group pattern for a mutually exclusive setting.
- Do not add `role="tab"` merely for styling.

Keyboard focus is separate from selection. Left/right keys may move through horizontal choices according to the selected pattern; Tab should not become trapped inside a nonmodal control.

### 10.5 Filter trigger and summary

The v8 Filters button is 46px high on desktop and 44px on mobile, matching its adjacent view controls. It includes a sliders icon, the word “Filters,” and a count when narrowing is active.

The closed panel does not erase the fact that results are filtered. Show an active summary and a Clear action. Clearing filters should follow an explicit rule about whether search is preserved; do not mix those behaviors arbitrarily across pages.

### 10.6 Switches and checkboxes

Use switches for a mode that changes immediately or reveals a staged choice. Use checkboxes for independent selections and explicit permissions.

A switch revealing further settings should state what becomes shared or enabled. In the language workflow, enabling shared mode reveals a choice; it does not silently commit a global language before the user selects and applies it.

Permission checkboxes need their own label and explanation. Source inclusion and permission to quote publicly are different controls, not one vague “Use this” checkbox.

---

## 11. Forms, selectors, and staged settings

### 11.1 Field anatomy

Each field is a small hierarchy:

**Label → input/control → optional helper or error.**

Place labels above controls for dense vertical forms; use side-by-side layouts only where labels and values remain readable. Do not rely on disappearing placeholders as the only label.

Default form controls should be borderless, with sufficient fill separation from the parent surface. Use consistent radii and heights. On mobile, prioritize full-width fields rather than squeezing multiple selects into a narrow row.

### 11.2 Native selects

V8 explicitly resets `appearance` and `-webkit-appearance` for its styled library selects, then places a consistent chevron beside the value. The final library select height is **48px**, with **16px** text and **12px** radius. [^v8-library]

Carry over both the dimensions and the reset. A styled input next to a browser-default select produces the inconsistent control geometry the user rejected in earlier versions.

A native select remains a good option for a small straightforward list. Use the richer searchable language picker for large, localized catalogues; do not create a custom combobox for every five-option setting.

### 11.3 Draft versus applied state

A selector that changes a consequential configuration should distinguish:

```text
Applied state → open editor → staged changes
                            ├─ Apply → commit deliberately
                            └─ Cancel / close → restore applied state
```

This is observed in content and channel selection. Use it for destination sets, reusable voice profiles, campaign defaults, model configuration, and other settings where exploratory clicks should not accidentally alter existing work.

Filters can update the view immediately because they are not mutations to the content. Make that distinction consistent: “Done” closes a filter panel; “Apply changes” commits a configuration.

### 11.4 Validation

**Extension:** show errors next to the field that caused them. Use plain language, an icon or text state, and a recovery action. Preserve entered values. Do not clear an entire form because one field failed.

For asynchronous checks, distinguish checking, unavailable, invalid, and verified. “Could not check” is not the same as “invalid.” Preserve the attempted value and provide Retry when sensible.

### 11.5 Expanded writing

The expanded writing surface should create real room to think: a larger textarea/editor, a stable header, optional context, and a clear return/apply action. It is not just the original small input in a large empty modal.

Edits must stay synchronized according to the stated interaction contract. Do not lose text when switching between collapsed and expanded modes. Production autosave, if implemented, must report genuine persistence status; v8's session-only behavior does not prove durable saving.

---

## 12. Dialogs, filters, tooltips, and overlays

### 12.1 Use the lightest appropriate container

| Need | Container |
|---|---|
| One short explanation | Tooltip or small descriptive popover |
| A few contextual controls | Popover / nested filter surface |
| A bounded selection or form | Dialog / mobile sheet |
| A persistent inspection task | Side panel on larger layouts; detail route or sheet on mobile |
| A long, independent workflow | A page, not a giant permanent modal |

The Content Library is a bounded choice, so a modal works. The whole Inbox should not be placed inside a modal merely because the library uses one.

### 12.2 V8 dialog anatomy

The library is a flex column with a stable header, a shrinking/scrollable content region, and a stable footer. The content region must have `min-height: 0`; otherwise it can overflow instead of scrolling.

**Reference sizing:** 910px dialog width; desktop height `min(910px, 94dvh)`; mobile width `calc(100vw - 12px)` and height `96dvh`. Use dynamic viewport units and safe-area accommodation, but validate virtual-keyboard behavior on physical devices rather than assuming those units solve every mobile issue. [^v8-library]

Do not hardcode the measured pixel heights of the header/footer. Their content must grow for translations, text zoom, or validation messages without swallowing the entire task.

### 12.3 Nested Filters surface

The v8 filter panel is 368px wide on desktop, with a 22px radius and 20px padding. On mobile it fills the available inner width, with 18px padding and a 20px radius. Its background is more opaque than ordinary controls so values remain readable over the library.

The temporary layer groups Category, Suggested app fit, artwork motion and access to evidence. Background library controls become inert while it is treated as a modal subtask. Closing restores focus to Filters, not an arbitrary element at the top of the page.

Future filter panels should keep the same anatomy, but populate only filters relevant to their task. Do not copy research and artwork controls into a billing filter panel.

### 12.4 Tooltip contract

A circle-i explanation is independent from the item selection. Pressing it must not choose the item, submit a form, or close the parent dialog.

Provide a meaningful accessible name, an associated description, and dismissal behavior. A descriptive tooltip should not contain a hidden form or a collection of focusable controls. Use a dialog/popover pattern for interactive content instead.

In v8, the information tooltip animates opacity over 180ms and a 4px offset over 220ms. It is clamped to the library bounds and closes before the library when Escape is pressed. Preserve this predictability. [^v8-library-motion]

### 12.5 Focus and dismissal

An actual modal keeps interaction and the tab sequence within the modal, moves focus inside on open, and restores focus logically on close. A visible close/cancel action remains available. Initial focus should suit the task; a large reading dialog may need its heading or introductory content focused rather than jumping to a distant button. [^w3c-dialog]

Nested Escape order:

1. Open tooltip or deepest transient explanation.
2. Filter/evidence child surface.
3. Parent dialog.
4. Never discard an unrelated page task as a side effect.

### 12.6 Overlay layering

**Standardized:** establish a documented layer scale, such as base content, sticky chrome, popover, scrim, modal, modal-child, and notification. Prefer the browser's dialog top layer or a deliberate portal strategy rather than page-specific `z-index: 999999` patches.

Native social mockups have their own internal layering. Their Dynamic Island, app header, or floating icons must not escape the phone's stacking context.

---

## 13. Collections: Gallery, List, and Pairings

### 13.1 One collection, several representations

The library's Gallery, List, and Pairings modes share the same staged selection and applicable search/filter state. Changing a representation must not duplicate records, lose selection, or secretly change the destination account set.

Reuse this principle for assets, campaigns, drafts, source documents, and templates. Not every collection needs all three modes:

- Gallery is useful when visual recognition matters.
- List is useful when titles, metadata and precise comparison matter.
- Pairings is useful when relationships or recommended combinations matter.

Do not add a third mode simply to satisfy visual symmetry.

### 13.2 Gallery card anatomy

```text
Semantic illustration / real thumbnail
    Selected check, if applicable

Dimension/category metadata
Title
Concise description
Suggested app fit or other useful metadata
Separate information action
```

V8 uses two columns for its desktop/tablet library and one column on mobile. Large artwork is approximately 8:5 in this implementation; preserve the actual asset aspect ratio rather than using an older requested 16:9 ratio by mistake. [^v8-art]

The image is not a blank decoration. It communicates the concept even when the title is not read. Each new taxonomy item has a distinct illustrative treatment.

### 13.3 List row anatomy

```text
Compact semantic SVG | Title + meaningful tags | state / relationship | info
```

Rows have enough vertical padding to distinguish items without creating a wall of full-size cards. Tags such as `editorial / everyday` are taxonomy information, not decoration. The info button is a separate hit target.

A list-view thumbnail is purpose-drawn at small scale, not a miniature of artwork containing unreadable fine text. Keep the title as the main recognition cue; the SVG supports it.

### 13.4 Pairings anatomy

Pairings explain a relationship: **editorial intent → presentation format → suggested app fit**. Include why the combination is useful and its boundaries.

A “Use pairing” action stages the editorial/native choices. It does not connect an app or select publishing destinations. Evidence labels are explicit: fit suggestion, usage signal, and engagement signal are not interchangeable.

The historical research catalogue is a static snapshot. Reusing the design should not copy stale numbers onto a production analytics page as if they were current or personal.

### 13.5 Filters and empty results

Filter values affect only the represented collection unless an explicit mutation action says otherwise. Keep an active count and a summary while the panel is closed. Clear/reset behavior must be labelled consistently.

An empty result is not an empty account. Say “No matches for these filters,” show what can be cleared, and preserve the user's underlying data. Distinguish no records, no matches, no access, offline, and failed retrieval.

### 13.6 Selection integrity

The selected state must appear on the card/row and in the selection summary from the same source of truth. Do not maintain a separate decorative checkmark state that can disagree with the footer.

A selected item filtered out of the current view remains selected unless the user explicitly changes it. The summary should reveal that state, not silently remove it because it is no longer on screen.

---

## 14. Illustration and icon system

### 14.1 Two scales, related meaning

V8 carries **51 large semantic illustrations and 51 compact glyphs** corresponding to the same 31 editorial and 20 native-format items. The large image explains; the small mark helps scan. [^v8-art]

For future features, extend this grammar: source file, voice profile, campaign, connection, approval, calendar event, and insight should each have a recognizable metaphor. Reuse existing artwork when the meaning is genuinely the same; do not reuse it merely because it fits the available dimensions.

### 14.2 Illustration style

- Light paper or stone-gray illustration field inside the dark interface.
- Simple layered geometry, restrained rotation, soft shadows.
- Clear semantic motifs: sequence cards for steps, side-by-side panels for comparison, waveform for audio, a date/pass for an event.
- Minimal text inside the illustration; the actual UI title remains selectable text.
- Consistent visual weight, whitespace and framing across the library.
- No stock-photo substitutions, external image URLs, emoji-only placeholders, or a label on a blank rectangle.

Real user assets are different: do not force photographs or brand media into grayscale merely to match Rafii chrome.

### 14.3 Icon treatment

Use a coherent line-icon system, generally around 1.5–2px strokes at common interface sizes. Match optical weight rather than mixing unrelated icon sets.

Company/provider symbols are the actual approved or licensed local brand assets. Do not sketch an approximate knot, star or asterisk as a substitute when a correct asset is available. Keep source/licence provenance and accessibility names. V8 inherits its brand assets; this guide does not re-certify every mark's licence for a new distribution context.

### 14.4 Asset metadata contract

Retain or add these fields for every generated taxonomy asset:

```ts
type SemanticIllustration = {
  thumbnail_id: string;
  thumbnail_kind: "svg" | "css_illustration" | "local_image";
  thumbnail_asset_path?: string;
  component_reference?: string;
  alt_text: string;
  aspect_ratio: string;
  visual_concept: string;
  source_type: string;
  content_hash?: string;
  version: string;
};
```

Use hashes for local asset bytes where applicable. Separate original art from adapted artwork. Provide unique SVG IDs for gradients, masks and clips when the same asset appears more than once on a page.

### 14.5 Decorative motion

Observed v8 artwork uses three restrained behaviors: glyph breathing over 4.8 seconds, paper motion over 6 seconds, and accent opacity over 4.8 seconds. Movement is about 0.9–1.2px with at most a small 0.3-degree paper rotation. Offscreen/background and user-paused artwork stops. [^v8-library-motion]

Animate a relevant detail, not the entire row label. Do not move text while someone is trying to read or select it. Reduced motion disables decorative loops rather than merely making them faster.

---

## 15. Composer and AI controls

### 15.1 Composer hierarchy

The composer is the primary creative surface, not a form made of unrelated settings cards.

```text
Draft identity + expand affordance
Idea / source input
Context and source actions
Content type + selected channels
Language | Model | Writing Voice
Primary generate/review action
Approval and state assurance
```

The three independent settings retain separate meanings. A single Tune button should not duplicate them. Their values are summaries, not additional disconnected dropdowns elsewhere in the same region.

### 15.2 Input versus result

Differentiate the user's original thought, included sources, generated draft, and edited result. Changing a provider or content format must not silently rewrite the user's original text.

If a production generation creates per-channel drafts, preserve each draft's version and selected configuration. A preview switch is not a generation request. Selecting a different output language changes future intent unless the user explicitly asks to regenerate or translate the existing draft.

### 15.3 Model selector

The v8 pattern is a selected-model capsule above a provider rail, searchable model list, and stable reasoning controls. Provider selection changes the visible catalogue; committing a model requires the defined selection flow.

The provider highlight and reasoning lens remain mounted. The list can crossfade, but do not rebuild the entire dialog—including the focused control—on every click.

All demo presets expose Low/Medium/High/Max preferences in the prototype. For the live app, validate the chosen provider/model's actual capabilities and map preferences transparently. If a backend does not support an equivalent parameter, show that honestly rather than silently claiming “Max reasoning” was transmitted.

### 15.4 Reasoning visualization

A group of four vertical bars shows intensity:

| Preference | Lit bars |
|---|---:|
| Low | 1 |
| Medium | 2 |
| High | 3 |
| Max | 4 |

The text label and accessible description identify the value; the bars are a reinforcing visual. The inactive bars stay visible but subdued. The capsule and bars animate smoothly without delaying the underlying choice.

This is a configuration indicator, not an animation of the model's private reasoning or a measurement of actual compute consumed.

### 15.5 Writing Voice

Keep a clear distinction between a selected voice profile and a casual tone modifier. Voice setup should show what the profile is based on and allow review/editing. A warm-looking orb is not evidence that the system has learned someone's voice.

A production voice page should use the same panel, source, version, status and approval grammar as other knowledge features. Do not create a separate colorful onboarding theme for AI-related pages.

### 15.6 Approval

The design must reinforce the difference between drafting, approving, scheduling and publishing. “Generate” cannot secretly mean “Publish.” The primary action should change label and confirmation context as the user crosses those boundaries.

In production, show the destinations, final content version, timing/timezone and any unsupported format issues before a publish/schedule commitment. These are workflow extensions, not connected services in v8.

---

## 16. Language and localization

### 16.1 Four separate concepts

1. Interface language: the app's controls and messages.
2. Output language: what a generated channel draft is intended to use.
3. Source language: the language of material being referenced.
4. Locale: regional script, formatting, timezone and related conventions.

Do not combine these into one global flag button. A language flag is an affordance, not a complete language identifier.

### 16.2 Full picker presentation

V8's local catalogue contains 196 language/region options, with native labels, English descriptions, search, flags or regionless symbols, and script/region distinctions. Preserve the canonical locale IDs and display-name behavior when migrating the component. [^v8-locale]

A production picker should handle native-script search, regional aliases, empty results and keyboard navigation. Local labels should not be rebuilt ad hoc on each page.

### 16.3 Independent channel settings

Each channel can keep its own output locale. A global shared-language mode is an override, not a destructive overwrite of all saved individual values.

The sequence remains:

**Enable shared mode → expand the containing glass box → choose the language for every channel → apply deliberately.**

Turning shared mode off restores the saved individual choices. Closing without applying does not mutate the current configuration.

### 16.4 Localized layout

Reserve room for long native labels. Use wrapping or a native-name/English-subtitle stack. Keep a 16px entry/select size on mobile. Right-to-left labels get their appropriate direction; the surrounding app direction follows the chosen interface locale, not the language of a single output option.

Use logical CSS properties for new components. Test long German-style labels, Traditional Chinese, Japanese, Arabic, and mixed Latin/RTL content. Do not assume a date such as `09/10` is unambiguous; include localized formatting and an explicit timezone where timing matters.

### 16.5 Fonts and flags

Use system flag rendering or vetted local vector assets according to the actual picker implementation. Do not ship platform font files to imitate another operating system's flag glyphs. A globe is preferable to inventing a country for a regionless language.

---

## 17. Native social-app previews

### 17.1 Purpose

The phone preview answers, “How might this content appear in its destination?” It is an inspection tool, not an additional version of the app's navigation.

The surrounding frame, app selector and expand action belong to Rafii. The in-phone layout belongs to the simulated destination. Keep those boundaries visible.

### 17.2 V8 phone geometry and state

The transition engine uses one active phone and up to two decorative neighbours. The active phone is fully opaque and centered. Neighbours sit around ±65% horizontal offset, scale 0.83, rotate approximately ±14 degrees around the Y axis and use opacity 0.2. The transition lasts 560ms with `cubic-bezier(.22,.78,.22,1)`. [^v8-phone]

These values describe the approved dimensional effect. Apply this effect only to preview decks or analogous physical-object comparisons, not every tab, table row, or input field.

### 17.3 Interaction contract

- Swipe/drag horizontally to select another preview.
- Keep vertical scrolling available for the post body.
- Small, diagonal, cancelled, or multi-touch gestures must not accidentally switch.
- A tap or keyboard-controlled platform selector is an equivalent path; swipe is not the only way.
- Rapid switches settle on the final requested destination.
- Outgoing layers become inert and hidden from assistive technology.
- Edits update the active preview without replaying a transition.
- Previewing an app does not add/remove it from the generation destination set.

### 17.4 Fidelity and honesty

Do not display invented engagement counts, connected-user avatars, published timestamps, or verified-state badges merely for polish. Identify sample content and unsupported preview branches when applicable.

When applying Rafii styling elsewhere, never put the entire production app inside a decorative phone. Device frames are contextual preview tools, not an application shell.

---

## 18. Motion system

### 18.1 Motion principles

**Continuity:** the user should understand where a view, selected state, or object went.

**Responsiveness:** state changes are immediate logically; animation only presents that transition.

**Interruptibility:** a second action can change direction or destination without a stale completion callback restoring the old state.

**Restraint:** most motion is opacity, a small translation, a selected-state glide, or a measured expansion. Dramatic motion is reserved for the phone-preview effect and similarly meaningful transitions.

### 18.2 Extracted motion tokens

| Interaction | Observed duration | Easing / detail |
|---|---:|---|
| General control feedback | About 200–260ms | Color/fill transitions |
| Information tooltip opacity | 180ms | `ease` |
| Information tooltip offset | 220ms | `cubic-bezier(.22,1,.36,1)`; about 4px |
| Standard dialog exit | 170ms | `ease-in`; 12px down; scale 0.965 |
| Filter panel enter | 270ms | `cubic-bezier(.22,1,.36,1)`; −8px to 0; scale .98 to 1 |
| Filter panel exit | 170ms | `ease-in`; approximately −5px and .985 scale |
| Library view crossfade | 320ms | `cubic-bezier(.22,1,.36,1)` |
| Library view lens | 370ms | Same soft-out curve |
| Taxonomy dimension lens | 400ms | Same soft-out curve |
| Generic state/list swap | 430ms | Outgoing −18px; incoming +22px; height interpolation |
| Provider and reasoning lenses | 440ms | Same soft-out curve |
| Measured disclosure height | 480ms | Same soft-out curve |
| Disclosure inner reveal | 330ms, delayed 100ms | −7px to 0 with opacity |
| Standard dialog enter | 400ms | `cubic-bezier(.2,.8,.2,1)` |
| Trigger-origin dialog enter | 560ms | Same interface curve; scaled from trigger region |
| Phone deck switch | 560ms | `cubic-bezier(.22,.78,.22,1)` |
| Decorative glyph / paper | 4.8s / 6s | `ease-in-out`; pause when not relevant |

These are extracted values, not a universal requirement to slow down every interaction to 560ms. New dense operational views should use the shortest token that preserves clarity. [^v8-motion]

### 18.3 The real-crossfade contract

```text
Read current geometry and visual state
→ cancel prior transition ownership
→ retain one inert outgoing representation
→ mount/update the incoming representation
→ animate both within a stable host
→ remove outgoing only after the current transition completes
```

A new request supersedes the old request. Completion callbacks must verify their transition identity before changing the DOM. Cancelled animations must not leave invisible layers intercepting clicks or retained IDs conflicting with the live content.

### 18.4 Measured disclosure

For an expanding panel, measure the currently rendered height before changing its contents. Compute the destination height, then animate between real numeric values. Restore `height: auto` after opening completes; use a closed/inert state after closing.

Do not simultaneously animate a `0fr → 1fr` grid row, a hardcoded `max-height`, and an independently toggled `display` on the same element. That produces the sudden “pop” and layout discontinuity previously rejected.

### 18.5 Selected lenses

The lens belongs to the control, not to the selected button's newly mounted subtree. Keep its origin and dimensions stable. Theme or text changes may require recomputing geometry; they should not destroy the selection.

Do not animate borders, neon halos, or scale the selected text as the primary indication. Position, fill and a small check state are sufficient.

### 18.6 Motion limits for new pages

**Standardized:** navigation should remain usable immediately. Do not delay input availability until an ornamental entrance ends. Avoid staggered entrance of every item in a long inbox or table. Animate only the local change when data updates.

Respect reduced motion through a single shared predicate that considers the OS preference and the app's explicit setting. Reduced motion disables spatial transitions and decorative loops; selection, focus and state updates remain intact. [^mdn-motion]

---

## 19. Responsive and touch behavior

### 19.1 Observed breakpoints are component-specific

| Threshold | V8 behavior |
|---|---|
| 1550px and wider | More top breathing room in the creative workspace |
| 1190px and below | Narrower desktop outer padding and column gap |
| 980px and below | Composer/preview workspace becomes single-column |
| 800px and below | Library workbar stacks; search is above view/Filters |
| 760px and below | Mobile app shell and navigation adaptations |
| 600px and below | Mobile library, one-column gallery, stacked summary/action |
| 374px / 359px and below | Additional compact-label and icon adjustments |

Do not replace these with one arbitrary framework breakpoint and assume the design will remain identical. For new layouts, use content-based breakpoints or container queries while retaining the same behavioral outcomes.

### 19.2 Mobile priorities

The first mobile viewport should expose the task and useful content, not just the title and controls. Collapse advanced settings; do not collapse the primary action or current selection into an unexplained icon.

Prefer a full-width search row where an adjacent select makes the field unusably narrow. Maintain at least 44px working targets as the product target. Long labels may force the workbar to wrap; this is better than squeezing controls to tiny widths.

### 19.3 Responsive tables and grids

Desktop tables can become card-like rows or a focused subset of columns on mobile. Make omitted fields available in detail view. Do not put a 12-column analytics table in a 390px viewport with unreadably small text.

Keep two-column galleries only when the images, titles and actions remain useful. The approved content library switches to one column on phones because the semantic illustrations need room.

### 19.4 Sticky areas

A sticky header/footer should be a tool, not a permanent tax on content space. Prefer one scrollable work area per bounded dialog. Avoid nested arbitrary scrolling inside every panel.

When content grows due to filters, long text, or an error, the interface must continue to expose close and commit actions without covering the focused field. Test at small height as well as small width.

### 19.5 Input modalities

Desktop hover can add subtle elevation, but touch must not depend on hover to reveal essential information. Keyboard users receive visible focus and equivalent selection. A drag-only interaction requires a button or keyboard path as well.

Do not intercept vertical pointer gestures simply to make the phone deck swipe feel strong. Preserve normal reading and browser zoom behaviors.

---

## 20. System states and data truthfulness

### 20.1 Common state vocabulary

**Extension:** use the same visual grammar across jobs, content, connections and resources, with domain-specific wording.

| State | Visual behavior | Content requirement |
|---|---|---|
| Initial / empty | Quiet illustration + one relevant action | Explain what belongs here |
| Loading | Stable geometry; restrained skeleton/progress | State what is being loaded |
| Ready | Normal contrast and usable controls | Show the actual available data |
| Dirty / unsaved | Subtle but explicit change indicator | Offer save/discard without data loss |
| Saving | Local busy state, no fake completion | Indicate the operation in progress |
| Success | Calm confirmation and next context | Claim only what the backend confirmed |
| Partial result | Retain completed content, identify gaps | Say which items succeeded or failed |
| Error | Clear message close to the failure | Preserve input; give a recovery path |
| Offline / stale | Explicit freshness state | Show cached/as-of context, not a live claim |
| Permission required | Explanation + deliberate action | Distinguish missing permission from empty data |
| Unsupported | Disabled/alternative path with reason | Do not imply a model/platform can do it |

### 20.2 Job state is not content state

A draft can exist while its latest generation job failed. A post can be approved without being scheduled. A scheduled item can have a connection error. Represent these separately instead of forcing all meaning into one badge.

A useful production model is:

```text
Content lifecycle: draft → in review → approved → scheduled → published
Job lifecycle:     idle → queued → running → succeeded / failed / cancelled
Connection state:  ready / needs permission / expired / disconnected / unknown
```

These names are proposed workflow categories, not an assertion about the current backend schema.

### 20.3 No simulated production truth

The v8 draft sequence is explicitly a demo. Do not reuse its deterministic delay as the production progress indicator or carry its sample account names into live UI.

A successful copy action is not a saved draft. A saved draft is not a published post. A model selected in a dialog is not an authenticated provider. A local file shown in a Context Pocket is not proof of completed ingestion.

### 20.4 Errors should not change the design language

An error should not suddenly become a bright red full-page design from another product. Use the same surface, spacing and typography, with a clear warning icon, explicit language, and a recovery action. Introduce any semantic tint only through an approved shared token, never ad hoc component colors.

## 21. Page-by-page application recipes

**All recipes below are extensions of the v8 language, not claims of completed pages.** Map them to the actual repository's existing routes and features before implementation. Preserve working workflows and permissions; do not add or rename routes simply to match this chapter.

### 21.1 Create / Home

**Purpose:** turn a thought into channel-specific drafts.

**Composition:** preserve the signature creative layout: a short eyebrow, a large sans/serif-accent greeting, one glass composer, contextual controls, then a faithful preview. On desktop the preview can sit beside the composer; on mobile it follows the creative surface rather than compressing it.

**Primary action:** Generate drafts, changing to the appropriate review step after completion. The action's disabled/busy states explain why it cannot run.

**Secondary controls:** Context, content type, channels, Language, Model, Writing Voice, expand writing space. Keep settings in their existing distinct roles.

**Design adaptation:** do not copy the named “James” greeting or sample account counts literally. Personalization must come from real context or a neutral fallback. Remove stale prototype version labels in production; they are reference metadata, not product identity.

**Critical check:** changing format, preview, theme or language must not destroy the original idea or an edited draft.

### 21.2 Draft editor / Composer detail

**Purpose:** work deeply on one draft, its variants, and its approval state.

**Composition:** use a focused editor page with a stable draft identity row and a primary text/media canvas. A contextual inspector can contain channel settings, content type, model/voice metadata and preview. Long writing should use a regular, readable text style rather than carrying the large italic homepage placeholder into every paragraph.

**Primary action:** Save changes, Request review, or Schedule, according to state. Do not show all three as equal high-contrast buttons.

**Mobile:** editor first; configuration becomes a sheet or a distinct panel. The keyboard should not hide save state or the current line. Keep the expand/collapse path for focused writing.

**Critical check:** clearly distinguish per-channel edits from shared input. Applying a common change should state whether it will replace individual versions.

### 21.3 Calendar / Agenda

**Purpose:** understand what is planned and when it will happen.

**Composition:** a compact functional heading, date navigation, period/view control, and labelled Filters above a neutral calendar surface. Use quiet cells and small structured event cards, not a shiny card around every day. Selected dates/events can use the shared glass lens or selected fill.

**Primary action:** Create/schedule a post. When an event is selected, its detail surface has the relevant Save/Reschedule action.

**Mobile:** default to a useful agenda or a readable compact period view. Do not render a seven-column desktop grid with tiny titles as the only path.

**Critical checks:** timezone is explicit; drafts, approved items and scheduled items are visually and textually distinct; drag-to-reschedule has a keyboard/button alternative; moving a scheduled item does not silently publish it.

### 21.4 Queue / Review & Publish

**Purpose:** see what needs attention and move content through an approval workflow.

**Composition:** state tabs such as Drafts, In review, Scheduled and Published where the real workflow supports them. Put counts next to the state labels. Use a list as the default for managing many items, with optional visual preview on selection. Filters and sorting belong in the workbar, not repeated on each item.

**Primary action:** the current review/commit action. Batch selection introduces a contextual selection bar rather than another permanent toolbar.

**Visual details:** status icon + label, destination marks, title/snippet, time, owner/reviewer and freshness are ordered by task importance. A failed publish should remain inspectable beside successful destinations.

**Critical check:** bulk approval, regeneration, deletion, and publication are different actions. Do not combine them in one ambiguous “Process” button.

### 21.5 Inbox / Conversations

**Purpose:** read, understand and respond to conversations.

**Composition:** a left conversation list, a central thread, and an optional contextual inspector on wide screens. Use one clear hierarchy for unread state, participant, snippet and recency. Keep message text on quiet, readable surfaces. Reserve glass for selected conversations, reply composer and contextual controls.

**Primary action:** Send reply in the active conversation. AI assistance stages a reply; it does not automatically send it.

**Mobile:** show the list and thread as separate steps with clear Back navigation. Do not place a full conversation list beside a squeezed 150px thread.

**Critical checks:** thread changes preserve drafts when appropriate; external platform identity is visible; loading older messages does not jump scroll; failed-send messages remain editable and retryable.

### 21.6 Channels / Connections

**Purpose:** manage actual destination accounts and understand what each connection can do.

**Composition:** use platform icon + account identity + connection status + capabilities/limitations. A channel card may use glass, but do not replace useful account identity with an oversized platform logo.

**Primary action:** Connect channel. Item-specific Reconnect or Manage actions are secondary unless the whole screen is a recovery flow.

**Grouping:** if the product supports folders/account groups, use named groups with clear membership and batch selection. A folder is not a new platform. Selecting a group should not imply all members are connected or publish-capable.

**Critical checks:** connected, expired, disconnected, missing permission and unknown state are distinct. Show the exact affected account, not just “Instagram.” Do not invent an OAuth success state for a polished screenshot.

### 21.7 Learn My Voice / Voice profiles

**Purpose:** help users review and control how Rafii represents their writing.

**Composition:** a source summary, profile description, editable voice attributes, examples and an explicit review/apply flow. The visual signature can include a small waveform or paper illustration, but the substance is the evidence and editable profile.

**Primary action:** Review profile / Save voice, depending on the step. A “Learn” action must identify its source scope and authorization.

**Layout:** comfortable panels with readable examples, not a collection of vague sliders. Use side-by-side before/after writing examples on desktop and stacked examples on mobile.

**Critical checks:** generated inference is labelled as a draft interpretation; the user can correct it; sources and permissions are visible; voice selection in the composer links back to a versioned profile rather than a disconnected label.

### 21.8 Brand Brain / Brand knowledge

**Purpose:** maintain the approved facts, positioning, preferences and reference material used for content.

**Composition:** a searchable collection with categories such as Brand facts, Products, Audience, Guidelines and References if those categories exist in the real system. Use List for precise knowledge and Gallery where imagery helps. An inspector contains the selected entry's content, source, revision and status.

**Primary action:** Add knowledge. Editing an item gets its own Save changes action.

**Visual details:** ownership, update time, approved/draft state and source attribution are quiet metadata, but never hidden so deeply that content appears authoritative without evidence.

**Critical check:** distinguish user-entered facts, imported source text, and AI suggestions. Updating a reference should not retroactively relabel already published content as using a different version.

### 21.9 Assets / Media library

**Purpose:** find reusable media and understand rights, formats and readiness.

**Composition:** Gallery for images/videos, List for filenames/metadata, one consistent search/filter workbar. Keep actual images in their natural colors; Rafii's surrounding UI remains neutral. Selected state belongs outside the image's meaningful content or in a predictable corner.

**Primary action:** Upload assets. Within a picker, use Use selected assets rather than an unrelated publishing verb.

**Mobile:** comfortable one/two-column media tiles according to content, with clear selection count and a stable confirm button. Do not hide filenames and rights entirely behind hover.

**Critical checks:** uploaded, uploading, failed, processing and ready are separate; permission/licence fields are inspectable; unsupported files have an explanation; broken media never renders as a blank box.

### 21.10 Sources / References

**Purpose:** manage the material supporting a draft or knowledge task.

**Composition:** readable document rows with type, title, source location, inclusion state and processing status. A paper/document icon is appropriate; decorative miniatures should not replace a meaningful filename.

**Primary action:** Add source. In a draft context, Done/Use sources commits the current source selection.

**Permission design:** inclusion in analysis and permission to quote publicly remain separate. Use explicit labels rather than one consent checkbox with several hidden consequences.

**Critical check:** a missing field or failed fetch is not a declaration that the source contains no relevant information. Preserve failure state and make retry/removal available without erasing other sources.

### 21.11 Campaign Planner

**Purpose:** coordinate a coherent sequence, not merely a pile of scheduled posts.

**Composition:** campaign identity and objective, an ordered plan/timeline, channel mix, draft status and optional calendar view. Use the same content-type miniatures to distinguish editorial intentions. A campaign's components should visually relate through order and spacing, not a different palette per campaign.

**Primary action:** Create plan / Prepare drafts / Submit for review, depending on the stage. Keep execution separate from planning.

**Mobile:** an ordered plan list with expandable items. Do not force a wide Gantt-style surface without a useful alternative.

**Critical checks:** recurring preparation tasks and recurring publication are different; generated schedules are proposals until approved; per-post edits and campaign defaults have clear precedence.

### 21.12 Suggestions / Opportunities

**Purpose:** surface useful next actions without overwhelming the user.

**Composition:** a small prioritized list, with reason, affected channel/topic, evidence or context, and a clear action. Use an editorial illustration only when it improves recognition. Do not create a full promotional hero for every suggestion.

**Primary action:** Use suggestion / Create draft. Dismiss, postpone or explain should be secondary.

**Evidence:** a suggested content gap is not a guaranteed performance opportunity. Label estimates, sample observations, and account-specific facts differently.

**Critical checks:** recommendations are relevant and dismissible; dismissing one is respected; suggestions do not auto-fill a publishing queue without an explicit action.

### 21.13 Analytics / Reports

**Purpose:** help users understand measured performance and make informed decisions.

**Composition:** a clear period/account scope, a restrained metric summary, one central analytical view, and explanatory context. Use quiet chart backgrounds, labeled axes, tabular numbers and a consistent empty/unavailable state.

**Visual grammar:** grayscale series can use line style, markers, weight and direct labels. If the system later adopts semantic data colors, they must be a documented shared extension, not a new dashboard theme.

**Primary action:** View report / Export, if implemented. Do not add a dominant CTA merely to fill the header.

**Critical checks:** impressions, reach, engagement, posting frequency and unique users are distinct metrics; denominators and dates are visible; missing accounts and partial sync are disclosed; static research benchmarks are not presented as the user's analytics.

### 21.14 Models / Integrations / API configuration

**Purpose:** configure real provider access and understand available capabilities.

**Composition:** a provider/account list, connection/configuration details and a small capability summary. Reuse the provider icon rail only when it helps browse a focused catalogue; use a standard settings layout for credentials and technical fields.

**Primary action:** Connect / Save configuration / Test connection, according to the task. A connection test does not imply model availability or successful content generation.

**Security-related UI:** masked secrets, explicit reveal/copy where permitted, no secrets in toasts or previews. A local CLI option needs an honest environment boundary, not a button that pretends the browser can run an arbitrary local command.

**Critical checks:** display saved configuration and active runtime status separately. A selected model preference can remain visible while its connection is unavailable.

### 21.15 Settings / Profile / Workspace

**Purpose:** let people make precise, reversible configuration changes.

**Composition:** a calm settings navigation with grouped forms. Use section titles, clear labels, helper text and one save action per independent group or an explicit page-level dirty-state bar. Do not place every field in an independent card.

**Primary action:** Save changes when required. Immediate preferences such as appearance may apply instantly, with consistent semantics.

**Mobile:** vertical groups and full-width controls. Destructive/account-management actions live in a clearly named lower-priority section, not beside the main profile save action.

**Critical checks:** role/permission restrictions are explained; changing interface language does not change per-channel output language; workspace switching does not leak or overwrite another workspace's drafts.

### 21.16 Onboarding / Sign-in / Invitations

**Purpose:** enter the product with a clear understanding of the next step.

**Composition:** a restrained identity block, one central form or choice surface, concise explanation and a clear primary action. Reuse the same typography, button shapes and theme behavior as the signed-in app.

**Avoid:** a colorful marketing-style onboarding flow that looks unrelated to the workspace, or a mandatory animation that delays sign-in.

**Critical checks:** form errors preserve input; account selection is explicit; an invitation communicates workspace and permissions; optional voice/channel setup can be deferred where the product allows it.

### 21.17 Notifications / Activity

**Purpose:** show what needs attention and what happened.

**Composition:** a compact chronological list with icon, clear action/result, related item and time. Distinguish unread from urgent. Use grouped notifications rather than repeated identical cards.

**Primary action:** context-specific, such as Review failed post. A general notification panel rarely needs an enormous primary button.

**Critical checks:** a background job notification represents actual events; opening a notification routes to the exact item; marking read does not execute an approval or publish action.

### 21.18 Plans / Billing / Usage

**Purpose:** make commercial state and limits understandable.

**Composition:** current plan, actual usage scope, billing dates and a clear manage action. Use the same quiet panels and tabular data, not a neon pricing microsite embedded in settings.

**Primary action:** Manage plan / Update payment method, reflecting the real flow. Paid changes need clear terms before confirmation.

**Critical checks:** display actual connected billing data or a labelled unavailable state. Do not invent prices, credit balances, consumption, model costs or predicted savings. A prototype's sample plan is not the user's current subscription.

### 21.19 Public landing / Product education

**Purpose:** explain the product and bring users into the actual workspace.

**Composition:** allow more editorial breathing room, larger selective typography and short demonstrations of real workflows, but retain the same monochrome palette, surfaces, icons and controls.

**Primary action:** a clear entry path such as Sign in or Get started, according to the actual product. Marketing imagery should not imply unsupported automation or publishing capabilities.

**Critical check:** the transition from landing page to signed-in app should feel continuous. The product should not change to a different visual theme after authentication.

---

## 22. Copy, tone, and information design

### 22.1 Voice

Rafii sounds like a considerate colleague: direct, warm, specific, and comfortable with restraint. The interface may use a short editorial phrase at the top, then plain functional language in the work area.

| Prefer | Avoid |
|---|---|
| “Find your next idea.” | “Unlock limitless AI-powered content magic.” |
| “Choose where this draft should go.” | “Omnichannel distribution configuration.” |
| “3 drafts ready to review.” | “Success!” without explaining what succeeded |
| “This connection needs permission.” | “Something went wrong.” as the entire message |
| “Your changes are saved.” after confirmation | “All set!” while a write is still pending |
| “No matches for these filters.” | “No content exists.” when the view is merely filtered |

### 22.2 Copy hierarchy

Page headlines can have personality. Buttons must describe actions. Helper text explains consequences, not repeat the label. Error text identifies the failed step and recovery. Metadata is quiet but factual.

Avoid abbreviations that require product expertise. A badge reading “API/CLI” can exist in a technical model selector, but it should be explained before asking a nontechnical user to choose it.

### 22.3 Evidence labels

Use explicit language for interpretation boundaries:

- **Suggestion:** a proposed fit or action, not a measured fact.
- **Usage:** observed posting frequency or use in a defined sample.
- **Engagement:** a response measure with its denominator and period.
- **Sample:** illustrative content, not a live account result.
- **Unsupported / unverified:** capability has not been established.

Do not collapse these into a generic “Popular” badge. Keep source detail accessible without repeating a long disclaimer under every card.

### 22.4 Counts and names

Counts should come from data, not hardcoded 31/20/196 strings copied into every new feature. The prototype numbers describe its inventory. A selected account uses its real name/handle, not only the social app's name. A collection uses its actual count, including filtered versus total counts where useful.

---

## 23. Accessibility and reduced effects

### 23.1 Product targets versus standards

**Rafii's product target is at least 44 × 44 CSS pixels for primary touch controls**, with 48px standard form fields where practical. This is deliberately stronger than the WCAG 2.2 AA minimum target-size criterion, which is 24 × 24 CSS pixels with specified exceptions and spacing provisions. Do not describe “44px everywhere” as the exact AA requirement. [^w3c-target]

The prototype includes some smaller auxiliary controls. Expand their hit area or improve spacing when promoting them to production; do not assume every observed control already satisfies a full accessibility audit.

### 23.2 Contrast

Use at least 4.5:1 for normal text, and 3:1 for qualifying large text. Essential non-text UI/state indicators need adequate contrast against adjacent colors; the non-text criterion uses a 3:1 threshold in its covered cases. Decorative art and disabled states have different applicability, but “decorative” must not become an excuse for unreadable required information. [^w3c-contrast] [^w3c-nontext]

For glass, inspect the composited result over the actual background. A gray text token that passes on pure black may fail over a brighter selected surface or real media. Validate default, selected, focused, error and both themes.

### 23.3 Focus and keyboard

Keep a visible focus outline even though resting chrome is borderless. V8 commonly uses a 2px outline; the library moves it inward where an outer outline would be clipped. Prefer a visible, unclipped ring rather than `outline: none`.

Use meaningful native elements and the correct ARIA pattern. Focus order follows reading/task order. Keep controls operable by keyboard; do not create nested buttons, focusable elements inside hidden outgoing layers, or a modal that lets focus escape behind its backdrop.

### 23.4 Motion and transparency preferences

Respect `prefers-reduced-motion` and the app's pause setting. Reduced motion should remove nonessential spatial animation and ongoing decorative movement while keeping the selected state clear. It must not freeze the task or leave the UI halfway through an animation. [^mdn-motion]

An additional reduced-effects preference is a **recommended extension** for users who find glass distracting or for constrained devices. Use more opaque surfaces and minimal reflections; preserve the same layout and control hierarchy.

### 23.5 Responsive accessibility tests

Test text enlargement, keyboard-only operation, focus visibility after opening/closing dialogs, screen-reader labels and announcements, long translated labels, high-contrast/forced-color environments, and small-height viewports. Validate the real iPhone/Safari workflow before making a physical-device compatibility claim.

A screenshot with readable text is useful evidence, not proof of full conformance. A passing unit suite is not a screen-reader audit.

### 23.6 Status announcements

Use concise live-region messages for meaningful events: results changed, selection count changed, draft saved, upload failed. Do not announce every animation frame or each decorative icon. Keep success feedback tied to actual state, and avoid multiple competing live regions saying the same thing.

---

## 24. Reusable implementation architecture

### 24.1 Build a component system, not page-specific patches

V8's HTML includes eight stylesheet layers accumulated over several revisions. That is valuable extraction evidence, but not the desired production architecture. Resolve the intended cascade into shared tokens and components instead of adding another override file for every page.

**Recommended structure:**

```text
design/
  Rafii_Design_DNA_v8.md
  tokens.css
  motion-tokens.ts
  reference-images/

ui/
  app-shell/
  page-header/
  workbar/
  surface/
  button/
  segmented-control/
  filter-panel/
  field/
  dialog/
  tooltip/
  collection/
  semantic-illustration/
  state-message/

features/
  composer/
  channels/
  content-library/
  voice/
  knowledge/
  calendar/
  review/
  inbox/
```

This is a suggested boundary, not a required framework, folder naming convention, or package installation. Fit it into the existing project structure.

### 24.2 Shared component contracts

| Component | Essential inputs/states |
|---|---|
| Surface | material, padding, radius, density, semantic element |
| Button | variant, size, loading, disabled, icon, accessible name |
| Segmented control | options, selected key, focus policy, controlled change |
| Workbar | search slot, view slot, filter trigger, active-filter summary |
| Filter panel | fields, active values, clear behavior, focus return |
| Dialog | title, initial focus, close policy, dirty-state policy, footer |
| Collection item | identity, selection, primary content, metadata, separate actions |
| Semantic illustration | stable ID, size role, alt/decorative mode, motion permission |
| Preview deck | active destination, item models, reduced motion, swipe/keyboard callbacks |
| State message | status type, explanation, recoverability, action |

Keep data and display state outside purely presentational components. A card should not connect an account simply because its logo was clicked.

### 24.3 State boundaries

Use controlled state for current route, workspace, active account set, applied settings, staged modal changes, content versions, and job status. Separate view preferences from content mutations.

A model selector should not rebuild the global header. A filter panel should not own the underlying collection. A phone preview should not hold the only copy of a draft. The user-editable text and the native mockup must derive from the same content state.

### 24.4 Framework independence

The v8 prototype uses DOM/CSS/Web Animations API code. Its design does not require React, Tailwind, Rive, Hyperframe, or a new animation library. Use the existing stack and only introduce a dependency if a concrete requirement cannot reasonably be met with the current tools.

Where the production app already has a reusable language selector, model catalogue or native preview subsystem, adapt that component's appearance rather than duplicating its data rules into a second divergent implementation.

### 24.5 Performance safeguards

Pause decorative animation offscreen and in background tabs. Avoid expensive full-page blur during continuous scrolling. Virtualize very large collections if needed without breaking keyboard order, selection or screen-reader access.

Limit outgoing animation layers to the minimum needed for a transition. Cancel and remove them deterministically. Do not retain an entire old page tree after each filter/view change.

---

## 25. Copy-ready token and component foundation

The following CSS is a **standardized starting point derived from v8**, not a drop-in replacement for its complete stylesheet cascade. It intentionally increases ordinary reading/label sizes, gives tokens semantic names, and leaves component-specific page dimensions to each layout. Apply inside the app's existing style architecture and compare against reference screenshots.

```css
/* Rafii design system foundation — v8-derived, app-wide standard. */
:root {
  color-scheme: dark;

  --rafii-bg: oklch(0 0 0);
  --rafii-text-primary: oklch(1 0 0);
  --rafii-text-secondary: #a1a1a1;
  --rafii-text-tertiary: #848484;
  --rafii-panel-rgb: 19 19 19;
  --rafii-highlight-rgb: 255 255 255;

  --rafii-action-bg: #ffffff;
  --rafii-action-fg: #080808;
  --rafii-action-fill:
    linear-gradient(125deg, #ffffff, #dedede 58%, #f5f5f5);

  --rafii-surface-glass:
    linear-gradient(135deg,
      rgb(255 255 255 / .13),
      rgb(255 255 255 / .055) 40%,
      rgb(255 255 255 / .04) 65%,
      rgb(255 255 255 / .08));
  --rafii-surface-selected:
    linear-gradient(140deg,
      rgb(255 255 255 / .23),
      rgb(255 255 255 / .10) 60%,
      rgb(255 255 255 / .17));
  --rafii-surface-elevated:
    linear-gradient(130deg,
      rgb(38 38 38 / .94),
      rgb(21 21 21 / .90) 62%,
      rgb(38 38 38 / .94));
  --rafii-surface-quiet: rgb(var(--rafii-highlight-rgb) / .035);
  --rafii-surface-solid-fallback: #242424;
  --rafii-scrim: rgb(0 0 0 / .5);

  --rafii-shadow-glass:
    0 15px 40px -22px #000c,
    inset 0 5px 17px -13px #ffffffa0,
    inset 0 -5px 18px -14px #fff4;
  --rafii-shadow-dialog:
    0 30px 100px #0009,
    inset 0 16px 40px -38px #fff;

  --rafii-font-ui:
    Geist, -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif;
  --rafii-font-editorial: Georgia, "Times New Roman", serif;
  --rafii-font-mono: ui-monospace, "SFMono-Regular", Consolas, monospace;

  /* Standardized type roles; not all are literal v8 measurements. */
  --rafii-text-body: 1rem;
  --rafii-text-control: .875rem;
  --rafii-text-meta: .75rem;
  --rafii-text-page-title: clamp(1.75rem, 2.4vw, 2.25rem);
  --rafii-text-creative-title: clamp(2.5rem, 3.5vw, 3.25rem);
  --rafii-leading-body: 1.6;
  --rafii-leading-label: 1.35;
  --rafii-leading-heading: 1.15;

  --rafii-space-1: .25rem;
  --rafii-space-2: .5rem;
  --rafii-space-3: .75rem;
  --rafii-space-4: 1rem;
  --rafii-space-5: 1.25rem;
  --rafii-space-6: 1.5rem;
  --rafii-space-8: 2rem;
  --rafii-space-10: 2.5rem;
  --rafii-space-12: 3rem;
  --rafii-space-16: 4rem;

  --rafii-radius-micro: .5rem;
  --rafii-radius-control: .75rem;
  --rafii-radius-card: 1.25rem;
  --rafii-radius-dialog: 1.75rem;
  --rafii-radius-mobile-dialog: 1.5rem;
  --rafii-radius-pill: 999px;

  --rafii-control-min: 2.75rem; /* 44px at the default root size */
  --rafii-control-standard: 3rem;
  --rafii-control-hero: 3.5rem;
  --rafii-blur-surface: 24px;
  --rafii-blur-dialog: 40px;
  --rafii-blur-scrim: 12px;

  --rafii-ease-ui: cubic-bezier(.2, .8, .2, 1);
  --rafii-ease-soft: cubic-bezier(.22, 1, .36, 1);
  --rafii-ease-phone: cubic-bezier(.22, .78, .22, 1);
  --rafii-time-feedback: 200ms;
  --rafii-time-view: 320ms;
  --rafii-time-swap: 430ms;
  --rafii-time-lens: 440ms;
  --rafii-time-disclosure: 480ms;
  --rafii-time-phone: 560ms;
}

:root[data-appearance="light"] {
  color-scheme: light;
  --rafii-bg: oklch(.99 0 0);
  --rafii-text-primary: #000000;
  --rafii-text-secondary: #626262;
  --rafii-text-tertiary: #777777;
  --rafii-panel-rgb: 245 245 245;
  --rafii-highlight-rgb: 0 0 0;
  --rafii-action-bg: #000000;
  --rafii-action-fg: #ffffff;
  --rafii-action-fill:
    linear-gradient(130deg, #343434, #000 65%, #303030);
  --rafii-surface-glass:
    linear-gradient(135deg, #fff9, #ffffff45 50%, #eeeeee55);
  --rafii-surface-selected:
    linear-gradient(140deg, #fff, #ddd8);
  --rafii-surface-elevated:
    linear-gradient(135deg, #fffffff2, #ecececef);
  --rafii-surface-solid-fallback: #f0f0f0;
  --rafii-shadow-glass:
    0 12px 28px -19px #0005,
    inset 0 9px 22px -19px #fff;
  --rafii-shadow-dialog: 0 30px 100px #0003;
}

.rafii-app {
  font-family: var(--rafii-font-ui);
  color: var(--rafii-text-primary);
  background: var(--rafii-bg);
  line-height: var(--rafii-leading-body);
}

.rafii-surface {
  border: 0;
  border-radius: var(--rafii-radius-card);
  padding: var(--rafii-space-6);
  background: var(--rafii-surface-glass);
  box-shadow: var(--rafii-shadow-glass);
  backdrop-filter: blur(var(--rafii-blur-surface));
  -webkit-backdrop-filter: blur(var(--rafii-blur-surface));
}

.rafii-surface[data-material="quiet"] {
  background: var(--rafii-surface-quiet);
  box-shadow: none;
  backdrop-filter: none;
  -webkit-backdrop-filter: none;
}

.rafii-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--rafii-space-2);
  min-block-size: var(--rafii-control-standard);
  padding-inline: var(--rafii-space-4);
  border: 0;
  border-radius: var(--rafii-radius-control);
  font: inherit;
  font-size: var(--rafii-text-control);
  color: var(--rafii-text-primary);
  background: var(--rafii-surface-glass);
  cursor: pointer;
  transition:
    background var(--rafii-time-feedback),
    transform var(--rafii-time-feedback) var(--rafii-ease-ui);
}

.rafii-button[data-variant="primary"] {
  color: var(--rafii-action-fg);
  background: var(--rafii-action-fill);
}

.rafii-button:disabled {
  opacity: .45;
  cursor: not-allowed;
  transform: none;
}

.rafii-icon-button {
  min-inline-size: var(--rafii-control-min);
  min-block-size: var(--rafii-control-min);
  aspect-ratio: 1;
  padding: 0;
  border-radius: 50%;
}

.rafii-field {
  display: grid;
  gap: var(--rafii-space-2);
  min-inline-size: 0;
}

.rafii-input,
.rafii-select {
  box-sizing: border-box;
  inline-size: 100%;
  min-inline-size: 0;
  min-block-size: var(--rafii-control-standard);
  padding-inline: var(--rafii-space-3);
  border: 0;
  border-radius: var(--rafii-radius-control);
  background: rgb(var(--rafii-highlight-rgb) / .065);
  color: var(--rafii-text-primary);
  font: inherit;
  font-size: 1rem;
}

.rafii-select {
  appearance: none;
  -webkit-appearance: none;
  padding-inline-end: 2.5rem;
  /* Render a separate, noninteractive chevron in the field wrapper. */
}

.rafii-app :is(button, a, input, textarea, select):focus-visible {
  outline: 2px solid var(--rafii-text-primary);
  outline-offset: 3px;
}

.rafii-dialog-layout {
  display: flex;
  flex-direction: column;
  max-block-size: 94dvh;
  overflow: hidden;
  border-radius: var(--rafii-radius-dialog);
}

.rafii-dialog-body {
  flex: 1;
  min-block-size: 0;
  overflow: auto;
  overscroll-behavior: contain;
}

@supports not ((backdrop-filter: blur(1px)) or
               (-webkit-backdrop-filter: blur(1px))) {
  .rafii-surface {
    background: var(--rafii-surface-solid-fallback);
  }
}

/* Intentional reduced-effects option; an app-wide extension. */
.rafii-app[data-effects="reduced"] .rafii-surface {
  background: var(--rafii-surface-solid-fallback);
  backdrop-filter: none;
  -webkit-backdrop-filter: none;
}

@media (prefers-reduced-motion: reduce) {
  .rafii-app .rafii-decorative-motion {
    animation: none !important;
  }
  .rafii-app .rafii-spatial-motion {
    transition: none !important;
  }
}
```

The reduced-motion CSS above is only the styling half of the contract. JavaScript-driven Web Animations API transitions must also consult the shared motion preference and finish/cancel cleanly. Similarly, CSS classes alone do not implement focus trapping, dialog semantics, persistence, validation, or request state.

---

## 26. Migration and rollout

### 26.1 Begin with an inventory, not a rewrite

Inspect existing routes, shared components, tokens, authentication, data loading, selected state, localization, and user permissions. Record which components already implement the v8 behavior and which only resemble it visually.

Do not overwrite unrelated local work, replace the UI framework, or redesign an already-approved flow just to standardize a corner radius.

### 26.2 Recommended sequence

**Phase 1 — Foundations:** establish semantic tokens, fonts/fallbacks, surface recipes, basic controls, focus styles and theme behavior. Build a reference screen with the most common states.

**Phase 2 — Shared shell:** migrate navigation and topbar without changing routes or behavior. Confirm mobile safe areas, selected states and keyboard access.

**Phase 3 — Core workflow:** align Create/editor, content/channel/model/language selectors, previews and Queue. Test data preservation before polishing less frequent pages.

**Phase 4 — Operational pages:** Calendar, Inbox, Channels, Sources and Settings, using their appropriate archetypes.

**Phase 5 — Knowledge and planning:** Voice, Brand Brain, Campaign Planner, Suggestions and Analytics if present.

**Phase 6 — Edge states and hardening:** loading, empty, partial error, unavailable capability, offline, long content, translations, reduced motion and physical-device testing.

### 26.3 Migration rules

Use a component-by-component transition rather than a global CSS selector that changes every existing `button` overnight. Keep compatibility aliases temporarily. Remove obsolete styles once a component is migrated; do not leave three conflicting theme definitions in place.

Preserve behavior under visual changes. A filter redesign should not change query semantics. A phone animation repair should not alter generation channels. A new button label should not change the action without an explicit workflow decision.

### 26.4 Per-page completion evidence

For each page, produce: the actual route/component touched; shared components reused; before/after desktop and mobile captures; dark/light states; interaction checks; data/permission checks; and remaining limitations.

Do not declare “all pages updated” from one attractive homepage screenshot. Track page coverage explicitly.

---

## 27. Design QA and acceptance criteria

### 27.1 Visual identity checklist

- [ ] Rafii-owned chrome is monochrome in both themes.
- [ ] No purple/neon accents or page-specific palette has been introduced.
- [ ] Serif accent is intentional and limited; controls remain clear sans-serif.
- [ ] Glass surfaces explain grouping/depth rather than enclosing every element.
- [ ] Resting controls are borderless; keyboard focus remains visible.
- [ ] Radius, spacing, icon weight and control height follow shared roles.
- [ ] One dominant commitment action is clear in the active task.
- [ ] View controls, filters and task settings are not duplicated.

### 27.2 Behavior checklist

- [ ] Search/filter/view switches preserve content and intentional selection.
- [ ] Apply/Cancel versus immediately applied view filters are consistent.
- [ ] Theme switching does not reset work or route state.
- [ ] Back/forward, refresh and deep links preserve the expected page.
- [ ] Modal focus is contained and restored logically.
- [ ] Escape closes the deepest active layer first.
- [ ] Information controls do not accidentally select their parent item.
- [ ] Rapid transitions end in the last requested state with no stale layers.
- [ ] Swipe has a non-gesture alternative and does not hijack vertical scrolling.
- [ ] State labels describe actual completed operations, not animation timing.

### 27.3 Responsive matrix

Use the following as a **standardized test matrix**, not a claim that every dimension was tested in the original design extraction:

| Width / height | Purpose |
|---|---|
| 320 × 740 | Narrow-phone labels, overlays and control grouping |
| 375 × 812 | Common compact-phone composition |
| 390 × 844 | V8 mobile reference comparison |
| 430 × 932 | Larger mobile and readable detail views |
| 768 × 1024 | Tablet stacking and gallery behavior |
| 1024 × 768 | Shorter landscape workspaces |
| 1440 × 1000 | V8 desktop reference comparison |
| 1920 × 1080 | Maximum widths and excessive whitespace |

Repeat relevant states in dark/light and reduced motion. Also test short landscape screens and a real mobile keyboard. Use actual viewports, not an image resized to different dimensions.

### 27.4 Content-stress matrix

Test no data, one item, a long list, long titles, long native language names, mixed scripts, emoji in user content, multiline descriptions, missing thumbnail, broken upload, empty search, failed sync, permission denied, partial result, many selected channels, and a long edited draft.

Important values should wrap or remain inspectable. Ellipsis must not hide the only available account identifier, deadline, role, or selected setting.

### 27.5 Asset and motion validation

Every new semantic asset has metadata, an accessible purpose, a local or approved storage path, and a unique visual concept. Repeated SVG IDs are namespaced. Legacy fallback is explicit and is not reused for new items.

Capture the running animation or inspect real browser animation state. A static concept board is not evidence that a crossfade works. Confirm pause/offscreen behavior, reduced motion, interrupted transitions, focus and selected state during the animation.

### 27.6 Release gate

A page is ready only when visual comparison, behavior, state integrity, accessibility checks and the relevant real data flow pass. If a page is still a demo, mark it as such. Record unsupported environments and untested devices instead of claiming universal compatibility.

Do not reuse historical prototype test counts as evidence for a new implementation. Run the relevant checks against the current delivered build.

---

## 28. Anti-patterns and corrections

| Anti-pattern | Why it breaks Rafii | Correction |
|---|---|---|
| Three giant toolbars with equal weight | No clear task hierarchy | Separate task, find, view and commit |
| Colored AI cards across every page | Breaks monochrome identity | Use neutral surfaces and semantic content |
| Glass around every line of text | Depth becomes noise | Use spacing, headings and quiet sections |
| A black rectangle with gray text called “glass” | No material or hierarchy | Use controlled opacity, reflection and separation |
| Hard bright outlines on all controls | Makes the interface busy | Borderless rest state; focus/validation exceptions |
| Hiding controls behind unexplained icons | Compact but not understandable | Add labels or group within a named panel |
| Tiny 7px metadata everywhere | Prototype density becomes poor readability | Increase essential text and simplify content |
| Full-size hero on a settings/table page | Misapplies the creative homepage | Use a compact functional page header |
| Same thumbnail for every type | Removes semantic recognition | Distinct large and micro illustrations |
| Recoloring platform content as Rafii chrome | Misrepresents native appearance | Isolate destination-preview styling |
| Incoming phone animates after old phone vanished | Not a connected transition | Retain an inert outgoing layer |
| Resetting draft state on a view switch | Violates user trust | Keep content state above representation state |
| Filters silently select channels | Confuses browsing with mutation | Explicit, separate account selection |
| All models shown as equally capable | UI implies unsupported execution | Capability-aware mapping and honest limits |
| Static benchmark labelled as live personal data | Misleads the user | Show source, period, scope and missing data |
| CSS overrides duplicated per page | Identity drifts and bugs accumulate | Tokens + shared components + scoped page layouts |

---

## 29. Agent implementation brief

The following block is intended to accompany this Markdown file when assigning an application-page migration. Replace the bracketed target with the actual task. It is an implementation brief, not evidence that work has been done.

```text
Apply Rafii_Design_DNA_v8.md to [target pages/components] in the existing Rafii project.

Reference authority:
- Approved design reference: the actual Rafii prototype v8.
- Preserve the product's monochrome, borderless liquid-glass language,
  selective serif-italic editorial accents, and clear task hierarchy.
- Distinguish this document's Observed values, Standardized rules, and Extensions.

Before editing:
1. Inspect the current repository, routes, shared components, tokens and styles.
2. Identify working flows, local changes, data boundaries and permissions to preserve.
3. Map the target page to the correct layout archetype.
4. Reuse current components where their behavior is already correct.

Implement:
- One coherent shell, theme and typography system across pages.
- WHAT / FIND / VIEW / COMMIT hierarchy where a collection task warrants it.
- Labelled, grouped filters and a visible active-filter summary.
- One dominant commitment action per active task surface.
- Stable selected-state lenses and cancellable, truthful motion.
- Correct Apply/Cancel behavior and preservation of user edits.
- Native platform previews isolated from Rafii chrome.
- Local, semantic artwork and real provider marks with provenance.
- Responsive desktop/tablet/mobile behavior; no tiny-text workaround for crowding.
- Dark/light, focus, reduced motion, loading, empty, error and unsupported states.

Do not:
- Introduce a purple/neon theme or rebrand unrelated pages.
- Copy prototype sample names, counts or simulated connection states into production.
- Claim all models or platforms support a format or reasoning setting without evidence.
- Trigger publication, external writes or deployments unless explicitly authorized.
- Change unrelated business logic or replace the stack unnecessarily.
- Treat static screenshots, old test counts or one homepage as full-app completion.

Deliver:
- The actual code changes for the requested scope.
- A short mapping of reused components and any added tokens.
- Desktop/mobile and dark/light browser screenshots for representative states.
- Interaction and data-preservation test results from this build.
- Explicit remaining limitations and a file/route coverage list.
```

---

## 30. Reference measurements and sources

### 30.1 Inspected artifact

| Property | Value |
|---|---|
| Standalone file | `rafii-prototype-v8.html` |
| Source package | `rafii-prototype-v8-source.zip` |
| Bytes | 784,398 |
| SHA-256 | `7266e550f2ff83deb68d11bcc8cd7f00689da07da8e7c248b026c39d4ee20d20` |
| Browser extraction | Chromium, 1440×1000 and 390×844, dark and light |
| Runtime during inspected states | No page errors or network requests observed |
| Scope of extraction | Home, Content Library, Filters, List, Model and shared Language states |
| Unverified in this work | Physical iPhone/Safari, full production route coverage, real API/CLI/publishing behavior |

Some inherited text inside the v8 file still mentions earlier prototype versions. The **artifact hash and final CSS cascade** define this reference, not a stale visible demo badge.

### 30.2 The actual stylesheet cascade

The source loads, in order:

```text
styles.css
→ glass.css
→ phone-previews.css
→ refinement.css
→ selectors-v5.css
→ refinement-v6.css
→ library-v7.css
→ library-v8.css
```

Values found near the start of `styles.css` may be overridden. For example, the base background and original rail highlights do not define the final theme. Measure the rendered component or inspect the final matching rule before extracting a token.

### 30.3 Measured component reference table

| Component | Desktop reference | 390px mobile reference |
|---|---|---|
| Main sans-serif stack | Geist → system → Arial | Same declared stack |
| Creative hero | 49px / 1.05; regular | 43px / 1.05 |
| Creative serif fragment | Georgia stack, italic | Same role |
| Original idea input | 26px serif italic; 190px height | 25px serif italic; 170px height |
| Library width | 910px | 378px |
| Library height | 910px at a 1000px viewport height | 810.23px at an 844px viewport height |
| Library radius | 28px | 24px |
| Library heading | 29px | 25px |
| Main library tabs | 58px buttons, 16px group radius | 46px buttons |
| Search | 46px high; 14px text | 44px high; 16px text |
| View and Filters controls | 46px high | 44px high |
| Filter panel | 368px wide; 22px radius | 358px observed inner width; 20px radius |
| Category / app selects | 48px high; 16px text; 12px radius | Same |
| Library Apply | 180×48px minimum; 14px radius | 348×46px in the observed layout |
| Model selected capsule | 60px high; 20px label | Responsive to available space |
| Provider rail item | 51×51px; 17px lens radius | Compact responsive equivalent |
| Model name / description | 18px / 12px in the observed row | Component-responsive |
| Reasoning track | 48px high; 40px inset lens | Compact responsive equivalent |

The full computed-style record is included as `rafii-design-reference/v8-measured-reference.json` in the optional reference package. The record includes declared stacks and computed CSS, not a guarantee that an identical physical font file rendered on all operating systems.

### 30.4 Visual references

These images are actual browser captures of the inspected v8 file. They are reference evidence, not new design proposals.

**Creative studio, dark**

![Rafii v8 desktop creative workspace](rafii-design-reference/desktop-dark-home.png)

**Content Library, mobile**

![Rafii v8 compact mobile library hierarchy](rafii-design-reference/mobile-dark-library.png)

**Nested Filters surface**

![Rafii v8 mobile filter panel](rafii-design-reference/mobile-dark-filters.png)

**Light appearance**

![Rafii v8 desktop light library](rafii-design-reference/desktop-light-library.png)

**Model selector**

![Rafii v8 model selector](rafii-design-reference/mobile-dark-model.png)

**Language configuration**

![Rafii v8 shared-language configuration](rafii-design-reference/mobile-dark-language.png)

The Markdown remains usable on its own; the optional ZIP supplies the relative image files and measured reference JSON for an offline, portable handoff.

### 30.5 Source map and standards notes

Source notes use file path + selector/function anchors because the prototype's CSS is partially minified. This is more reliable than assuming one declaration per source line.

[^v8-reference]: Inspected user library artifacts: `rafii-prototype-v8.html`, 784,398 bytes, SHA-256 as listed above; `rafii-prototype-v8-source.zip`, whose `index.html` matches the standalone bytes. The source archive's `README.md`, `VALIDATION.md`, and `PROVENANCE.md` explain its demo and test boundaries. The inherited validation report was consulted but its historical test counts are not presented as a fresh application-wide audit in this guide.

[^measured]: Fresh Chromium extraction performed for this document: `rafii-design-reference/v8-measured-reference.json`. States were rendered with the exact bundled HTML via Playwright `page.set_content`, with reduced-motion preference during geometry capture. Coordinates are CSS pixels and may vary with fonts, browser, content, and viewport.

[^v8-theme]: `src/glass.css`, root custom properties at the beginning of the file; `:root[data-appearance=light]`; `.composer`, `.morph-dialog`, `.generate-button`, `.mobile-nav`; `@supports not (...)` fallback. Later component files may override individual material details.

[^v8-type]: `src/styles.css`, `:root`, `body`, `h1`, `em`; `src/glass.css`, root font stack, `.greeting h1`, `#idea`, mobile breakpoints; `src/library-v8.css`, `.dialog-heading h2`, select/input rules and summary labels. All font sizes in the measured tables come from resolved computed styles or explicit final rules.

[^v8-shell]: `src/styles.css`, `.rail`, `.app-shell`, `.topbar`, `main`, `.mobile-nav`; `src/glass.css`, `.topbar`, `.workspace-grid`, `.app-shell` and media-query overrides. The Create/Calendar/Queue/Inbox navigation comes from `src/index.html`.

[^v8-library]: `src/library-v8.css`, particularly the WHAT/FIND/VIEW/COMMIT comment, `.library-workbar`, `.view-switch`, `.library-filter-trigger`, `.library-filter-layer`, `.library-filter-panel`, `.library-field select`, `.taxonomy-footer`, and the 800px/600px/359px media rules. Behavior: `openLibraryFilters`, `closeLibraryFilters`, `renderLibraryFilterSummary`, and `wireTaxonomy` in `src/app.js`.

[^v8-controls]: `src/glass.css`, primary/secondary/icon-button styles; `src/refinement.css`, the three independent settings controls; `src/library-v8.css`, explicit 44/46/48px control rules. Baseline `button:focus-visible` and form focus styles are preserved across the theme layer.

[^v8-art]: `src/taxonomy-data.js/json`, `src/library-data.js/json`, `src/assets/thumbnails/` and `src/assets/glyphs/`; renderers `libraryArt`, `libraryMini`, `taxonomyCard`, `pairingCard`, and `observeArt` in `src/app.js`. The inherited provenance documents record prior artwork and logo sources.

[^v8-library-motion]: `src/library-v7.css`, `.view-lens`, `.library-tooltip`, `.library-evidence`, `.glyph-motion`, `.art-motif`, `.art-accent`, their keyframes and pause/reduced-motion rules; `swapLibrary` and tooltip functions in `src/app.js`.

[^v8-motion]: `src/ui-motion.js` for 430ms swaps and 480ms height transitions; `src/refinement-v6.css` for provider/reasoning/tab lenses and bars; `src/app.js` for dialog, filter and library timings. Numbers describe this snapshot, not a benchmark for actual device smoothness.

[^v8-phone]: `src/phone-motion.js`, `createPhoneDeck`, `pose`, keyed rendering and cancellation; `src/swipe.js` for input arbitration; `src/phone-previews.js/css` and `src/refinement.css` for frame and responsive layout. Native mockup UI is not a live third-party embed.

[^v8-locale]: `src/locale-data.js/json`, `src/locales.js`, `src/selectors-v5.css`, and language functions in `src/app.js`. The source provenance describes the inherited locale reconstruction and non-connected translation/model behavior.

[^w3c-target]: W3C WAI, **Understanding SC 2.5.8: Target Size (Minimum)**, WCAG 2.2 AA. The standard's minimum/exception model differs from this guide's stronger 44px product target. Reference checked 2026-09-22: <https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum>.

[^w3c-contrast]: W3C WAI, **Understanding SC 1.4.3: Contrast (Minimum)**. Normal-text and large-text thresholds, with applicability/exceptions. Reference checked 2026-09-22: <https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html>.

[^w3c-nontext]: W3C WAI, **Understanding SC 1.4.11: Non-text Contrast**. Applies to covered UI and graphical information, not all decorative pixels. Reference checked 2026-09-22: <https://www.w3.org/WAI/WCAG22/Understanding/non-text-contrast.html>.

[^w3c-dialog]: W3C WAI ARIA Authoring Practices, **Dialog (Modal) Pattern**. Modal focus containment, initial focus, Escape and logical return. Reference checked 2026-09-22: <https://www.w3.org/WAI/ARIA/apg/patterns/dialog-modal/>.

[^mdn-motion]: MDN, **prefers-reduced-motion**. Browser media feature reflecting the reduced-motion preference. Reference checked 2026-09-22: <https://developer.mozilla.org/en-US/docs/Web/CSS/@media/prefers-reduced-motion>.

[^mdn-backdrop]: MDN, **backdrop-filter**. Describes filtering behind translucent elements and the relationship to backdrop content. Reference checked 2026-09-22: <https://developer.mozilla.org/en-US/docs/Web/CSS/backdrop-filter>.

---

## Final decision rule

When a page feels like Rafii, the user should not notice the design system first. They should notice that the page is calm, the choices are organized, the work is safe, and the next step is obvious. The serif accent, neutral glass, and connected motion then make that clarity feel unmistakably Rafii.
