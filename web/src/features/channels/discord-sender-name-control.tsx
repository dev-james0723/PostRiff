'use client';

import { useEffect, useId, useRef, useState, type FormEvent } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog';
import { ApiError } from '@/lib/api/client';
import { reportStepUp } from '@/lib/auth/security-step-up';
import { useSignInAgain } from '@/lib/auth/use-sign-in-again';
import type { ChannelView, DiscordSenderProfile, ProviderView } from '@/lib/api/types';
import { keys } from '@/lib/api/hooks';
import { discordCopy } from '@/lib/channels/discord-copy';
import {
  SENDER_LIMIT,
  canCheckAgain,
  checkSenderName,
  classifySenderFeature,
  classifySenderProfile,
  classifySenderRefusal,
  formatRetryTime,
  isSenderNameIssue,
  type BlockedState,
  type SenderFeature,
  type SenderKind,
  type SenderReason,
  type SenderRefusal
} from '@/lib/channels/discord-sender-name';
import { fillCount, senderIssueMessage } from '@/lib/channels/discord-sender-state-copy';
import { usePreferences } from '@/lib/preferences';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { cn } from '@/lib/utils';
import { CONTROL_44, DIALOG_ELEVATED, DIALOG_FOOTER_PLAIN } from './rafii-materials';
import { DiscordMessagePreview, type PreviewNameSource } from './discord-message-preview';
import { SenderStatePanel } from './discord-sender-state-panel';

type Origin = 'open' | 'check' | 'save';

/**
 * Buttons that cannot act right now stay in the tab order with `aria-disabled` and point at their reason with
 * `aria-describedby`, instead of going grey and silent with `disabled`.
 */
const ARIA_DISABLED = 'aria-disabled:cursor-not-allowed aria-disabled:opacity-60';

const describedBy = (...ids: (string | false | null | undefined)[]) => ids.filter(Boolean).join(' ') || undefined;
const isRecord = (value: unknown): value is Record<string, unknown> => typeof value === 'object' && value !== null && !Array.isArray(value);

/** The fields of a failed request that the sender-name states are chosen from. A network failure has no status. */
function refusalOf(cause: unknown): SenderRefusal {
  if (!(cause instanceof ApiError)) return {};
  const body = cause.body ?? {};
  const reasons = Array.isArray(body.reasons)
    ? body.reasons.filter(isRecord).map((reason): SenderReason => ({
        code: String(reason.code),
        ...(typeof reason.retryAfterSeconds === 'number' ? { retryAfterSeconds: reason.retryAfterSeconds } : {})
      }))
    : undefined;
  return {
    status: cause.status,
    code: cause.code,
    reasons,
    retryAfterSeconds: typeof body.retryAfterSeconds === 'number' ? body.retryAfterSeconds : undefined,
    message: cause.message
  };
}

/** Where the shown name came from, as the preview words it. */
function previewSource(profile: DiscordSenderProfile | null, dirty: boolean): PreviewNameSource {
  if (dirty) return 'draft';
  switch (profile?.nameSource) {
    case 'saved_override':
      return 'saved';
    case 'webhook_default':
      return 'webhook_default';
    case 'observed_nickname':
      return 'observed';
    case 'bot_username':
      return 'bot_username';
    case 'none':
      return 'unknown';
    default:
      return profile?.senderKind === 'bot' ? 'observed' : 'saved';
  }
}

export function DiscordSenderNameControl({ channel, provider }: { channel: ChannelView; provider?: ProviderView }) {
  const { workspaceId } = useWorkspaceApi();
  return <SenderNameEditor key={`${workspaceId}:${channel.id}`} channel={channel} provider={provider} />;
}

