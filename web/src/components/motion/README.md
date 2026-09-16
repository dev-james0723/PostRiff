# Motion components

Animated primitives copied from [beUI](https://github.com/starc007/ui-components) (MIT, © 2026 Saurabh Chauhan) and owned by this app from here on. Paths mirror beUI so a later `npx shadcn add @beui/<slug>` lands on the same files:

- `src/components/motion/*` — primitives (tabs, switch, checkbox, radio, badges, text effects, tooltip, context menu, hold button, dynamic island, notification stack, file tree, loaders, 404 stages…)
- `src/components/agents/*` — agent surfaces (message rows, disclosure, to-do list, progress and shimmer)
- `src/components/charts/heat-calendar*` — activity heat calendar
- `src/lib/ease.ts`, `src/lib/touch.ts`, `src/lib/presence-gate.tsx`, `src/lib/text-shimmer.ts`, `src/lib/hooks/*` — the motion tokens and gesture hooks they share

## Local changes

- Icons come from `@/components/icons` (Tabler) instead of `lucide-react`.
- `button/base.tsx` renders through the app's `buttonVariants`, so `Button`, `StatefulButton` and `MagneticButton` follow the active theme; adds `destructive` and `xs`.
- `radio.tsx`: `RadioGroupItem` accepts a `description` line and a ReactNode label.
- `agents/message.tsx` no longer re-exports `MessageScroller` (not copied).
- `charts/heat-calendar/context.ts`: two pure helpers moved to module scope (lint).
- Formatted with the app's oxfmt config; a few lint suppressions carry their reason inline.

## Rules when using them

- Real data only. A timer, count, badge or progress row must read workspace state; nothing animates a number the API did not return.
- Motion already respects `prefers-reduced-motion` inside each component. Custom motion added around them must check `useReducedMotion()` too.
- Keep the control's meaning: tabs that switch panels use `Tabs`; choices use `RadioGroup` or checkboxes; destructive actions keep a confirmation (dialog or hold).

## License

MIT License

Copyright (c) 2026 Saurabh Chauhan

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
