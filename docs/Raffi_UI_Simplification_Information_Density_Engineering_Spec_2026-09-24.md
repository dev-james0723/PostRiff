# Raffi UI Simplification & Information Density Reduction
## Engineering Specification

**Project:** Raffi  
**Scope:** Entire application  
**Priority:** High  
**Date:** 2026-09-24

## 1. Problem

Raffi currently explains too much.

Many screens expose information that is technically correct but does not help the user complete the task in front of them.

Example from **Usage & Plan**:

- Current plan: Trial
- $0
- Nothing converts automatically
- 10 days left, ends October 3rd, 2026
- Draft state exportable
- Billing is not enabled on this deployment yet

Every individual statement may be true, but together they create unnecessary cognitive load.

The user should not need to read six facts to understand:

> I am on a free trial, and I have 10 days left.

The product currently behaves too much like documentation. It should behave like an application.

## 2. Product Direction

Raffi should feel:
- calm
- obvious
- lightweight
- fast
- confident
- conversational
- visually uncluttered

The UI should not continuously explain itself.

A user should normally be able to understand a screen by looking at:
1. the title
2. the current state
3. the primary action

Everything else should appear only when it becomes relevant.

## 3. Core Principle

### Show only what the user needs **right now**.

Every visible piece of text must answer at least one of these questions:
- What is this?
- What is happening?
- What do I need to do?
- What happens if I do it?
- Is there an important exception I must know?

If a piece of text does none of these things, strongly consider removing it.

## 4. Information Hierarchy

Every screen should use three information levels.

### Level 1 — Always visible
Only information necessary to understand and use the screen.

Examples:
> Trial · 10 days left

> 4 posts scheduled

> Instagram connected

> Draft saved

> 3 suggestions

### Level 2 — Contextual
Show only when the user interacts with the relevant control.

Possible surfaces:
- tooltip
- popover
- expandable details
- secondary modal
- inline explanation after an error
- contextual help

Instead of permanently showing:
> Billing is not enabled on this deployment yet.

Show nothing until the user tries to manage billing. Then:
> Billing isn’t available yet.

### Level 3 — Technical / administrative detail
Do not expose this in normal product UI unless explicitly requested.

Examples:
- deployment state
- internal synchronization details
- API implementation details
- backend terminology
- database state
- developer-oriented explanations
- architecture limitations

These belong in developer tools, logs, diagnostics, admin tools, or documentation, not normal customer-facing screens.

## 5. Progressive Disclosure

Raffi should adopt **progressive disclosure** throughout the application.

Default UI:
> Simple.

Expanded UI:
> Detailed when requested.

Do not show advanced information merely because Raffi has access to it.

Prefer **Connected** over a sentence explaining that the account is connected.

Prefer **Draft saved** over a sentence explaining how draft persistence works.

Prefer **10 days left** over a sentence repeating the trial end date.

Exact dates can be available in details if useful.

## 6. Action-First UI

Whenever possible, structure information around actions rather than explanation.

Bad:
> Your Brand Brain allows Raffi to understand your business information. You can add information about your products, audience, tone and brand identity below.

Better:

**Brand Brain**

> Add what Raffi should know.

`Add knowledge`

Better still, if context makes the description unnecessary:

**Brand Brain**

`Add knowledge`

## 7. Remove Redundant Labels

Avoid repeating information already communicated visually.

Bad:
> Current Plan  
> Trial

Better:
> Trial

Bad:
> Current connection status  
> Connected

Better:
> Connected

Bad:
> Number of scheduled posts  
> 6 scheduled posts

Better:
> 6 scheduled

## 8. Copy Budget

Use these as guidelines rather than rigid technical limits.

### Navigation
Prefer **1–2 words**.

Examples:
- Home
- Create
- Calendar
- Campaigns
- Brand
- Analytics
- Settings

### Buttons
Prefer **1–3 words**.

