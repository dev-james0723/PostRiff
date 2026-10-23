import type { DiscordCopy } from './discord-copy';
import { formatRetryTime, type SenderNameIssue, type SenderStateKey } from './discord-sender-name';

type CopyKey = keyof DiscordCopy;
export type BlockedStateKey = Exclude<SenderStateKey, 'ready'>;

/**
 * Which copy lines explain each state. Four states reuse the long-standing lines the editor already shipped
 * (`senderChangePending`, `senderSessionError`, `senderPermissionError`, `senderSaveFailed`) as their body, so
 * existing wording and tests keep meaning the same thing. Every state has a title, a body and a "what you can do".
 */
export const SENDER_STATE_COPY: Record<BlockedStateKey, { title: CopyKey; body: CopyKey; next: CopyKey }> = {
  feature_disabled: { title: 'senderStateFeatureDisabledTitle', body: 'senderStateFeatureDisabledBody', next: 'senderStateFeatureDisabledNext' },
  bot_nickname_disabled: { title: 'senderStateBotNicknameDisabledTitle', body: 'senderStateBotNicknameDisabledBody', next: 'senderStateBotNicknameDisabledNext' },
  not_authorizing_member: { title: 'senderStateNotAuthorizingMemberTitle', body: 'senderStateNotAuthorizingMemberBody', next: 'senderStateNotAuthorizingMemberNext' },
  member_lacks_manage_nicknames: {
    title: 'senderStateMemberLacksManageNicknamesTitle',
    body: 'senderStateMemberLacksManageNicknamesBody',
    next: 'senderStateMemberLacksManageNicknamesNext'
  },
  bot_lacks_change_nickname: { title: 'senderStateBotLacksChangeNicknameTitle', body: 'senderStateBotLacksChangeNicknameBody', next: 'senderStateBotLacksChangeNicknameNext' },
  nickname_managed_elsewhere: {
    title: 'senderStateNicknameManagedElsewhereTitle',
    body: 'senderStateNicknameManagedElsewhereBody',
    next: 'senderStateNicknameManagedElsewhereNext'
  },
  edit_pending: { title: 'senderStateEditPendingTitle', body: 'senderChangePending', next: 'senderStateEditPendingNext' },
  stale: { title: 'senderStateStaleTitle', body: 'senderStateStaleBody', next: 'senderStateStaleNext' },
  step_up_required: { title: 'senderStateStepUpRequiredTitle', body: 'senderSessionError', next: 'senderStateStepUpRequiredNext' },
  reconnect_required: { title: 'senderStateReconnectRequiredTitle', body: 'senderStateReconnectRequiredBody', next: 'senderStateReconnectRequiredNext' },
  permission_unclear: { title: 'senderStatePermissionUnclearTitle', body: 'senderPermissionError', next: 'senderStatePermissionUnclearNext' },
  failed: { title: 'senderStateFailedTitle', body: 'senderSaveFailed', next: 'senderStateFailedNext' }
};

export const BLOCKED_STATES = Object.keys(SENDER_STATE_COPY) as BlockedStateKey[];

export function senderStateCopy(copy: DiscordCopy, key: BlockedStateKey): { title: string; body: string; next: string } {
  const lines = SENDER_STATE_COPY[key];
  return { title: copy[lines.title], body: copy[lines.body], next: copy[lines.next] };
}

/** "Rafii can check again at 2:32 PM." / "...in about two minutes." / "...now." for a change that is still being confirmed. */
export function recheckLine(copy: DiscordCopy, retryAt: number | null, locale: string, timeZone?: string, nowMs: number = Date.now()): string {
  if (retryAt === null) return copy.senderRecheckSoon;
  if (retryAt * 1000 <= nowMs) return copy.senderRecheckNow;
  const time = formatRetryTime(retryAt, locale, timeZone);
  return time ? copy.senderRecheckAt.replace('{time}', time) : copy.senderRecheckSoon;
}

const ISSUE_COPY: Record<SenderNameIssue, CopyKey> = {
  empty: 'senderIssueEmpty',
  surrounding_space: 'senderIssueSpace',
  too_long: 'senderIssueTooLong',
  not_nfc: 'senderIssueNotNfc',
  control_character: 'senderIssueControl',
  reserved_word: 'senderRuleWebhookReserved'
};

/** The message for one broken rule, with the numbers filled in. */
export function senderIssueMessage(copy: DiscordCopy, issue: SenderNameIssue, numbers: { length: number; limit: number; over: number }): string {
  return copy[ISSUE_COPY[issue]]
    .replace('{length}', String(numbers.length))
    .replace('{limit}', String(numbers.limit))
    .replace('{over}', String(numbers.over));
}

/** `{limit}` / `{count}` placeholders in the shorter lines. */
export function fillCount(text: string, values: { count?: number; limit?: number }): string {
  return text.replace('{count}', String(values.count ?? '')).replace('{limit}', String(values.limit ?? ''));
}
