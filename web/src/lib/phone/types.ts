export type PhonePreferences = {
  enabled: boolean; proactiveCalls: boolean; scheduledCalls: boolean; quietStart: number; quietEnd: number;
  timeZone: string; maxCallsPerDay: number; maxMilliCreditsPerCall: number; eventAllowlist: string[]; fallbackToPush: boolean; fallbackToEmail: boolean;
};
export type PhoneCall = {
  id: string; conversationId: string; state: string; kind: string; provider: string; requestedAt: number;
  durationSeconds: number | null; failure: string | null; failureMessage?: string | null; maxSeconds: number; execution: 'fake' | 'provider';
};
export type PhoneSettingsData = {
  available: boolean; providerReady?: boolean; execution?: 'fake' | 'provider'; flags: Record<string, boolean>;
  spending?: { usesCredits: boolean; ceilingMilliCredits: number; availableMilliCredits: number | null };
  number: { lastFour: string; verified: boolean } | null; preferences: PhonePreferences; calls: PhoneCall[];
  schedules: { id: string; schedule: { weekdays: string[]; localTime: string; timeZone: string }; enabled: boolean; nextAt: number }[];
};
export type PhoneProviderReadiness = {
  ready: boolean; reason?: string; stage?: string; httpStatus?: number;
  maxSeconds?: number; smsReady?: boolean; smsRegistration?: string;
};
export const PHONE_TERMINAL = new Set(['completed', 'busy', 'declined', 'no_answer', 'voicemail', 'failed', 'cancelled']);
