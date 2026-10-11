import type { ChannelView, OfficialCapability } from '@/lib/api/types';

// Only account/destination identity rows. Reads and roles remain independent.
const CONNECTION_FEATURES = new Set(['connected', 'identity', 'member_identity', 'page_selected', 'page_identity', 'channel_selected', 'channel_identity']);
type Readiness = ChannelView['socialReadiness'];

export function isVerifiedConnectionFeature(key: string, feature: OfficialCapability, readiness?: Readiness): boolean {
  return readiness?.connection === 'CONNECTED' && feature.granted && feature.implemented
    && feature.officialSupport === 'documented' && CONNECTION_FEATURES.has(key);
}

/** A saved grant and an app-wide release qualification are separate facts. */
export function officialCapabilityStatus(key: string, feature: OfficialCapability, readiness?: Readiness): string {
  if (isVerifiedConnectionFeature(key, feature, readiness)) return 'Identity verified for this account';
  if (feature.state === 'READY') return 'Ready · live tested';
  if (feature.officialSupport === 'unsupported') return 'Official API unsupported';
  if (feature.officialSupport === 'audit_unavailable') return 'Official support needs verification';
  if (!feature.implemented) return 'Engineering pending';
  if (!feature.appApproved) return 'Platform approval unverified';
  if (!feature.granted) return 'Permission required';
  if (!feature.eligible) return 'Account eligibility unverified';
  return 'Live test pending';
}

export function connectionSummary(channel: Pick<ChannelView, 'socialReadiness' | 'officialCapabilities'>): string | null {
  const readiness = channel.socialReadiness;
  if (!readiness) return null;
  if (readiness.connection === 'DESTINATION_REQUIRED') return 'Choose an eligible destination to finish connecting.';
  if (readiness.connection === 'REAUTHORIZATION_REQUIRED') return 'Reconnect required.';
  if (readiness.connection !== 'CONNECTED') return 'Not connected.';
  const publishingAvailable = channel.officialCapabilities
    ? Object.values(channel.officialCapabilities).some((feature) => ['publish', 'organization_publish'].includes(feature.permission_group) && feature.state === 'READY')
    : readiness.publishing === 'PUBLISHING_AVAILABLE';
  const memberPublication = channel.officialCapabilities?.member_publish;
  if (!publishingAvailable && readiness.publishing === 'PUBLISHING_AVAILABLE'
      && memberPublication?.appApproved && memberPublication.granted && memberPublication.implemented
      && memberPublication.officialSupport === 'documented') {
    return 'Connected — publishing permission granted; verification pending.';
  }
  return publishingAvailable ? 'Connected — see publishing permissions below.' : 'Connected — publishing not enabled.';
}
