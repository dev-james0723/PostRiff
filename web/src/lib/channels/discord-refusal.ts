import type { ApiError } from '@/lib/api/client';
import type { DiscordCopy } from '@/lib/channels/discord-copy';

/**
 * The launch gate, the server cap and the shared request coordinator refuse with stable codes, so the refusal can be
 * shown in the person's language instead of the server's operator wording. Use it for every Discord request that can
 * reach them: connecting, listing servers, choosing a destination and verifying a connection.
 */
export function discordRefusal(error: ApiError, copy: DiscordCopy): string {
  if (error.code === 'discord_access_closed') return copy.accessClosed;
  if (error.code === 'discord_capacity_reached') return copy.capacityReached;
  if (error.code === 'discord_rate_delayed') return copy.rateDelayed;
  if (error.code === 'discord_rate_coordinator_unavailable') return copy.coordinatorUnavailable;
  return error.message;
}

/**
 * The same mapping for the page Discord returns the person to after the consent screen. By then Discord may already
 * have put the bot in their server, so "nothing was connected" would be false there; say what to do instead.
 */
export function discordReturnRefusal(error: ApiError, copy: DiscordCopy): string {
  if (error.code === 'discord_rate_delayed') return copy.returnRateDelayed;
  if (error.code === 'discord_rate_coordinator_unavailable') return copy.returnCoordinatorUnavailable;
  return discordRefusal(error, copy);
}
