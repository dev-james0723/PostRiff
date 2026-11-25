/** Parse a visible maximum, not a predicted task cost. Keep arithmetic integral. */
export function parseCreditLimit(value: string): number | null {
  const text = value.trim();
  if (!/^\d{1,6}(?:\.\d)?$/.test(text)) return null;
  const [whole, fraction = '0'] = text.split('.');
  const milli = Number(whole) * 1000 + Number(fraction) * 100;
  return milli > 0 && milli <= 100_000_000 ? milli : null;
}

/** No typed limit is needed: the server approves this request's maximum automatically and the balance covers it. */
export function automaticCovers(ceilingMilliCredits: number | null | undefined, automaticLimitMilliCredits: number | null | undefined, availableMilliCredits: number | null | undefined): boolean {
  return typeof ceilingMilliCredits === 'number' && typeof automaticLimitMilliCredits === 'number' && typeof availableMilliCredits === 'number'
    && ceilingMilliCredits >= 0 && ceilingMilliCredits <= automaticLimitMilliCredits && ceilingMilliCredits <= availableMilliCredits;
}

/**
 * Whether a credit-mode request can be sent: never without the server's estimate; with a typed limit that covers the
 * estimate's ceiling and the balance; or, with nothing typed, when the automatic limit covers it. Something typed that is
 * not a valid limit never falls back to the automatic one.
 */
export function creditLimitReady({ estimated, typed, maximum, ceiling, available, automatic }: {
  estimated: boolean; typed: boolean; maximum: number | null; ceiling: number | null; available: number; automatic?: number | null;
}): boolean {
  if (!estimated) return false;
  if (maximum === null) return !typed && automaticCovers(ceiling, automatic, available);
  return maximum <= available && (ceiling === null || maximum >= ceiling);
}
