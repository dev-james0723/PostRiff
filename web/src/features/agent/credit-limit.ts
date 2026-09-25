/** Parse a visible maximum, not a predicted task cost. Keep arithmetic integral. */
export function parseCreditLimit(value: string): number | null {
  const text = value.trim();
  if (!/^\d{1,6}(?:\.\d)?$/.test(text)) return null;
  const [whole, fraction = '0'] = text.split('.');
  const milli = Number(whole) * 1000 + Number(fraction) * 100;
  return milli > 0 && milli <= 100_000_000 ? milli : null;
}
