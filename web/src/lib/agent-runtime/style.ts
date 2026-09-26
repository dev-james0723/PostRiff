/**
 * How Rafii talks to one person (text and voice). Mirrors `src/postriff_phase2/agent_runtime_v2/style.py`:
 * enum values only, stored on the person's profile (`GET/PATCH /api/me` → `preferences.agentStyle`).
 */

export const TONES = ['friendly', 'professional', 'playful', 'direct'] as const;
export const DETAILS = ['concise', 'balanced', 'detailed'] as const;
export const PACES = ['slower', 'normal', 'faster'] as const;
export const VOICES = ['marin', 'cedar', 'sage', 'verse', 'coral', 'alloy'] as const;
export const LANGUAGES = ['auto', 'en', 'yue', 'cmn'] as const;
export const INITIATIVE = ['ask', 'suggest'] as const;

export type Tone = (typeof TONES)[number];
export type Detail = (typeof DETAILS)[number];
export type Pace = (typeof PACES)[number];
export type VoiceId = (typeof VOICES)[number];
export type Language = (typeof LANGUAGES)[number];
export type Initiative = (typeof INITIATIVE)[number];

export interface AgentStyle {
  tone: Tone;
  detail: Detail;
  pace: Pace;
  voice: VoiceId;
  language: Language;
  initiative: Initiative;
  /** False until the person picked a style once (the first voice call offers the presets). */
  chosen: boolean;
}

export type AgentStylePatch = Partial<Omit<AgentStyle, 'chosen'>> & { preset?: PresetId; chosen?: boolean };

export const DEFAULT_STYLE: AgentStyle = { tone: 'friendly', detail: 'balanced', pace: 'normal', voice: 'marin', language: 'auto', initiative: 'suggest', chosen: false };

export type PresetId = 'friendly' | 'concise' | 'explainer';

export const PRESETS: Record<PresetId, { label: string; description: string; style: Pick<AgentStyle, 'tone' | 'detail' | 'pace' | 'initiative'> }> = {
  friendly: { label: 'Friendly', description: 'Warm, short answers and a helpful next step.', style: { tone: 'friendly', detail: 'balanced', pace: 'normal', initiative: 'suggest' } },
  concise: { label: 'Concise', description: 'Straight to the point. One sentence unless you ask for more.', style: { tone: 'direct', detail: 'concise', pace: 'normal', initiative: 'ask' } },
  explainer: { label: 'Explain in detail', description: 'Step by step, a little slower, and says why.', style: { tone: 'friendly', detail: 'detailed', pace: 'slower', initiative: 'suggest' } }
};

export const TONE_LABELS: Record<Tone, string> = { friendly: 'Friendly', professional: 'Professional', playful: 'Playful', direct: 'Direct' };
export const DETAIL_LABELS: Record<Detail, string> = { concise: 'Concise', balanced: 'Balanced', detailed: 'Detailed' };
export const PACE_LABELS: Record<Pace, string> = { slower: 'Slower', normal: 'Normal', faster: 'Faster' };
export const VOICE_LABELS: Record<VoiceId, string> = { marin: 'Marin', cedar: 'Cedar', sage: 'Sage', verse: 'Verse', coral: 'Coral', alloy: 'Alloy' };
export const LANGUAGE_LABELS: Record<Language, string> = { auto: 'Match my language', en: 'English', yue: '廣東話', cmn: '普通话' };
export const INITIATIVE_LABELS: Record<Initiative, string> = { ask: 'Wait for me to ask', suggest: 'Suggest next steps' };

const FIELDS = { tone: TONES, detail: DETAILS, pace: PACES, voice: VOICES, language: LANGUAGES, initiative: INITIATIVE } as const;

/** Any value from the API or storage becomes a complete, valid style (unknown values fall back to the default). */
export function normalizeStyle(raw: unknown): AgentStyle {
  const source = raw && typeof raw === 'object' ? (raw as Record<string, unknown>) : {};
  const out: Record<string, unknown> = {};
  for (const [key, allowed] of Object.entries(FIELDS)) {
    const value = source[key];
    out[key] = (allowed as readonly string[]).includes(value as string) ? value : DEFAULT_STYLE[key as keyof typeof FIELDS];
  }
  out.chosen = source.chosen === true;
  return out as unknown as AgentStyle;
}

/** The preset a style matches exactly, if any (the picker marks it). */
export function presetOf(style: AgentStyle): PresetId | null {
  for (const [id, preset] of Object.entries(PRESETS) as [PresetId, (typeof PRESETS)[PresetId]][]) {
    if (Object.entries(preset.style).every(([key, value]) => style[key as keyof AgentStyle] === value)) return id;
  }
  return null;
}