Examples:
- Create post
- Publish
- Schedule
- Connect
- Export
- Try again
- Add account

Avoid sentence-length button labels.

### Helper text
Usually **one short sentence**.

If a description becomes longer than roughly 10–15 words, question whether the text belongs there at all.

### Cards
A card should generally contain:
- title
- one important value/state
- optional action

Not a paragraph.

### Empty states
Preferred structure:

**Short title**

One short explanation if necessary.

One primary action.

Example:

**No campaigns yet**

`Create campaign`

Do not write an essay explaining campaigns.

## 9. Usage & Plan Redesign

This screen should be radically simplified.

### Current experience
The user may see:
- Current plan: Trial
- $0
- Nothing converts automatically
- 10 days left
- Ends October 3rd, 2026
- Draft state exportable
- Billing is not enabled on this deployment yet

This is too much.

### Proposed default state

### Trial

**10 days left**

`Manage plan`

That may be enough.

If the product does not currently support plan management:

### Trial

**10 days left**

No additional explanation is necessary.

### Optional detailed state
If the user opens plan details:

### Trial
$0

Ends Oct 3

`Export data`

Only display the export action if exporting is genuinely relevant here.

### Remove from default UI

#### “Nothing converts automatically”
Remove.

If automatic conversion is not a real user concern, this statement creates a concern that did not previously exist.

If legally or commercially necessary, place the information in billing confirmation or plan terms.

#### “Draft state exportable”
Remove from this screen.

Export belongs near:
- Export
- Data
- Account
- Backup
- Workspace settings

A capability should appear where a user would look for that capability.

#### “Billing is not enabled on this deployment yet”
Remove from normal UI.

This is developer language.

If a user attempts billing:
> Billing isn’t available yet.

That is enough.

Never expose the concept of “deployment” to normal users.

## 10. Remove Implementation Language

Run a full audit for terms that expose Raffi's internal implementation.

Examples to look for:
- deployment
- backend
- API
- provider
- database
- sync state
- model
- environment
- production
- staging
- record
- schema
- payload
- internal state

These terms may be valid in developer/admin interfaces.

They generally should not appear in customer-facing Raffi UI.

Translate implementation state into user state.

Bad:
> Provider authentication token expired.

Better:
> Instagram disconnected.

`Reconnect`

## 11. Error Messages

Simplification does **not** mean hiding meaningful errors.

Errors should communicate:
1. what happened
2. what the user can do

Bad:
> Request failed with status code 401 because authentication credentials could not be validated.

Better:
> Instagram disconnected.

`Reconnect`

Bad:
> Something went wrong while processing your request. Please try again later or contact support if the issue continues.

Better:
> Couldn’t publish this post.

`Try again`

Secondary details may exist under:
`Details`

## 12. Remove Defensive Explanations

Audit language such as:
- “Don’t worry…”
- “Please note that…”
- “It is important to understand…”
- “This simply means…”
- “You can always…”
- “For your information…”
- “Keep in mind…”
- “Nothing will happen automatically…”
- “This does not mean that…”

Most of these phrases can be deleted.

Raffi should communicate facts directly.

## 13. Avoid Explaining Obvious UI

Do not describe what a button already says.

Bad:

**Export**

> Click this button to export your data.

`Export`

Remove the explanation.

## 14. Context Beats Documentation

Do not front-load instructions.

Teach through the interaction.

For example, instead of a paragraph explaining the campaign workflow, show:

### New campaign

**What are you promoting?**

`Tell Raffi`

Then ask the next question when needed.

## 15. AI Interface Simplification

This principle is especially important for Raffi's AI agent.

The user should feel like they are speaking to a smart coworker, not filling out software configuration.

Avoid explanatory cards describing what Raffi can do when the capability can demonstrate itself.

Prefer:

**Ask Raffi**

> “Plan next week’s Instagram posts.”

The capability should demonstrate itself.

## 16. AI Suggestions

Keep suggestions compact.

