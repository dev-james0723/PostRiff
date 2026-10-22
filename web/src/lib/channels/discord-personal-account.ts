import type { DiscordIdentity, ProviderView } from '@/lib/api/types';

/** Presentation only. Live Discord permission and token checks remain server-owned. */
export function discordDiscoveryState(identity: DiscordIdentity | undefined):
  'choose_identity' | 'reconnect_required' | 'scope_required' | 'ready' {
  if (!identity) return 'choose_identity';
  if (identity.status !== 'linked') return 'reconnect_required';
  return identity.discoverGuilds === true ? 'ready' : 'scope_required';
}

export function discordCanConnect(provider: ProviderView | undefined, canManage: boolean): boolean {
  return canManage && provider?.id === 'discord' && provider.discordConnectionsV2 === true
    && provider.capabilities.identity === true && provider.configured !== false
    && provider.connectReady !== false && provider.executionPaused !== true
    && provider.configurationState !== 'partial_configuration'
    && provider.configurationState !== 'invalid_configuration';
}

export function missingScopePublishingMessage(provider: string): string {
  return provider === 'discord'
    ? 'Discord publishing is unavailable until the required server and channel authorization is verified.'
    : provider === 'mastodon'
      ? 'Capabilities requiring those permissions remain unavailable.'
      : 'Publishing stays Assisted.';
}

/** Revoking an existing local mapping does not need a live provider grant. */
export function discordPrivateLinkActions(identity: Pick<DiscordIdentity, 'status' | 'privateDraftsLinked' | 'privateDraftsConfigured'>, enabled: boolean) {
  const remove = identity.privateDraftsConfigured === true || identity.privateDraftsLinked === true;
  return { bind: enabled && identity.status === 'linked' && !remove, remove };
}
