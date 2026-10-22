import type { ApiError } from '@/lib/api/client';
import type { DiscordCopy } from '@/lib/channels/discord-copy';

/**
 * The launch gate, the server cap and the shared request coordinator refuse with stable codes, so the refusal can be
 * shown in the person's language instead of the server's operator wording.
 */
export function discordRefusal(error: ApiError, copy: DiscordCopy): string {
  if (error.code === 'discord_access_closed') return copy.accessClosed;
  if (error.code === 'discord_capacity_reached') return copy.capacityReached;
  if (error.code === 'discord_rate_delayed') return copy.rateDelayed;
  if (error.code === 'discord_rate_coordinator_unavailable') return copy.coordinatorUnavailable;
  return error.message;
}
