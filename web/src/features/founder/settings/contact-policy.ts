import type { ContactPolicy } from '../customers/kit/types';
import { clockToMinutes, minutesToClock } from '../customers/kit/format';

export interface ContactDraft {
  liveDeliveryEnabled: boolean;
  channels: string[];
  quietStart: string;
  quietEnd: string;
  timeZone: string;
  dailyCap: string;
  concurrentCap: string;
  eventAllowlist: string[];
  budgetMode: 'limited' | 'unlimited';
  budgetUsd: string;
}

export function draftFromPolicy(policy: ContactPolicy): ContactDraft {
  return { liveDeliveryEnabled: policy.liveDeliveryEnabled, channels: [...policy.channels],
    quietStart: minutesToClock(policy.quietStart), quietEnd: minutesToClock(policy.quietEnd), timeZone: policy.timeZone,
    dailyCap: String(policy.dailyCap), concurrentCap: String(policy.concurrentCap), eventAllowlist: [...policy.eventAllowlist],
    budgetMode: policy.budgetUsdMicroDaily === null ? 'unlimited' : 'limited',
    budgetUsd: String((policy.budgetUsdMicroDaily ?? 50_000_000) / 1_000_000) };
}

export function policyFromDraft(policy: ContactPolicy, draft: ContactDraft): { policy: ContactPolicy } | { error: string } {
  const quietStart = clockToMinutes(draft.quietStart), quietEnd = clockToMinutes(draft.quietEnd);
  if (quietStart === null || quietEnd === null) return { error: 'Quiet hours need a start and an end time (HH:MM).' };
  const dailyCap = Number(draft.dailyCap), concurrentCap = Number(draft.concurrentCap);
  if (!draft.dailyCap.trim() || !Number.isInteger(dailyCap) || dailyCap < 0 || dailyCap > 100) return { error: 'Daily cap must be a whole number from 0 to 100.' };
  if (!draft.concurrentCap.trim() || !Number.isInteger(concurrentCap) || concurrentCap < 0 || concurrentCap > 10) return { error: 'Concurrent cap must be a whole number from 0 to 10.' };
  const budget = Number(draft.budgetUsd);
  if (draft.budgetMode === 'limited' && (!draft.budgetUsd.trim() || !Number.isFinite(budget) || budget < 0 || budget > 10_000)) return { error: 'Daily call budget must be from $0 to $10,000, or Unlimited.' };
  try { new Intl.DateTimeFormat('en', { timeZone: draft.timeZone.trim() }); }
  catch { return { error: 'A valid IANA time zone is required.' }; }
  return { policy: { ...policy, liveDeliveryEnabled: draft.liveDeliveryEnabled, channels: [...draft.channels],
    quietStart, quietEnd, timeZone: draft.timeZone.trim(), dailyCap, concurrentCap, eventAllowlist: [...draft.eventAllowlist],
    budgetUsdMicroDaily: draft.budgetMode === 'unlimited' ? null : Math.round(budget * 1_000_000) } };
}
