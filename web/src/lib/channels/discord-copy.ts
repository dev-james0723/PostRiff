import packs from './discord-copy.json';
import { healthCopy } from './health-copy';
export type DiscordCopy = typeof packs.en;
/** Same three complete UI packs and regional fallback as Connection Health. */
export function discordCopy(locale: string): DiscordCopy {
  return packs[healthCopy(locale).lang];
}

export function discordSenderLabel(copy: DiscordCopy, kind?: string, name?: string | null): string {
  return kind === 'webhook' && name
    ? `${copy.senderNamePrefix}: ${name} · ${copy.senderWebhookKind}`
    : kind === 'webhook' ? copy.senderWebhook : copy.senderBot;
}
