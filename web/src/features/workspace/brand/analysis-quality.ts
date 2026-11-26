/**
 * The analysis quality slider's rules, shared by the Brand Brain analysis step (voice samples) and the AI reading of
 * imported posts. Pure: no React, no server, no path aliases (node tests import this file directly).
 *
 * Stops run cheapest to most thorough. A stop this deployment does not offer is shown but cannot be chosen, and is
 * never quietly served by another model: the cost a person approves is the cost of the model they chose.
 */
export type QualityId = 'economy' | 'balanced' | 'best';
export const QUALITY_ORDER: readonly QualityId[] = ['economy', 'balanced', 'best'];

export interface QualityStopLike {
  id: QualityId;
  available: boolean;
}

export function isQualityId(value: unknown): value is QualityId {
  return typeof value === 'string' && (QUALITY_ORDER as readonly string[]).includes(value);
}

/** The slider position of a stop (0 to 2). */
export function qualityIndex(id: QualityId): number {
  return QUALITY_ORDER.indexOf(id);
}

/** The stop at a slider position; positions outside 0 to 2 are clamped. */
export function qualityAt(position: number): QualityId {
  const index = Number.isFinite(position) ? Math.round(position) : 1;
  return QUALITY_ORDER[Math.max(0, Math.min(QUALITY_ORDER.length - 1, index))];
}

/** The offered stop closest to `wanted`; on a tie the cheaper one. Null when no stop is offered. */
export function nearestAvailable(stops: readonly QualityStopLike[], wanted: QualityId): QualityId | null {
  const offered = new Set(stops.filter((stop) => stop.available).map((stop) => stop.id));
  if (offered.has(wanted)) return wanted;
  const at = qualityIndex(wanted);
  for (let distance = 1; distance < QUALITY_ORDER.length; distance += 1) {
    for (const index of [at - distance, at + distance]) {
      const id = QUALITY_ORDER[index];
      if (id && offered.has(id)) return id;
    }
  }
  return null;
}

/** Where a screen starts: the server's default stop when it is offered, else the offered stop nearest Balanced. */
export function initialQuality(stops: readonly QualityStopLike[], preferred?: QualityId | null): QualityId | null {
  return nearestAvailable(stops, preferred && isQualityId(preferred) ? preferred : 'balanced');
}

/** The most credits a quote may use, in whole credits (rounded up); null when the quote is not under credit billing. */
export function quoteCredits(quote?: { creditLimit?: { maxMilliCredits?: number } | null } | null): number | null {
  const milli = quote?.creditLimit?.maxMilliCredits;
  return typeof milli === 'number' && Number.isFinite(milli) && milli >= 0 ? Math.ceil(milli / 1000) : null;
}

/** A quote's estimated provider cost in US dollars; null without a usable estimate. */
export function quoteUsd(quote?: { estimatedMicroUsd?: number } | null): number | null {
  const micro = quote?.estimatedMicroUsd;
  return typeof micro === 'number' && Number.isFinite(micro) && micro >= 0 ? micro / 1_000_000 : null;
}

/** A model id as people read it: "anthropic/claude-opus-5.5" → "claude-opus-5.5". */
export function modelShortName(model: string): string {
  const name = model.split('/').pop();
  return name && name.length ? name : model;
}

/** How people know each maker on Rafii's AI gateway; an unknown maker shows its id with a capital letter. */
const MAKERS: Record<string, string> = {
  anthropic: 'Anthropic (Claude)',
  openai: 'OpenAI (GPT)',
  google: 'Google (Gemini)',
  deepseek: 'DeepSeek',
  alibaba: 'Alibaba (Qwen)',
  meta: 'Meta (Llama)',
  mistral: 'Mistral',
  xai: 'xAI (Grok)',
  moonshotai: 'Moonshot (Kimi)',
  zai: 'Z.ai (GLM)',
  minimax: 'MiniMax'
};

/** The maker of a gateway model id: "google/gemini-3.8-flash" → "google". */
export function makerOf(model: string): string {
  return model.includes('/') ? model.split('/')[0] : '';
}

export function makerLabel(maker: string): string {
  if (MAKERS[maker]) return MAKERS[maker];
  return maker ? maker.charAt(0).toUpperCase() + maker.slice(1) : '';
}

export interface ProviderChoice {
  model: string;
  maker?: string;
  available: boolean;
}

/**
 * "Advanced · choose AI provider": the offered choices of a stop, one row per model, labelled by maker; two models of
 * one maker are told apart by their short model name. The person picks a provider, never a model id.
 */
export function providerOptions(choices: readonly ProviderChoice[] | undefined): { model: string; label: string }[] {
  const offered = (choices ?? []).filter((choice) => choice.available);
  const count = new Map<string, number>();
  for (const choice of offered) {
    const maker = choice.maker || makerOf(choice.model);
    count.set(maker, (count.get(maker) ?? 0) + 1);
  }
  return offered.map((choice) => {
    const maker = choice.maker || makerOf(choice.model);
    const label = makerLabel(maker) || modelShortName(choice.model);
    return { model: choice.model, label: (count.get(maker) ?? 0) > 1 ? `${label} · ${modelShortName(choice.model)}` : label };
  });
}

/** A quote still usable now: not expired (expiresAt is in seconds). */
export function quoteLive(quote: { expiresAt?: number } | null | undefined, nowMs: number = Date.now()): boolean {
  return typeof quote?.expiresAt === 'number' && quote.expiresAt * 1000 > nowMs;
}
