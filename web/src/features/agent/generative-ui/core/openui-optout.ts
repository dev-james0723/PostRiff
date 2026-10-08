/**
 * Opt out of OpenUI's development devtools auto-mount (D-A3).
 *
 * `@openuidev/react-lang` 0.3.2 mounts its Inspect widget under `next dev` by importing remote, unpinned JavaScript from a
 * CDN, unless this global flag is already set when its entry module evaluates (dist/index.mjs:16-42). `core/openui.ts`
 * imports this module first; ES modules evaluate imports in order, so the flag is set before react-lang runs. Production
 * builds drop the devtools branch entirely; this keeps development sessions free of remote code too.
 */
(globalThis as Record<symbol, unknown>)[Symbol.for('openui.devtools.autoMount')] = true;

export const OPENUI_DEVTOOLS_DISABLED = true;
