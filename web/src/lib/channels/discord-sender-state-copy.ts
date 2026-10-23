import type { DiscordCopy } from './discord-copy';
import { formatRetryTime, formatWait, type BlockedSenderState, type SenderNameIssue } from './discord-sender-name';

type CopyKey = keyof DiscordCopy;

/**
 * Which copy lines explain each state. Three states reuse the long-standing lines the editor already shipped
 * (`senderChangePending`, `senderSessionError`, `senderSaveFailed`) as their body, so existing wording keeps meaning
 * the same thing. Every state has a title, a body and a "what you can do".
 */
export const SENDER_STATE_COPY: Record<BlockedSenderState, { title: CopyKey; body: CopyKey; next: CopyKey }> = {
  sender_names_disabled: { title: 'senderStateSenderNamesDisabledTitle', body: 'senderStateSenderNamesDisabledBody', next: 'senderStateSenderNamesDisabledNext' },
  bot_nickname_disabled: { title: 'senderStateBotNicknameDisabledTitle', body: 'senderStateBotNicknameDisabledBody', next: 'senderStateBotNicknameDisabledNext' },
  not_authorizing_member: { title: 'senderStateNotAuthorizingMemberTitle', body: 'senderStateNotAuthorizingMemberBody', next: 'senderStateNotAuthorizingMemberNext' },
  session_reverification_required: { title: 'senderStateSessionReverificationRequiredTitle', body: 'senderSessionError', next: 'senderStateSessionReverificationRequiredNext' },
  person_missing_manage_nicknames: {
    title: 'senderStatePersonMissingManageNicknamesTitle',
    body: 'senderStatePersonMissingManageNicknamesBody',
    next: 'senderStatePersonMissingManageNicknamesNext'
  },
  person_role_below_bot: { title: 'senderStatePersonRoleBelowBotTitle', body: 'senderStatePersonRoleBelowBotBody', next: 'senderStatePersonRoleBelowBotNext' },
  bot_missing_change_nickname: { title: 'senderStateBotMissingChangeNicknameTitle', body: 'senderStateBotMissingChangeNicknameBody', next: 'senderStateBotMissingChangeNicknameNext' },
  nickname_authority_other_workspace: {
    title: 'senderStateNicknameAuthorityOtherWorkspaceTitle',
    body: 'senderStateNicknameAuthorityOtherWorkspaceBody',
    next: 'senderStateNicknameAuthorityOtherWorkspaceNext'
  },
  edit_pending: { title: 'senderStateEditPendingTitle', body: 'senderChangePending', next: 'senderStateEditPendingNext' },
  stale: { title: 'senderStateStaleTitle', body: 'senderStateStaleBody', next: 'senderStateStaleNext' },
  reconnect_required: { title: 'senderStateReconnectRequiredTitle', body: 'senderStateReconnectRequiredBody', next: 'senderStateReconnectRequiredNext' },
  rate_limited: { title: 'senderStateRateLimitedTitle', body: 'senderStateRateLimitedBody', next: 'senderStateRateLimitedNext' },
  upstream_unavailable: { title: 'senderStateUpstreamUnavailableTitle', body: 'senderStateUpstreamUnavailableBody', next: 'senderStateUpstreamUnavailableNext' },
  workspace_permission: { title: 'senderStateWorkspacePermissionTitle', body: 'senderStateWorkspacePermissionBody', next: 'senderStateWorkspacePermissionNext' },
  failed: { title: 'senderStateFailedTitle', body: 'senderSaveFailed', next: 'senderStateFailedNext' }
};

export const BLOCKED_STATES = Object.keys(SENDER_STATE_COPY) as BlockedSenderState[];

export function senderStateCopy(copy: DiscordCopy, key: BlockedSenderState): { title: string; body: string; next: string } {
  const lines = SENDER_STATE_COPY[key];
  return { title: copy[lines.title], body: copy[lines.body], next: copy[lines.next] };
}

/**
 * "Rafii can check again in about 90 seconds, at 2:32 PM." for a held change or a throttle: the wait the server named
 * (`retryAfterSeconds`) and the clock time it ends; "...now." once that time has passed; "...in about two minutes."
 * when the server named no wait.
 */
export function recheckLine(
  copy: DiscordCopy,
  state: { retryAtMs: number | null; retryAfterSeconds: number | null },
  locale: string,
  timeZone?: string,
  nowMs: number = Date.now()
): string {
  if (state.retryAtMs === null) return copy.senderRecheckSoon;
  if (state.retryAtMs <= nowMs) return copy.senderRecheckNow;
  const time = formatRetryTime(state.retryAtMs, locale, timeZone);
  if (!time) return copy.senderRecheckSoon;
  if (state.retryAfterSeconds === null) return copy.senderRecheckAt.replace('{time}', time);
  return copy.senderRecheckIn.replace('{wait}', formatWait(state.retryAfterSeconds, locale)).replace('{time}', time);
}

const ISSUE_COPY: Record<SenderNameIssue, CopyKey> = {
  empty: 'senderIssueEmpty',
  surrounding_space: 'senderIssueSpace',
  not_normalized: 'senderIssueNotNormalized',
  too_long: 'senderIssueTooLong',
  control_or_format: 'senderIssueControl',
  spacing: 'senderIssueSpacing',
  invisible: 'senderIssueInvisible',
  forbidden_character: 'senderIssueForbidden',
  url_like: 'senderIssueUrl',
  reserved_word: 'senderIssueReserved'
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