Bad:
> Based on your posting history and recent content calendar activity, Raffi has identified a possible gap in your posting schedule next Tuesday.

Better:

**Tuesday is empty.**

`Create a post`

Bad:
> Raffi believes this caption could potentially perform better if its opening sentence were made more direct.

Better:

**The opening could be stronger.**

`Improve it`

## 17. Settings

Settings are especially vulnerable to over-explanation.

Preferred pattern:

### Auto-publish
`On / Off`

Optional tooltip:
> Publish approved posts automatically.

Do not permanently display paragraphs below every switch.

## 18. Status Design

Prefer compact status indicators.

Examples:
- Connected
- Draft
- Scheduled
- Published
- Needs review
- Failed
- Trial
- Pro

Use badges, icons and typography where helpful rather than sentences.

Instead of:
> Your Instagram account is currently connected successfully.

Use:
> ● Connected

## 19. Dates

Avoid showing multiple representations of the same information.

Bad:
> 10 days left  
> Ends October 3, 2026

Default:
> 10 days left

Detailed view:
> Ends Oct 3

Do not display both unless the date is genuinely important.

## 20. Numbers

Use numbers as information compression.

Prefer:
> 6 scheduled

over:
> You currently have six social media posts scheduled for publication.

Prefer:
> 3 drafts

over:
> There are currently three posts saved in draft state.

## 21. Screen-Level Rule

Every major screen should answer:

### Where am I?
Clear title.

### What matters here?
One obvious current state or piece of content.

### What can I do?
One dominant primary action.

Anything else is secondary.

If a screen contains five competing explanations and six CTAs, redesign it rather than rewriting the text.

## 22. Visual Simplification

This project is not only a copy-editing exercise.

When text disappears, reconsider the layout.

Do not leave large cards containing almost nothing.

Consolidate redundant surfaces.

Prefer:
- more whitespace
- fewer borders
- fewer cards
- fewer nested containers
- stronger typography hierarchy
- one primary CTA
- lightweight secondary controls
- icon + label where appropriate

Avoid turning every piece of information into a separate card.

## 23. Card Reduction

Audit whether Raffi suffers from “card soup.”

If five related facts are displayed in five separate cards, consider one compact section.

Instead of separate cards for Plan, Price, Days remaining, Billing and Export, use:

### Trial

**10 days left**

`Manage`

## 24. Page Audit Procedure

Audit **every user-facing route**.

For every visible string, classify it as:

### KEEP
Critical and already concise.

### COMPRESS
Necessary but too verbose.

### MOVE
Useful information, but shown too early or in the wrong place.

### REMOVE
Does not materially help the user.

Perform this audit on:
- onboarding
- home/dashboard
- Raffi chat
- voice mode
- composer
- drafts
- approvals
- calendar
- campaigns
- Brand Brain
- Learn My Voice
- social accounts
- analytics
- publishing
- media/image generation
- notifications
- Usage & Plan
- account
- settings
- errors
- empty states
- modals
- confirmation dialogs
- tooltips

Do not limit this project to the Usage & Plan page.

## 25. Before / After Examples

### Example A
Before:
> No social media accounts are currently connected. Connect an account to begin using Raffi's publishing functionality.

After:

**No accounts connected**

`Connect account`

### Example B
Before:
> Your changes have been successfully saved to your Brand Brain and will now be available for Raffi to reference when generating future content.

After:

**Saved**

### Example C
Before:
> You have not created any campaigns yet. Campaigns allow Raffi to organize content around a specific marketing objective.

After:

**No campaigns yet**

`Create campaign`

### Example D
Before:
> Raffi has generated three content suggestions based on your current brand information and posting history.

After:

**3 ideas for you**

### Example E
Before:
> Image generation is powered by an AI model and may occasionally produce unexpected results.

Default UI:

**Generate image**

Move necessary limitations or safety information to contextual help rather than permanently displaying it.

## 26. Preserve Important Information

