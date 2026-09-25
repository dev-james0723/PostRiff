# English pattern catalogue

Each entry gives the detector id, what to watch for, the fix and when to keep
the original. Examples use only information that is already in the "before"
text. An "after" never gains a fact, a name or a number. Judge the entries in
clusters: one hit on its own is rarely a reason to edit.

## Content

**en.inflated_significance, en.broader_trends.** Watch for "stands as a
testament", "marks a pivotal moment", "plays a vital role", "evolving
landscape", "in today's fast-paced world". Fix: state the plain fact, or cut the
claim. Keep a significance claim the owner makes and can support.
"The café opened in 2019, marking a pivotal moment for the neighbourhood."
becomes "The café opened in 2019."

**en.notability_claims.** Watch for "featured in outlets such as...", "active
social media presence". Fix: keep one specific, supplied reference, or drop the
list. Never add outlets.

**en.ing_tail_analysis.** Watch for a trailing ", highlighting/reflecting/
showcasing/ensuring..." that adds unsupported meaning. Fix: end the sentence
before the tail. Keep the tail when it states a sourced reason or result.

**en.promotional.** Watch for nestled, in the heart of, boasts, breathtaking,
vibrant, world-class, game-changer, cutting-edge. Fix: keep the features that
were actually supplied. A subjective view stays labelled as a view. Keep any
match that is part of an approved brand term.

**en.vague_attribution.** Watch for "experts believe", "studies show", "it is
widely believed". Fix: remove the empty praise around it. Keep the vague
attribution and its uncertainty. Never replace it with a named institution, a
year or a statistic. Ask for a source in the note.

**en.challenges_formula.** Watch for "Despite its challenges... continues to
thrive", "Future outlook". Fix: keep the real problems, plans and dates. Cut the
formula.

**en.speculative_gap_fill, en.cutoff_disclaimer.** Watch for "details are
limited", "maintains a low profile", "as of my last training update". Fix: say
plainly what is not known, or cut the line. A guess stays a guess. A real "as of
2026-09-01" that scopes the data stays.

## Language

**AI vocabulary (list in `humanizer_patterns.json`).** Watch for delve,
tapestry, testament, pivotal, crucial, intricate, showcase, foster, seamless,
leverage, elevate, unlock, robust, moreover, additionally. Fix: act only on
clusters, or on a word that is vague in its context. Formal or technical words
are fine ("robust statistics").

**en.copula_avoidance.** Watch for "serves as", "stands as", "boasts over 40
seats". Fix: use is, has or offers. Keep the comparator ("over 40" stays "over
40").

**en.negative_parallelism, en.tailing_negation.** Watch for "It's not just X;
it's Y", "not only... but also", ", no guessing." Fix: state the positive claim
directly, or write the negation as a full clause. Keep it when the negated part
corrects a misunderstanding the source actually states. Never edit inside a
quotation.

**en.rule_of_three_abstract.** Watch for triads of abstract nouns or buzz
adjectives ("innovation, inspiration and insights"). Fix: keep the concrete items
and drop the filler triad. Three real features stay three.

**Synonym cycling (no regex).** Watch for "the protagonist... the main
character... the central figure". Fix: repeat the clearest noun or use a pronoun.
Keep approved terms consistent.

**en.false_range.** Watch for "from X to Y, from A to B", where X and Y are not
on a scale. Fix: list the actual topics.

**en.subjectless_fragment.** Watch for "No configuration needed." Fix: add the
subject when the actor is known ("You do not need a configuration file."). Keep
the fragment when it is an approved UI-copy style.

## Style

**Dash density (metric, no ban).** Watch for dashes above the density clue, or
a dash used as a suspense reveal. Fix: use a full sentence, a comma or a colon
for the reveal. Keep dashes in the owner's voice and ordinary asides.

**en.bold_overuse, en.inline_header_list.** Watch for bold on every phrase, or
"- **Speed:** Speed improved". Fix: keep the bold that helps scanning or warns.
Turn a bold-colon list into a sentence only when the list repeats its own
headers. Never drop an item.

