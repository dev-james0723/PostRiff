# Note Garden — Research receipt

Task `ao-rafii-20261031-bf90f0` · role 14-research-evaluation · researched 2026-10-30/31 (UTC).
Status labels: **VERIFIED** = read from the primary source or the GitHub API in this session; **SECONDARY** = taken from a
reputable secondary summary, primary text not opened; **UNVERIFIED** = plausible but not confirmed.

## 1. Questions answered

1. In what order should ages 6–10 meet pitch, staff and rhythm concepts?
2. What child-UX rules should shape feedback, pacing and touch input?
3. Which accessibility and privacy rules bind a public children's page?
4. What can we learn from existing open music-learning projects, and what may we legally reuse? (Answer: ideas only.)

## 2. Pedagogy sources

| Source | URL | Status | Used for |
|---|---|---|---|
| Kodály method overview | https://en.wikipedia.org/wiki/Kod%C3%A1ly_method | SECONDARY | Sound before symbol; child-developmental sequence; so–mi (minor 3rd) as the first sung interval |
| Wichita State Univ., *A Kodály Sequence* (2009) | https://wichita.edu/academics/fine_arts/music/kodaly/documents/G_2009_Wichita_A_KODALY_SEQUENCE_FINAL.pdf | SECONDARY (search excerpt) | Kindergarten: high/low and steady beat first. Grade 1: *ta* / *ti-ti* (quarter / paired eighths) |
| Houlahan & Tacka, *J. Music Theory Pedagogy* | https://journals.ou.edu/jmtp/article/download/815/1656/1646 | SECONDARY | Unit-by-unit sequencing: prepare → present → practise |
| ABRSM Grade 1 theory content (as reproduced by mymusictheory.com) | https://mymusictheory.com/tag/abrsm1/ | SECONDARY | Grade 1 note values are semibreve → semiquaver; US names accepted. Our L3 is a **pre-Grade-1** subset |
| Mueller & Dweck (1998), *Praise for intelligence can undermine children's motivation* | https://www.columbia.edu/cu/psychology/courses/3615/Readings/Mueller_Dweck.pdf | VERIFIED (paper exists; findings via abstract) | Praise the process ("You listened carefully!"), never the person ("You're so smart!") |
| Open Music Theory v2 / Hutchinson, *Music Theory for the 21st-Century Classroom* | https://viva.pressbooks.pub/openmusictheory/ · https://musictheory.pugetsound.edu/mt21c/ | UNVERIFIED this session (known open textbooks) | Staff positions, the step/skip definition (2nd vs 3rd and wider), beat terminology |

**Synthesis.** All the sources agree on three principles: experience before notation, one new concept at a time, and
pitch direction plus steady beat as the first concepts. That supports the default order, with one change. L4 builds on
the staff work in L2 rather than on L1 hearing alone. Two orderings were weighed:

- **Adopted:** L1 high/low (ear only) → L2 staff names → L3 note values/beats → L4 **steps vs skips** (ear plus staff).
  Steps and skips joins the ear skill from L1 with the reading skill from L2. It is also the first Kodály-style melodic
  concept after so–mi.
- **Rejected for L4:** "same or different". It is developmentally earlier than L1, so placing it fourth would make the
  last level the easiest. It survives only as **two warm-up questions inside L1** (see SPEC §L1). This is the only
  change to the default structure, and the level count, order and topic slots are unchanged.

## 3. Child UX, accessibility, privacy, hearing

