/**
 * Home result rows, kept free of React so they can be tested directly. The run artifact supplies the
 * written text; the saved workspace variants supply what is actually stored after apply and edits.
 */

export type DestinationStatus = 'pending' | 'writing' | 'ready' | 'failed' | 'cancelled';

interface Target {
  platform: string;
  language: string;
  channelId?: string;
}

interface ItemRun<V> {
  runId: string;
  status: string;
  events: { type: string; destination?: unknown }[];
  artifact?: { variants?: (V & Target & { text: string; account?: string })[] } | null;
}

interface SavedVariant extends Target {
  text: string;
  provenance?: { runId?: string } | null;
  runRefs?: string[] | null;
  proposedUpdate?: { runId?: string; text: string } | null;
}

export interface BuiltItem<V> {
  key: string;
  destination: Target & { account?: string };
  status: DestinationStatus;
  text: string;
  edited: string | null;
  variant: (V & Target & { text: string; account?: string }) | null;
}

const ACTIVE = new Set(['running', 'queued']);

/** The saved text for this run's slot: a draft it created, a refreshed draft (edited or still proposed). */
export function savedTextFor(saved: readonly SavedVariant[], runId: string | undefined, key: string, keyOf: (t: Target) => string): string | undefined {
  if (!runId) return undefined;
  const slot = saved.filter((v) => keyOf(v) === key);
  const created = slot.find((v) => v.provenance?.runId === runId);
  if (created) return created.text;
  const proposed = slot.find((v) => v.proposedUpdate?.runId === runId);
  if (proposed?.proposedUpdate) return proposed.proposedUpdate.text;
  return slot.find((v) => !v.proposedUpdate && v.runRefs?.includes(runId))?.text;
}

/**
 * One row per chosen destination in request order, then any destination the run also wrote (for
 * example a channel named in the brief), so nothing that Save would store stays out of view.
 */
export function buildItems<V>({ requested, run, savedVariants, edits, keyOf }: {
  requested: readonly Target[];
  run: ItemRun<V> | null;
  savedVariants: readonly SavedVariant[];
  edits: Record<string, string>;
  keyOf: (t: Target) => string;
}): BuiltItem<V>[] {
  const variants = run?.artifact?.variants ?? [];
  const completed = new Set(run?.events.filter((e) => e.type === 'message.completed' && typeof e.destination === 'number').map((e) => e.destination as number) ?? []);
  const failed = run?.status === 'failed';
  const cancelled = run?.status === 'cancelled';
  const running = run ? ACTIVE.has(run.status) : false;
  const chosen = requested.map(({ platform, language, channelId }) => ({ platform, language, channelId }));
  const chosenKeys = new Set(chosen.map(keyOf));
  const extra = variants.filter((v) => !chosenKeys.has(keyOf(v))).map(({ platform, language, channelId }) => ({ platform, language, channelId }));
  return [...chosen, ...extra].map((destination, index) => {
    const key = keyOf(destination);
    const variant = variants.find((v) => keyOf(v) === key) ?? null;
    const status: DestinationStatus = variant ? 'ready' : failed ? 'failed' : cancelled ? 'cancelled' : completed.has(index) ? 'ready' : running && index === completed.size ? 'writing' : 'pending';
    const text = savedTextFor(savedVariants, run?.runId, key, keyOf) ?? variant?.text ?? '';
    return { key, destination: { ...destination, account: variant?.account }, status, text, edited: edits[key] !== undefined && edits[key] !== text ? edits[key] : null, variant };
  });
}
