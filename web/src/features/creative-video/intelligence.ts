import type { CreativeDirectionControl, CreativeQuote, CreativeSettings, IntelligenceLevel } from '@/lib/api/creative-video';
import type { IntelligenceOption } from '@/components/rafii/ai-intelligence-control';

export const videoLevels: readonly IntelligenceOption<IntelligenceLevel>[] = [
  { id: 'draft', label: 'Draft', description: 'Explore shot timing with a composed storyboard or an economical take.' },
  { id: 'balanced', label: 'Balanced', description: 'Recommended for everyday videos. Match the scene, format and credit limit.' },
  { id: 'professional', label: 'Professional', description: 'Plan for campaign detail, consistent styling and deliberate camera movement.' },
  { id: 'cinematic', label: 'Cinematic', description: 'Prioritize lighting, motion and continuity in the creative direction for this take.' }
];

export const directionControls: readonly [CreativeDirectionControl, string][] = [
  ['referenceAdherence', 'Reference structure'], ['creativeFreedom', 'Creative freedom'],
  ['visualFidelity', 'Visual detail'], ['characterConsistency', 'Character continuity'],
  ['productFidelity', 'Product accuracy'], ['motionQuality', 'Motion quality'],
  ['brandConsistency', 'Brand consistency']
];

export const initialSettings: CreativeSettings = { level: 'balanced', mode: 'auto' };

/** Work in integer thousandths, matching the wallet and preserving its smallest unit. */
export function parseCreditLimit(value: string): number | null {
  const match = /^(\d+)(?:\.(\d{1,3}))?$/.exec(value.trim());
  if (!match) return null;
  const milli = Number(match[1]) * 1000 + Number((match[2] ?? '').padEnd(3, '0'));
  return Number.isSafeInteger(milli) ? milli : null;
}

export const formatCredits = (milli: number) => (milli / 1000).toLocaleString(undefined, { maximumFractionDigits: 3 });

export function canAuthorizeQuote(quote: CreativeQuote | undefined, now: number): quote is CreativeQuote & { id: string } {
  if (!quote || quote.eligible !== true || !quote.id || typeof quote.expiresAt !== 'number' ||
      !Number.isFinite(quote.expiresAt) || quote.expiresAt * 1000 <= now) return false;
  const { estimatedMilliCredits: estimate, maximumMilliCredits: cap, availableMilliCredits: balance, estimatedUsdMicro: usd } = quote;
  return typeof estimate === 'number' && Number.isSafeInteger(estimate) && estimate >= 0 &&
    typeof cap === 'number' && Number.isSafeInteger(cap) && cap >= estimate &&
    typeof usd === 'number' && Number.isSafeInteger(usd) && usd >= 0 &&
    (balance === null || (Number.isSafeInteger(balance) && balance >= estimate));
}
