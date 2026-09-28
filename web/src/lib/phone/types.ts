export type CustomPhoneRule = {
  id: string; when: string; discuss: string; enabled: boolean; version: string;
  eventType: string; countAtLeast: number; windowHours: number; sameEntity: boolean;
};
export type PhonePreferences = {
  enabled: boolean; proactiveCalls: boolean; scheduledCalls: boolean; quietStart: number; quietEnd: number;
  timeZone: string; maxCallsPerDay: number; maxMilliCreditsPerCall: number; eventAllowlist: string[]; customRules: CustomPhoneRule[];
  fallbackToPush: boolean; fallbackToEmail: boolean;
};
export type PhoneCall = {
  direction?: 'inbound' | 'outbound';
  id: string; conversationId: string; state: string; kind: string; provider: string; requestedAt: number;
  durationSeconds: number | null; failure: string | null; failureMessage?: string | null; maxSeconds: number; execution: 'fake' | 'provider';
};
export type PhoneSettingsData = {
  inbound?: { available: boolean; phoneNumber: string | null; spending: { usesCredits: boolean; ceilingMilliCredits: number; availableMilliCredits: number | null } };
  available: boolean; providerReady?: boolean; execution?: 'fake' | 'provider'; flags: Record<string, boolean>;
  spending?: { usesCredits: boolean; ceilingMilliCredits: number; availableMilliCredits: number | null };
  number: { lastFour: string; verified: boolean } | null; preferences: PhonePreferences; calls: PhoneCall[];
  schedules: { id: string; schedule: { weekdays: string[]; localTime: string; timeZone: string }; enabled: boolean; nextAt: number }[];
};
export type PhoneInboundCode = { id: string; code: string; expiresAt: number; phoneNumber: string; conversationId: string | null };
export type PhoneInboundStatus = { state: 'ready' | 'used' | 'revoked' | 'expired'; call: PhoneCall | null };
export type PhoneProviderReadiness = {
  ready: boolean; reason?: string; stage?: string; httpStatus?: number;
  maxSeconds?: number; smsReady?: boolean; smsRegistration?: string;
};
export const PHONE_TERMINAL = new Set(['completed', 'busy', 'declined', 'no_answer', 'voicemail', 'failed', 'cancelled']);
