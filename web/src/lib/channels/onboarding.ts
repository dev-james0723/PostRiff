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
  if (provider?.executionPaused) return 'This connector is paused. Retained samples and manual imports remain available.';
  if (!provider || provider.configured === false || provider.connectReady === false) return 'This connector needs server configuration. Open Channels for setup details.';
  if (!['read_verified', 'publish_verified'].includes(channel.connectionState)) return 'Reconnect or verify this account before reading its posts.';
  if (channel.platform === 'LinkedIn' && (!provider.historyAvailableForApp || !channel.scopes.includes('r_member_social'))) return 'LinkedIn is connected, but LinkedIn has not granted this app permission to import your historical posts. Separate provider approval and a granted r_member_social scope are required. Import writing samples manually instead.';
  if (!provider.historyAvailableForApp) return 'Historical-post import requires separate provider approval. Import writing samples manually.';
  return null;
}

export function providerReadinessLabel(provider: ProviderView): string {
  if (provider.configurationState === 'partial_configuration') return 'Partial credentials';
  if (provider.configurationState === 'invalid_configuration') return 'Invalid configuration';
  if (provider.configured === false) return 'Not configured';
  if (provider.executionPaused) return 'Paused';
  if (provider.connectReady === false) return 'Configuration blocked';
  return provider.productionReviewed ? 'Identity connection available' : 'Configured · review not confirmed';
}

