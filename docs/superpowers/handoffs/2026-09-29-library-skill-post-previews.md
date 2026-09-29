# Handoff — Rafii Skill Reader + Post Phone Preview

The product decision is final. Implement, verify and ship the plan in:
- `docs/superpowers/specs/2026-09-29-library-skill-post-previews.md`
- `docs/superpowers/plans/2026-09-29-library-skill-post-previews.md`

Do not redesign the interaction.

Critical invariants:
- Skill row tap previews; it does **not** attach.
- Only **Use skill** attaches.
- Full skill body never moves into the public model catalogue.
- Post quick tap keeps its existing attachment behavior.
- Post hold opens the existing real iPhone/platform preview renderer.
- Do not build a second/fake LinkedIn, Instagram or Threads mockup.
- Preserve existing media/account-picture loading and honesty captions.
- Provide a keyboard/fine-pointer preview path.
- Preserve unrelated WIP and current `consumer-saas` behavior.

Release evidence must name the exact branch/head, tests, PR, merge SHA, deployment and any browser gate that could not be executed.