function SenderNameEditor({ channel, provider }: { channel: ChannelView; provider?: ProviderView }) {
  const { api, workspaceId } = useWorkspaceApi();
  const client = useQueryClient();
  const { locale, timeZone } = usePreferences();
  const copy = discordCopy(locale);
  const signInAgain = useSignInAgain();
  const id = useId();
  const request = useRef(0);
  const inFlight = useRef(false);
  const nameRef = useRef<HTMLInputElement>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState<null | 'loading' | 'saving'>(null);
  const [profile, setProfile] = useState<DiscordSenderProfile | null>(null);
  const [problems, setProblems] = useState<BlockedState[]>([]);
  const [origin, setOrigin] = useState<Origin>('open');
  const [checkedAt, setCheckedAt] = useState<number | null>(null);
  const [name, setName] = useState('');
  const [shared, setShared] = useState(false);
  const [saved, setSaved] = useState(false);
  const [refusal, setRefusal] = useState<string | null>(null);
  const [clock, setClock] = useState(() => Date.now());
  const [focusRequest, setFocusRequest] = useState<{ target: 'name' | 'panel'; serial: number } | null>(null);

  const connectionKind: SenderKind = channel.discordConnectionKind === 'webhook' ? 'webhook' : 'bot';
  const kind: SenderKind = profile?.senderKind ?? connectionKind;
  // The server's two global switches: from the provider view when it carries them, else what an earlier read in this
  // page session learned (shared by every card). They only add a line under the button; the dialog always asks.
  const switchesKey = ['discord-sender-switches', workspaceId] as const;
  const learned = useQuery({ queryKey: switchesKey, queryFn: () => null as SenderFeature | null, enabled: false, staleTime: Infinity, gcTime: Infinity }).data ?? null;
  const switchedOff = classifySenderFeature(provider?.discordSenderNames ?? learned, connectionKind);
  const isBot = kind === 'bot';
  const limit = profile?.rules?.maxLength ?? profile?.maxLength ?? SENDER_LIMIT[kind];
  const check = checkSenderName(name, kind, { limit, forbidden: profile?.rules?.forbiddenCharacters });
  const dirty = profile !== null && name !== profile.name;
  const showIssues = dirty && check.issues.length > 0;
  const editable = profile !== null && problems.length === 0;
  const primary = problems[0] ?? null;
  const guild = channel.discordDestinations?.find((destination) => destination.guildId === profile?.guildId)?.guildName;
  const waiting = primary?.retryAtMs != null && primary.retryAtMs > clock;
  const observedTime = profile?.observedAt != null ? formatRetryTime(profile.observedAt * 1000, locale, timeZone) : null;

  // Why Save cannot be used right now, in the order a person would fix it. null means it can be used.
  const saveWhy: string | null =
    busy === 'saving'
      ? copy.senderSaving
      : busy === 'loading'
        ? copy.senderSaveWhyLoading
        : problems.length > 0
          ? copy.senderSaveWhyBlocked
          : profile === null
            ? copy.senderSaveWhyLoading
            : !dirty
              ? copy.senderSaveWhyUnchanged
              : check.issues.length > 0
                ? copy.senderSaveWhyInvalid
                : isBot && !shared
                  ? copy.senderSaveWhyConfirm
                  : null;

  // After a state arrives, focus moves to the field (editable) or to the explanation (blocked), so a keyboard or
  // screen-reader user lands where the news is. The dialog mounts lazily, so look for the element for a few frames.
  useEffect(() => {
    if (!focusRequest || !open) return;
    let frame = 0;
    let tries = 0;
    const attempt = () => {
      const target = focusRequest.target === 'name' ? nameRef.current : headingRef.current;
      if (target) target.focus();
      else if (tries++ < 30) frame = requestAnimationFrame(attempt);
    };
    frame = requestAnimationFrame(attempt);
    return () => cancelAnimationFrame(frame);
  }, [focusRequest, open]);

  // A held change or a throttle names a time; "Check again" wakes up at it.
  useEffect(() => {
    const at = primary?.retryAtMs;
    if (at == null || at <= clock) return;
    const timer = window.setTimeout(() => setClock(Date.now()), Math.min(at - clock + 50, 2_147_000_000));
    return () => window.clearTimeout(timer);
  }, [primary?.retryAtMs, clock]);

  function focusOn(target: 'name' | 'panel') {
    setFocusRequest((current) => ({ target, serial: (current?.serial ?? 0) + 1 }));
  }

  function apply(next: DiscordSenderProfile, from: Origin) {
    const now = Date.now();
    const blocked = classifySenderProfile(next, now);
    if (next.feature) client.setQueryData(switchesKey, next.feature);
    setProfile(next);
    setName(next.name ?? '');
    setShared(false);
    setOrigin(from);
    setCheckedAt(now);
    setClock(now);
    setProblems(blocked);
    if (blocked.length > 0) focusOn('panel');
    else if (from !== 'save') focusOn('name');
  }

  function explain(cause: unknown, from: Origin) {
    reportStepUp(cause);
    const now = Date.now();
    // Anything that may have reached Discord ends the form: the person reloads (a read) and decides again.
    setProfile(null);
    setName('');
    setShared(false);
    setOrigin(from);
    setCheckedAt(from === 'save' ? null : now);
    setClock(now);
    setProblems(classifySenderRefusal(refusalOf(cause), now));
    focusOn('panel');
  }

  async function load(from: Origin) {
    const current = ++request.current;
    setBusy('loading');
    setRefusal(null);
    setSaved(false);
    try {
      const next = await api.discordSenderProfile(workspaceId, channel.id);
      if (current !== request.current) return;
      apply(next, from);
    } catch (cause) {
      if (current !== request.current) return;
      explain(cause, from);
    } finally {
      if (current === request.current) setBusy(null);
    }
  }

  function show() {
    setOpen(true);
    setSaved(false);
    setRefusal(null);
    setProfile(null);
    setName('');
    setShared(false);
    setProblems([]);
    void load('open');
  }

  async function save() {
    if (!profile || saveWhy !== null || inFlight.current) return;
    inFlight.current = true;
    const current = ++request.current;
    setBusy('saving');
    setRefusal(null);
    setSaved(false);
    try {
      const updated = await api.setDiscordSenderName(workspaceId, channel.id, {
        name,
        fingerprint: profile.fingerprint,
        confirmed: true,
        ...(isBot ? { sharedServerConfirmed: shared } : {})
      });
      if (current !== request.current) return;
      apply(updated, 'save');
      setSaved(true);
      void client.invalidateQueries({ queryKey: keys.channels(workspaceId) });
      void client.invalidateQueries({ queryKey: keys.snapshot(workspaceId) });
      void client.invalidateQueries({ queryKey: keys.audit(workspaceId) });
    } catch (cause) {
      if (current !== request.current) return;
      if (cause instanceof ApiError && cause.status === 400) {
        // Refused before anything was sent to Discord: the fingerprint is still good, so the form stays for a fix.
        const reason = cause.body?.reason;
        setRefusal(
          cause.code === 'discord_sender_name_invalid' && isSenderNameIssue(reason)
            ? senderIssueMessage(copy, reason, check)
            : fillCount(copy.senderIssueSummary, { limit })
        );
        focusOn('name');
      } else {
        explain(cause, 'save');
      }
    } finally {
      inFlight.current = false;
      if (current === request.current) setBusy(null);
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    void save();
  }

  function close() {
    if (busy === 'saving') return;
    request.current++;
    setOpen(false);
    setProfile(null);
    setProblems([]);
    setRefusal(null);
    setSaved(false);
    setBusy(null);
  }

  const panelId = `${id}-state`;
  const scopeId = `${id}-scope`;
  const rulesId = `${id}-rules`;
  const countId = `${id}-count`;
  const issuesId = `${id}-issues`;
  const refusalId = `${id}-refusal`;
  const whyId = `${id}-why`;
  const formId = `${id}-form`;
  const rereadLabel = primary?.key === 'stale' || primary?.key === 'failed' ? copy.senderReload : copy.senderCheckAgain;
  // A failed action is an alert; a state found when the editor opened rides in the persistent live region.
  const asAlert = problems.length > 0 && (origin === 'save' || problems.some((problem) => problem.key === 'failed'));
  const panels = problems.map((problem, index) => (
    <SenderStatePanel
      key={problem.key}
      state={problem}
      kind={kind}
      copy={copy}
      locale={locale}
      timeZone={timeZone}
      nowMs={clock}
      id={`${panelId}-${index}`}
      role={asAlert ? 'alert' : undefined}
      headingRef={index === 0 ? headingRef : undefined}
      checkedAtMs={origin === 'save' || index > 0 ? null : checkedAt}
      actions={
        index > 0 ? undefined : (
          <>
            {problem.signInAgain && (
              <Button type='button' variant='glass' className={CONTROL_44} onClick={() => void signInAgain()}>
                {copy.senderSignInAgain}
              </Button>
            )}
            {canCheckAgain(problem.key) && (
              <Button
                type='button'
                variant='glass'
                className={cn(CONTROL_44, ARIA_DISABLED)}
                aria-disabled={busy !== null || waiting}
                aria-describedby={waiting ? `${panelId}-0-recheck` : undefined}
                data-sender-check-again
                onClick={() => {
                  if (busy === null && !waiting) void load('check');
                }}
              >
                {rereadLabel}
              </Button>
            )}
          </>
        )
      }
    />
  ));

  return (
    <>
      <Button
        variant='glass'
        className={CONTROL_44}
        aria-label={`${copy.senderEdit} · ${channel.account}`}
        aria-haspopup='dialog'
        aria-describedby={switchedOff ? `${id}-card-hint` : undefined}
        data-discord-sender-edit
        data-availability={switchedOff?.key ?? 'unknown'}
        onClick={show}
      >
        {copy.senderEdit}
      </Button>
      {switchedOff && (
        <span id={`${id}-card-hint`} className='text-muted-foreground basis-full text-xs' data-discord-sender-edit-hint>
          {copy.senderCardOff}
        </span>
      )}
      <Dialog
        open={open}
        onOpenChange={(value) => {
          if (busy === 'saving') return;
          if (value) setOpen(true);
          else close();
        }}
      >
        <DialogContent
          showCloseButton={false}
          data-testid='discord-sender-dialog'
          className={cn(DIALOG_ELEVATED, 'max-h-[calc(100dvh-2rem)] overflow-x-hidden overflow-y-auto sm:max-w-lg')}
        >
          <DialogHeader>
            <DialogTitle>{copy.senderEdit}</DialogTitle>
            <DialogDescription>
              {channel.account}. {copy.senderEditDescription}
            </DialogDescription>
          </DialogHeader>
          <form id={formId} onSubmit={submit} noValidate className='flex min-w-0 flex-col gap-4 py-2'>
            <div role='status' aria-live='polite' data-sender-status className='flex min-w-0 flex-col gap-3 empty:hidden'>
              {busy === 'loading' && <p className='text-muted-foreground text-sm'>{copy.senderChecking}</p>}
              {busy === 'saving' && <p className='text-muted-foreground text-sm'>{copy.senderSaving}</p>}
              {saved && !busy && <p className='text-sm'>{copy.senderSaved}</p>}
              {!asAlert && panels}
            </div>
            {asAlert && panels}
            {profile && (
              <>
                <div className='flex min-w-0 flex-col gap-1' id={scopeId}>
                  <p className='text-sm font-medium' data-sender-mode={kind}>
                    {isBot ? copy.senderModeBotLabel : copy.senderModeWebhookLabel}
                  </p>
                  <p className='text-muted-foreground text-sm'>{isBot ? copy.senderBotScope : copy.senderWebhookScope}</p>
                  <p className='text-muted-foreground text-sm [overflow-wrap:anywhere]'>
                    {copy.serverLabel}: {guild ? `${guild} (${profile.guildId})` : profile.guildId}
                  </p>
                  {observedTime && (
                    <p className='text-muted-foreground text-xs' data-sender-observed-at>
                      {copy.senderCheckedAt.replace('{time}', observedTime)}
                    </p>
                  )}
                </div>
                {isBot && profile.externalChange && profile.observedName && (
                  <p className='rounded-lg border p-3 text-sm [overflow-wrap:anywhere]' data-sender-external-change>
                    {copy.senderExternalChange.replace('{name}', profile.observedName)}
                  </p>
                )}
                <div className='flex min-w-0 flex-col gap-2'>
                  <Label htmlFor={`${id}-name`}>{copy.senderNameLabel}</Label>
                  <Input
                    id={`${id}-name`}
                    ref={nameRef}
                    value={name}
                    placeholder={editable ? undefined : copy.senderNameNotKnown}
                    readOnly={!editable || busy !== null}
                    aria-readonly={!editable || busy !== null}
                    aria-invalid={showIssues || refusal !== null}
                    aria-describedby={describedBy(scopeId, editable && rulesId, countId, showIssues && issuesId, refusal !== null && refusalId, problems.length > 0 && `${panelId}-0-body`)}
                    autoComplete='off'
                    autoCapitalize='off'
                    spellCheck={false}
                    enterKeyHint='done'
                    className={cn(CONTROL_44, 'min-w-0', !editable && 'bg-muted/40')}
                    onChange={(event) => {
                      setName(event.target.value);
                      setSaved(false);
                      setRefusal(null);
                    }}
                  />
                  {editable && (
                    <ul id={rulesId} className='text-muted-foreground flex list-disc flex-col gap-0.5 pl-5 text-xs' data-sender-rules>
                      <li>{copy.senderRuleLength.replace('{limit}', String(limit))}</li>
                      <li>{copy.senderRuleSpaces}</li>
                      <li>{copy.senderRuleForbidden}</li>
                      <li>{copy.senderRuleUrl}</li>
                      <li>{copy.senderRuleReserved}</li>
                    </ul>
                  )}
                  {editable ? (
                    <p
                      id={countId}
                      data-sender-count
                      data-over={check.over > 0 ? 'true' : undefined}
                      className={cn('text-xs tabular-nums', check.over > 0 ? 'text-destructive font-medium' : 'text-muted-foreground')}
                    >
                      {fillCount(copy.senderCount, { count: check.length, limit })}
                    </p>
                  ) : (
                    <p id={countId} className='text-muted-foreground text-xs' data-sender-readonly>
                      {copy.senderReadOnlyHint}
                    </p>
                  )}
                  {showIssues && (
                    <ul id={issuesId} className='text-destructive flex list-disc flex-col gap-0.5 pl-5 text-xs' data-sender-issues>
                      {check.issues.map((issue) => (
                        <li key={issue} data-issue={issue}>
                          {senderIssueMessage(copy, issue, check)}
                        </li>
                      ))}
                    </ul>
                  )}
                  {/* Announces when broken rules appear or clear, not on every keystroke (the list holds the numbers). */}
                  <span className='sr-only' role='status' aria-live='polite' data-sender-issues-live>
                    {showIssues ? fillCount(copy.senderIssueSummary, { limit }) : ''}
                  </span>
                  {refusal && (
                    <p id={refusalId} role='alert' className='text-destructive text-xs' data-sender-refusal>
                      {refusal}
                    </p>
                  )}
                </div>
                <DiscordMessagePreview
                  kind={kind}
                  name={dirty ? name : profile.effectiveName ?? (profile.name || null)}
                  nameSource={previewSource(profile, dirty)}
                  badge={profile.preview?.badge}
                  queuedKeepsName={profile.preview?.queuedPostsKeepApprovedName}
                  queuedFollowsNickname={profile.preview?.queuedPostsFollowCurrentNickname}
                  copy={copy}
                  locale={locale}
                  timeZone={timeZone}
                  heading={copy.senderPreview}
                  themeToggle
                />
                {isBot && editable && (
                  <label className='flex min-h-11 items-start gap-3 text-sm'>
                    <input
                      type='checkbox'
                      className='mt-1 size-4 shrink-0'
                      checked={shared}
                      disabled={busy !== null}
                      aria-labelledby={`${id}-shared`}
                      onChange={(event) => setShared(event.target.checked)}
                    />
                    <span id={`${id}-shared`}>{copy.senderSharedConfirm}</span>
                  </label>
                )}
              </>
            )}
            <p id={whyId} className='text-muted-foreground text-xs' data-sender-save-why={saveWhy ? 'true' : undefined}>
              {saveWhy}
            </p>
          </form>
          <DialogFooter className={DIALOG_FOOTER_PLAIN}>
            <Button
              type='button'
              variant='glass'
              className={cn(CONTROL_44, ARIA_DISABLED)}
              aria-disabled={busy === 'saving'}
              aria-describedby={busy === 'saving' ? whyId : undefined}
              onClick={close}
            >
              {copy.senderClose}
            </Button>
            <Button
              type='submit'
              form={formId}
              className={cn(CONTROL_44, ARIA_DISABLED)}
              aria-disabled={saveWhy !== null}
              aria-describedby={saveWhy !== null ? whyId : undefined}
              data-sender-save
            >
              {copy.senderSave}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
