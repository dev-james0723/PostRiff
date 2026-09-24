# Stream F6 — Public marketing pages

Common brief: `F-page-migration-common.md`. Recipe: DNA §21.19 (Public landing / product education); prompt §10 row "Auth/onboarding/invitations/public pages".

Files: `web/src/app/(marketing)/**` (13 pages + layout), `web/src/components/marketing/**`, `web/src/content/**` only if a rendered claim must change (do not rewrite legal text; do not invent platform, growth or automation claims). Same monochrome palette, materials, typography (larger selective serif accent allowed here), controls and theme behaviour as the signed-in app so landing → app feels continuous; hero/CTA entry paths (`Sign in`, `Get started`) untouched; JSON-LD, metadata, anchors (`/#how-it-works`), OG image untouched. Note: several of these files carry uncommitted edits from an earlier session (git status shows them modified); build on their current content, never revert them.