**en.title_case_heading.** Fix: use the heading case the platform or house style
requires. In files, keep the heading text and anchors unless the brief allows
changes.

**en.emoji_label, en.hashtag_block.** Watch for emoji used as labels on every
line, and blocks of 6 or more hashtags. Fix: follow the approved emoji and
hashtag habits and the platform lint. Do not add emoji or hashtags.

**en.curly_double_quotes.** A weak clue in English only. It never applies to
Chinese text.

## Communication residue

**en.res.\*, en.sycophancy.** Watch for "Great question!", "Certainly!", "I
hope this helps", "Let me know if you'd like...", "Here is a revised caption",
"As an AI". Fix: delete the framing and keep the content inside it. Keep real
greetings and sign-offs in emails and replies.

**en.res.meta_rewrite.** "Here's a more natural version" and similar are
residue from this stage. They must never appear in the final copy.

**en.res.placeholder, en.res.citation_artifact.** Watch for `[insert link]`,
`{{name}}`, `:contentReference[oaicite:0]`, `【4†source】`. Fix: never fill a slot
with invented content. Leave it and raise a warning, or use the supplied value.
Delete citation markup, keep the claim, and record that its source needs
checking.

**en.announce_formula, en.engagement_bait.** Watch for "We're thrilled to
announce", "Agree? Drop a comment below". Fix: never add them. If the owner's
draft or brief contains them, they are voice or an approved CTA, so keep them
unless they sit in a cluster the owner asked to clean.

## Filler and hedging

**en.filler.** Examples: "in order to" becomes "to"; "due to the fact that"
becomes "because"; "has the ability to" becomes "can"; "it is important to note
that" is deleted.

**en.stacked_hedge.** "could potentially reduce" becomes "may reduce". Keep one
hedge of the same strength. "Early testing suggests... may" keeps both words,
because they carry different information: the evidence and the degree.

**en.generic_conclusion.** Watch for "The future looks bright", "a step in the
right direction". Fix: end on the last specific point, or on the supplied next
step. Never invent a plan.

**en.hyphen_predicate.** A weak clue ("the report is high-quality"). Change it
only when house style asks.

**en.authority_trope.** Watch for "At its core", "The real question is", "The
truth is". Fix: state the point directly.

**en.sign.\*.** Watch for "Let's dive in", "Here's what you need to know",
"Read on to find out", "Unpopular opinion:". Fix: start with the content.
Platform hooks the owner approved stay.

**en.fragmented_header.** Watch for a heading followed by a line that restates
it. Fix: delete the restatement. Keep a line that adds a condition or a number.

**en.diff_anchored.** Watch for "was added to replace the previous approach".
Fix: describe the current state. Changelogs and release notes keep before and
after.

**en.staccato.** Watch for runs of short dramatic fragments. Fix: merge them into
one clear sentence that keeps every fact. One short emphatic line is fine.

**en.aphorism.** Watch for "X is the language of Y", "becomes a trap". Fix:
state the concrete claim the source gives. If there is none, cut the line.
Never guess what it meant.

**en.rhetorical_opener.** Watch for a standalone "Honestly?", "Look,", "Here's
the thing:". Fix: say the point. Keep casual words mid-sentence.

## Worked example

Before:

> We're excited to share that Smart Sync, our game-changing feature, now serves
> as the backbone of seamless collaboration — keeping drafts aligned across 3
> workspaces, ensuring nothing falls through the cracks. It may take up to 5
> minutes for edits to appear on mobile. Let us know your thoughts!

After, with "Smart Sync" approved, no approved CTA and a plain voice:

> Smart Sync keeps drafts aligned across 3 workspaces. Edits may take up to 5
> minutes to appear on mobile.

The edit removed the added excitement, the promotional terms, the fake-depth
tail and the unapproved engagement bait. It kept the brand term, the number, the
hedge ("may"), the limit ("up to 5 minutes") and the platform scope. If the
brief had approved "Let us know your thoughts!", that line would stay.