Do not blindly delete text.

Certain information must remain clear.

Preserve information involving:
- money
- charges
- subscription renewal
- destructive actions
- permanent deletion
- privacy
- publishing to a public platform
- account permissions
- irreversible actions
- legal consent
- security
- important errors

Simplify these messages, but do not make them ambiguous.

Example:

### Delete campaign?

This permanently deletes the campaign and its drafts.

`Cancel` `Delete`

This is appropriate.

## 27. Confirmation Dialogs

Do not confirm harmless actions.

Avoid confirmation dialogs for:
- saving
- closing a normal modal
- changing filters
- navigating
- editing drafts

Use confirmations mainly for consequential operations.

Examples:
- Delete account
- Delete campaign
- Publish publicly
- Disconnect critical integration
- Discard unsaved work

## 28. Toasts

Avoid noisy success notifications.

If the UI itself clearly reflects the change, do not also display:
> Successfully updated your settings!

For ordinary operations, silent success is preferable.

Use a toast when the result would otherwise be unclear.

Prefer:
> Saved

over:
> Your changes were saved successfully.

## 29. Placeholder Text

Placeholders should demonstrate input, not teach the whole feature.

Bad:
> Enter a detailed description of what you would like Raffi to help you create here...

Better:
> Launch post for my new course

## 30. Voice and Tone

Raffi UI copy should sound confident and natural.

Prefer:
> Connect Instagram

over:
> Please connect your Instagram account to continue.

Prefer:
> Try again

over:
> Please click here to attempt this operation again.

Prefer:
> Needs review

over:
> This item has not yet completed the review process.

## 31. Do Not Over-Minimize

Minimalism must not make Raffi mysterious.

Do not:
- replace clear labels with obscure icons
- hide important actions
- remove useful context from errors
- make destructive actions ambiguous
- bury information users frequently need
- require excessive hovering
- rely entirely on tooltips
- make accessibility worse

The target is:

**minimum necessary information**

not:

**minimum possible information**

## 32. Responsive Behaviour

The simplification should be especially aggressive on mobile.

Priority:
1. primary content
2. primary action
3. current state
4. secondary information
5. optional detail

Do not simply shrink desktop information onto mobile.

Where appropriate:
- collapse secondary metadata
- move advanced actions into menus
- shorten labels
- remove redundant descriptions

## 33. Accessibility

Do not remove semantic clarity while reducing visual text.

Maintain:
- accessible names
- screen reader descriptions where necessary
- meaningful button labels
- keyboard navigation
- clear focus states
- sufficient contrast
- understandable error messages

ARIA content can provide context that does not need to be visually displayed.

## 34. Implementation Architecture

Where practical, centralize repeated product language.

Example standardized status vocabulary:
- connected → Connected
- disconnected → Disconnected
- draft → Draft
- scheduled → Scheduled
- published → Published
- failed → Failed

Avoid slightly different verbose versions across different components.

Anti-pattern:
- “Your account is connected”
- “Successfully connected”
- “Connection successful”
- “Currently connected”

Use:
> Connected

everywhere unless context requires something different.

## 35. Add a Copy Review Layer

Create a lightweight internal checklist for new UI.

Before shipping any new customer-facing text, ask:

### Can this be deleted?
If no:

### Can this be shorter?
If no:

### Can this appear only when relevant?
If no:

### Is this written in user language rather than engineering language?

Only then keep it.

## 36. Automated Audit

Add a basic developer audit for suspicious UI copy where practical.

Search user-facing code for terms such as:
- deployment
- backend
- database
- provider
- implementation
- successfully
- currently
- please note
- please be aware
- this means
- you can
- in order to
- at this time
- functionality

Do not automatically delete matches.

Flag them for manual review.

## 37. UX Regression Tests

Add tests for critical simplified states.

### Usage & Plan
Assert the primary screen contains:
- Trial
- days remaining