| Source | URL | Status | Rule adopted |
|---|---|---|---|
| NN/g, *Designing for Children* (ages 3–12, three age bands) | https://www.nngroup.com/videos/designing-children/ | SECONDARY | Ages 6–8 need large targets and short text, and read slowly. Ages 9–12 dislike babyish styling, so the visuals stay friendly but not toddler-like |
| Friedman's guide via secondary summary: 18–19 px text, 75 px targets | https://ua.linkedin.com/in/alinahalushka | UNVERIFIED | Used only as a sanity check. We set 64 px minimum targets (72 px on phones) and ≥ 20 px text |
| W3C *Understanding SC 2.5.8 Target Size (Minimum)* | https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html | VERIFIED | AA 24×24 CSS px; AAA (2.5.5) 44×44. We exceed AAA |
| WCAG 2.2 (2.2.1 Timing, 2.3.1 Flashes, 2.3.3 Animation from Interactions, 1.4.3/1.4.11 Contrast, 1.4.1 Use of Color, 2.4.7/2.4.13 Focus) | https://www.w3.org/TR/WCAG22/ | VERIFIED (known normative text) | Untimed; no flashing; reduced motion respected; colour never the only cue |
| Okabe & Ito colour-universal palette | https://jfly.uni-koeln.de/color/ · hex list: https://conceptviz.app/blog/okabe-ito-palette-hex-codes-complete-reference | SECONDARY | Sky blue `#56B4E9`, orange `#E69F00` and blue `#0072B2` keep the high/low pair distinguishable under protanopia, deuteranopia and tritanopia |
| ICO *Age Appropriate Design Code* (15 standards: data minimisation, high-privacy defaults, no nudging) | https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/childrens-information/childrens-code-guidance-and-resources/ · summary https://www.esrb.org/privacy-certified-blog/the-icos-age-appropriate-design-code-default-settings-and-data-minimization/ | SECONDARY | Collect nothing; no nudges to stay longer; no streaks or pressure loops |
| FTC COPPA Rule 2025 amendments (persistent identifiers are personal information) | https://www.insideprivacy.com/united-states/federal-trade-commission/ftc-adopts-final-coppa-rule/ | SECONDARY | No cookies or IDs set by the game; localStorage holds only non-identifying progress and never leaves the device |
| WHO–ITU H.870 *Safe listening devices and systems* | https://www.who.int/publications/i/item/9789241515276 | SECONDARY | Children's exposure reference is 75 dB(A) for 40 h/week. A web page cannot measure SPL, so we cap digital gain and keep sound short and quiet (DESIGN §Audio) |

## 4. Existing open music-learning projects (patterns only)

Licences come from the GitHub API (`gh api repos/<r>`), queried 2026-10-31.

| Project | Repo @ commit (date) | Licence | Maintenance | Borrowed (idea only) | Rejected |
|---|---|---|---|---|---|
| **Chrome Music Lab** (Google Creative Lab) | https://github.com/googlecreativelab/chrome-music-lab @ `e54bb41` (2022-12-16) | Apache-2.0 (LICENSE file read) | **Archived**, read-only | Wordless, colour-plus-shape interaction (*Song Maker*, *Rhythm* monsters); sound on every tap; big friendly characters; no accounts | Its code, sounds and art (we borrow nothing); open-ended sandbox with no goals (we need graded questions); microphone input (privacy) |
| **Music Blocks** (Sugar Labs) | https://github.com/sugarlabs/musicblocks @ `31d6bf6` (2026-10-30) | AGPL-3.0 | Active | Learning by constructing and hearing; "listen again" as a first-class action | Any code, because AGPL would oblige us to release Rafii source; block-programming UI is too complex for ages 6–8 |
| **LenMus Phonascus** | https://github.com/lenmus/lenmus @ `113787f` (2025-09-15) | GPL-3.0 | Low activity | Exercise types: "name the note on the staff", "how many beats?", interval comparison; configurable note range | Code (GPL); dense desktop UI; adult tone |
| **OpenEar** | https://github.com/ShacharHarshuv/open-ear @ `e17c6f7` (2026-09-24) | **None declared** (API `license: null`) → all rights reserved | Active | "Replay" button pattern; reveal the answer after mistakes | Everything else. With no licence, even close imitation is risky |

Security advisories were not relevant because nothing was installed or imported. Status: NOT_RUN.

## 5. Decisions

- **Strategy D (focused implementation)** on the existing stack: React 19, Tailwind 4, inline SVG, Web Audio. No new
  dependencies. Every candidate above is either archived, copyleft or unlicensed, so none can be used as code.
- **No audio samples, fonts or images** come from any candidate. All sound is synthesised and all art is hand-authored
  SVG or CSS.
- Recorded open items are in SPEC §Assumptions.
