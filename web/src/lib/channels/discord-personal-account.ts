import type { DiscordIdentity, ProviderView } from '@/lib/api/types';

/** Presentation only. Live Discord permission and token checks remain server-owned. */
export function discordDiscoveryState(identity: DiscordIdentity | undefined):
  'choose_identity' | 'reconnect_required' | 'scope_required' | 'ready' {
  if (!identity) return 'choose_identity';
  if (identity.status !== 'linked') return 'reconnect_required';
  return identity.discoverGuilds === true ? 'ready' : 'scope_required';
}

/**
 * Whether the Channels page shows the "Personal Discord accounts" section: only when the Discord launch gate is open
 * for this workspace (the server's per-workspace discordAccess verdict, with the connections v2 flow on), or when the
 * workspace already has linked Discord identities, which stay visible and manageable. While Discord is closed to a
 * workspace that never linked one, nothing new appears on its Channels page (finding UI-1). The Connect sheet keeps
 * its own closed-gate message (UI-2).
 */
export function showDiscordPersonalAccounts(provider: ProviderView | undefined, identities: readonly unknown[] | undefined): boolean {
  return (provider?.id === 'discord' && provider.discordConnectionsV2 === true && provider.discordAccess?.status === 'open')
    || (identities?.length ?? 0) > 0;
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
