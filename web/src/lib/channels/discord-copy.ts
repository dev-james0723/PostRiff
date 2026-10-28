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

/**
 * The most approved Discord posts a workspace may have scheduled within any one hour: the owner's ceiling (reply 16,
 * D-4) and the server's `WORKSPACE_HOURLY_CEILING` (docs/discord-custody-20261023/HOURLY-CEILING-CONTRACT.md). This is
 * the one place the web writes the number. A refusal that carries its own `limit` wins over it (see
 * `hourlyCeilingLimit`), and `tests/discord-hourly-ceiling.test.cjs` pins it against the contract text, so a changed
 * ceiling fails there instead of showing the wrong number.
 */
export const WORKSPACE_HOURLY_CEILING = 300;

/** The refusal's explanation with the limit written in. `{limit}` is the only placeholder. */
export function hourlyCeilingBody(copy: DiscordCopy, limit: number = WORKSPACE_HOURLY_CEILING): string {
  return copy.hourlyCeilingBody.replace('{limit}', String(limit));
}
