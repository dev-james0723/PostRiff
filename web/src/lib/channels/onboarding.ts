import type { ChannelView, ProviderView } from '@/lib/api/types';
import type { ConnectCapability } from './state';

/** Least privilege for a new account; reconnect preserves an explicitly requested use. */
export function defaultConnectCapability(provider: ProviderView | undefined, wanted?: ConnectCapability): ConnectCapability {
  if (wanted && provider?.capabilities[wanted]) return wanted;
  const order: ConnectCapability[] = ['posts_read', 'identity', 'publish', 'analytics', 'comments_read', 'reply'];
  return order.find((key) => provider?.capabilities[key]) ?? 'identity';
}

/** Browser hints only. The server rechecks identity, entitlement and actual read permission. */
export function historyBlocker(channel: ChannelView | undefined, provider: ProviderView | undefined): string | null {
  if (!channel) return 'Choose a connected Instagram or LinkedIn account.';
  const platform = channel.platform;
  if (provider?.executionPaused) return `${platform} is paused. Add samples manually instead.`;
  if (!provider || provider.configured === false || provider.connectReady === false) return `Importing from ${platform} isn't available yet.`;
  if (!['read_verified', 'publish_verified'].includes(channel.connectionState)) return `Reconnect ${platform} to read its posts.`;
  // LinkedIn needs both app approval and the member's r_member_social grant; either gap blocks the import.
  if (platform === 'LinkedIn' && (!provider.historyAvailableForApp || !channel.scopes.includes('r_member_social'))) return "LinkedIn hasn't granted permission to import past posts. Add samples manually instead.";
  if (!provider.historyAvailableForApp) return `${platform} hasn't granted permission to import past posts. Add samples manually instead.`;
  return null;
}

/** A platform's readiness in the customer's words; setup detail stays in the tile's Details. */
export function providerReadinessLabel(provider: ProviderView): string {
  if (
    provider.configurationState === 'partial_configuration' ||
    provider.configurationState === 'invalid_configuration' ||
    provider.configured === false ||
    provider.connectReady === false
  )
    return 'Not available yet';
  if (provider.executionPaused) return 'Paused'; // STATUS.paused; a literal keeps this module loadable by its node test
  return provider.productionReviewed ? 'Available' : 'Review pending';
}
