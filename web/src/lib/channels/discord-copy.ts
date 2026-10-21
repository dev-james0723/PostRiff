import packs from './discord-copy.json';
import { healthCopy } from './health-copy';
export type DiscordCopy = typeof packs.en;
/** Same three complete UI packs and regional fallback as Connection Health. */
export function discordCopy(locale: string): DiscordCopy {
  return packs[healthCopy(locale).lang];
}
