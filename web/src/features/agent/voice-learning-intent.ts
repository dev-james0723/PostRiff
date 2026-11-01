export interface VoiceLearningRequest {
  platform?: 'Instagram' | 'LinkedIn' | 'Bluesky';
  instructions: string;
}

/** Guided own-writing learning, not a publishing command or permission grant. */
export function voiceLearningIntent(text: string): VoiceLearningRequest | null {
  const body = text.trim();
  if (!body || body.length > 1500 || !(/\bmy\b/i.test(body) || /我/.test(body))) return null;
  const analysis = /\b(?:analy[sz]e|learn|study|assess)\b|分析|學習|学习/.test(body.toLowerCase());
  const writing = /\b(?:posts?|captions?|writing|voice|style)\b|how i write|寫作|写作|貼文|贴文|風格|风格/i.test(body);
  if (!analysis || !writing || /\b(?:another|their|his|her)\b|他人|別人|别人/i.test(body)) return null;
  const instagram = /\binstagram\b|\big\b/i.test(body);
  const linkedin = /\blinkedin\b/i.test(body);
  const bluesky = /\bbluesky\b/i.test(body);
  const platforms = [instagram && 'Instagram', linkedin && 'LinkedIn', bluesky && 'Bluesky'].filter(Boolean) as NonNullable<VoiceLearningRequest['platform']>[];
  return { platform: platforms.length === 1 ? platforms[0] : undefined, instructions: body };
}