And does **not** expose by default:
- deployment language
- internal billing implementation
- export-state commentary
- redundant trial explanations

### Connection status
Assert:
> Connected

rather than paragraphs describing the connection state.

### Empty states
Assert each core empty state contains:
- concise state
- relevant CTA

without unnecessary instructional paragraphs.

## 38. Execution Plan

### Phase 1 — Inventory
Identify every significant user-facing string and screen.

Do not change code yet.

Produce an audit table:

| Screen | Current copy | Classification | Proposed copy |
|---|---|---|---|
| Usage | Current plan: Trial | Compress | Trial |
| Usage | Billing is not enabled… | Move | Contextual only |
| Usage | Draft state exportable | Remove/Move | Export UI |
| Campaign | You have no campaigns… | Compress | No campaigns yet |

### Phase 2 — UX Restructuring
Identify cases where excessive wording is actually hiding poor information architecture.

Fix:
- duplicated cards
- excessive status panels
- repeated metadata
- redundant headings
- multiple CTAs
- unnecessary alerts

Do not solve every problem by merely shortening sentences.

### Phase 3 — Copy Simplification
Rewrite customer-facing copy using this specification.

### Phase 4 — Progressive Disclosure
Move secondary details into:
- tooltips
- popovers
- expandable sections
- secondary dialogs
- error details
- settings details

only where genuinely useful.

### Phase 5 — Responsive Review
Review all important screens on:
- desktop
- tablet
- mobile

Mobile should not inherit unnecessary desktop verbosity.

### Phase 6 — Accessibility Review
Confirm the simplified interface still communicates necessary context to:
- screen readers
- keyboard users
- users relying on explicit status feedback

### Phase 7 — Regression Testing
Run:
- unit tests
- component tests
- typecheck
- lint
- application build
- relevant end-to-end tests

Visually inspect the main user journeys.

## 39. Primary Journeys to Review Manually

At minimum test:
1. First login
2. Connect a social account
3. Ask Raffi something
4. Create a post
5. Generate/edit an image
6. Use voice interaction
7. Save a draft
8. Approve a post
9. Schedule a post
10. Publish a post
11. Create a campaign
12. Edit Brand Brain
13. Learn My Voice
14. Open Usage & Plan
15. Change settings
16. Encounter a recoverable error
17. Use Raffi on mobile

For each journey ask:

> Was there any text I had to read that did not help me complete the task?

If yes, remove, compress or defer it.

## 40. Acceptance Criteria

The project is complete only when:
- Raffi contains substantially less explanatory UI copy.
- Internal/developer terminology is absent from normal customer flows.
- Important screens expose one obvious primary action.
- Repeated statuses use standardized short labels.
- Empty states are concise.
- Settings no longer contain paragraphs beneath every control.
- Usage & Plan communicates the plan in seconds.
- Important billing/security/destructive information remains clear.
- Secondary details use progressive disclosure.
- Desktop and mobile both feel intentionally simplified.
- Accessibility is not degraded.
- Existing functionality continues to work.
- All relevant tests pass.

## 41. Usage & Plan Target

A user opening the page should ideally understand their account in approximately one glance.

Target default state:

## Trial

**10 days left**

`Manage plan`

Not:
> Current plan: Trial  
> $0  
> Nothing converts automatically  
> 10 days left  
> Ends October 3rd, 2026  
> Draft state exportable  
> Billing is not enabled on this deployment yet

The difference between these two examples represents the broader direction for the entire Raffi application.

## 42. Final Product Principle

Raffi is supposed to reduce work.

Its interface should not create more reading.

When Raffi already knows something, the product should usually act on that knowledge rather than explain the knowledge.

When something is obvious from the interface, do not describe it.

When information is only occasionally useful, reveal it only when needed.

When one word works, do not use one sentence.

When one sentence works, do not use one paragraph.

The finished Raffi experience should feel like:

> **See → understand → act.**

Not:

> **See → read → interpret → understand → search → act.**
