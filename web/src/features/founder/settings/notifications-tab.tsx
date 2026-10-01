'use client';

import Link from 'next/link';
import { useEffect, useId, useState, type FormEvent, type ReactNode } from 'react';
import { toast } from 'sonner';
import { Icons } from '@/components/icons';
import { StateMessage } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Band, FIELD_CLASS, Panel, SelectField, StatusChip } from '@/features/workspace/rafii-parts';
import { signInHref } from '@/lib/founder/api';
import { cn } from '@/lib/utils';
import { useCapability, useFounderScope } from '../customers/kit/api';
import { whenDateTime } from '../customers/kit/format';
import { QueryState } from '../customers/kit/page-frame';
import { founderSafeHref } from '../shared/safe-href';
import {
  blockerCopy,
  draftFromPreferences,
  EVENT_LABEL,
  NOTICE_EVENTS,
  noticeChannelLines,
  preferencesPatch,
  readinessLine,
  routeSummary,
  severityStatus,
  type ChannelReadiness,
  type NoticeChannel,
  type PreferencesData,
  type PreferencesDraft
} from './comms';
import { randomKey, useMarkNoticeRead, useNoticePreferences, useNotices, useSaveNoticePreferences, useTestNotice, writeFailureOf } from './comms-hooks';

/**
 * Settings → Notifications (CONTRACTS §8.E, PRD §6.7). Founder notices always land in-app; email and push go out only when
 * the contact policy lists the channel with live delivery on, the server flag is set and the outbox has a transport —
 * each channel shows exactly which of those gates is closed, by code. Preferences narrow what a notice may use (never
 * widen it), the daily digest collects what is not urgent, and quiet hours hold everything but critical and security
 * notices. A test notice proves the in-app path without any external effect.
 */

const RETURN_TO = '/founder/settings?tab=notifications';
const CHANNEL_LABEL: Record<'inApp' | NoticeChannel, string> = { inApp: 'In-app', email: 'Email', push: 'Push' };

function SignInAgain({ message }: { message: string }) {
  return (
    <StateMessage
      kind='permission'
      layout='inline'
      title='Sign in again to make this change'
      description={message}
      action={
        <a href={signInHref(RETURN_TO)} className='rafii-focus text-foreground rounded text-sm font-medium underline underline-offset-4'>
          Sign in again
        </a>
      }
    />
  );
}

function ChannelCard({ channel, readiness, installed }: { channel: 'inApp' | NoticeChannel; readiness: ChannelReadiness | undefined; installed: boolean }) {
  const ready = Boolean(readiness?.ready) && (channel !== 'inApp' || installed);
  const codes = channel === 'inApp' ? (installed ? [] : ['notifications_not_installed']) : (readiness?.blockers ?? []);
  return (
    <li className='min-w-0'>
      <Band className='h-full gap-2'>
        <div className='flex flex-wrap items-center justify-between gap-2'>
          <span className='text-foreground text-sm font-medium'>{CHANNEL_LABEL[channel]}</span>
          <StatusChip status={ready ? 'success' : 'neutral'} icon={ready ? 'check' : 'lock'}>
            {ready ? 'Ready' : 'Off'}
          </StatusChip>
        </div>
        <p className='text-muted-foreground text-xs'>{channel === 'inApp' && !installed ? blockerCopy('notifications_not_installed') : readinessLine(channel, readiness)}</p>
        {codes.length > 0 && (
          <ul className='flex flex-col gap-1' aria-label={`${CHANNEL_LABEL[channel]} blockers`}>
            {codes.map((code) => (
              <li key={code} className='text-muted-foreground text-xs break-words'>
                <code className='text-foreground font-mono'>{code}</code> — {blockerCopy(code, channel === 'inApp' ? undefined : channel)}
              </li>
            ))}
          </ul>
        )}
      </Band>
    </li>
  );
}

function ChannelReadinessList({ data }: { data: PreferencesData }) {
  return (
    <div className='flex flex-col gap-3'>
      <ul className='grid gap-3 md:grid-cols-3'>
        {(['inApp', 'email', 'push'] as const).map((channel) => (
          <ChannelCard key={channel} channel={channel} readiness={data.readiness?.[channel]} installed={data.installed} />
        ))}
      </ul>
      <p className='text-muted-foreground text-xs'>
        Contact & calls: live delivery {data.policy.liveDeliveryEnabled ? 'on' : 'off'}, channels {data.policy.channels.length ? data.policy.channels.join(', ') : 'none listed'} (policy revision {data.policy.revision}). Server flags: email{' '}
        {data.flags.founderEmailEnabled ? 'set' : 'not set'}, push {data.flags.founderPushEnabled ? 'set' : 'not set'}.
      </p>
    </div>
  );
}

function Check({ label, name, checked, onChange, disabled }: { label: string; name?: string; checked: boolean; onChange: (next: boolean) => void; disabled?: boolean }) {
  return (
    <label className={cn('rafii-quiet flex min-h-11 items-center gap-2 rounded-[var(--rafii-radius-control)] px-3 py-2 text-sm', checked && 'rafii-glass-selected', disabled && 'opacity-60')}>
      <input type='checkbox' aria-label={name ?? label} checked={checked} disabled={disabled} onChange={(event) => onChange(event.target.checked)} className='accent-foreground size-4' />
      {label}
    </label>
  );
}

function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className='flex min-w-0 flex-col gap-1.5 text-sm'>
      <span className='text-foreground font-medium'>{label}</span>
      {children}
      {hint && <span className='text-muted-foreground text-xs'>{hint}</span>}
    </label>
  );
}

function PreferencesForm({ data }: { data: PreferencesData }) {
  const save = useSaveNoticePreferences();
  const canSettings = useCapability('control.settings');
  const preferences = data.preferences;
  const [draft, setDraft] = useState<PreferencesDraft>(() => draftFromPreferences(preferences));
  const [revision, setRevision] = useState(preferences.revision);
  const [problem, setProblem] = useState<{ kind: string; message: string } | null>(null);
  const noteId = useId();

  useEffect(() => {
    if (preferences.revision !== revision) {
      setDraft(draftFromPreferences(preferences));
      setRevision(preferences.revision);
    }
  }, [preferences, revision]);

  const routes = new Map(data.events.map((event) => [event.type, event] as const));
  const locked = !data.installed || !canSettings;

  async function submit(event: FormEvent) {
    event.preventDefault();
    const next = preferencesPatch(draft);
    if ('error' in next) {
      setProblem({ kind: 'validation', message: next.error });
      return;
    }
    setProblem(null);
    try {
      await save.mutateAsync(next.patch);
      toast.success('Notification preferences saved.');
    } catch (cause) {
      setProblem(writeFailureOf(cause));
    }
  }

  const setEvent = (name: string, channel: NoticeChannel, value: boolean) => setDraft({ ...draft, events: { ...draft.events, [name]: { ...draft.events[name], [channel]: value } } });

  return (
    <form onSubmit={(event) => void submit(event)} className='flex flex-col gap-5' aria-describedby={noteId}>
      <fieldset className='flex flex-col gap-3'>
        <legend className='text-foreground mb-1 text-sm font-medium'>Email and push for each notice</legend>
        <ul className='flex flex-col gap-3'>
          {NOTICE_EVENTS.map((name) => {
            const label = EVENT_LABEL[name] ?? name;
            const route = routes.get(name);
            return (
              <li key={name} className='min-w-0'>
                <Band className='gap-2'>
                  <div className='flex flex-col gap-0.5'>
                    <span className='text-foreground text-sm font-medium'>{label}</span>
                    {route && (
                      <span className='text-muted-foreground text-xs break-words'>
                        {Object.entries(route.routes)
                          .map(([severity, value]) => `${severity}: ${routeSummary(value).toLowerCase()}`)
                          .join(' · ')}
                      </span>
                    )}
                  </div>
                  <div className='flex flex-wrap gap-2' role='group' aria-label={`${label} channels`}>
                    <Check label='Email' name={`Email for ${label}`} checked={Boolean(draft.events[name]?.email)} onChange={(value) => setEvent(name, 'email', value)} disabled={locked} />
                    <Check label='Push' name={`Push for ${label}`} checked={Boolean(draft.events[name]?.push)} onChange={(value) => setEvent(name, 'push', value)} disabled={locked} />
                  </div>
                </Band>
              </li>
            );
          })}
        </ul>
      </fieldset>

      <fieldset className='flex flex-col gap-3'>
        <legend className='text-foreground mb-1 text-sm font-medium'>Daily digest</legend>
        <div className='flex flex-wrap gap-2'>
          <Check label='Collect non-urgent notices in a daily digest' checked={draft.digestEnabled} onChange={(value) => setDraft({ ...draft, digestEnabled: value })} disabled={locked} />
          <Check label='Email the digest' checked={draft.digestEmail} onChange={(value) => setDraft({ ...draft, digestEmail: value })} disabled={locked} />
        </div>
        <SelectField label='Digest hour (your time zone below)' value={draft.digestHour} onChange={(event) => setDraft({ ...draft, digestHour: event.target.value })} disabled={locked} className='sm:max-w-xs'>
          {Array.from({ length: 24 }, (_, hour) => (
            <option key={hour} value={String(hour)}>
              {`${String(hour).padStart(2, '0')}:00`}
            </option>
          ))}
        </SelectField>
      </fieldset>

      <fieldset className='flex flex-col gap-3'>
        <legend className='text-foreground mb-1 text-sm font-medium'>Quiet hours</legend>
        <p className='text-muted-foreground text-xs'>During quiet hours email waits for the digest and push stays off. Critical and security notices still come through.</p>
        <div className='grid gap-4 sm:grid-cols-3'>
          <Field label='Start'>
            <Input type='time' value={draft.quietStart} onChange={(event) => setDraft({ ...draft, quietStart: event.target.value })} className={FIELD_CLASS} disabled={locked} />
          </Field>
          <Field label='End'>
            <Input type='time' value={draft.quietEnd} onChange={(event) => setDraft({ ...draft, quietEnd: event.target.value })} className={FIELD_CLASS} disabled={locked} />
          </Field>
          <Field label='Time zone' hint='An IANA name, such as America/Indiana/Indianapolis.'>
            <Input value={draft.timeZone} onChange={(event) => setDraft({ ...draft, timeZone: event.target.value })} className={FIELD_CLASS} autoComplete='off' disabled={locked} />
          </Field>
        </div>
      </fieldset>

      {problem &&
        (problem.kind === 'step_up' ? (
          <SignInAgain message={problem.message} />
        ) : (
          <StateMessage kind={problem.kind === 'permission' ? 'permission' : problem.kind === 'not_installed' ? 'partial' : 'error'} layout='inline' title={problem.message} />
        ))}
      <div className='flex flex-wrap items-center gap-3'>
        <Button type='submit' variant='action' size='control' disabled={save.isPending || locked}>
          {save.isPending ? <Icons.spinner className='animate-spin' /> : <Icons.check />} Save preferences
        </Button>
        <span id={noteId} className='text-muted-foreground text-xs'>
          {!data.installed
            ? blockerCopy('notifications_not_installed')
            : !canSettings
              ? 'Changing preferences needs the control.settings capability with a fresh second factor.'
              : `Revision ${preferences.revision}${preferences.updatedAt ? ` · updated ${whenDateTime(preferences.updatedAt)}` : ' · defaults'} · saving needs a second factor from the last five minutes. Preferences can only narrow where a notice goes.`}
        </span>
      </div>
    </form>
  );
}

function NoticeList() {
  const scope = useFounderScope();
  const query = useNotices();
  const test = useTestNotice();
  const markRead = useMarkNoticeRead();
  const [outcome, setOutcome] = useState<ReactNode>(null);
  const live = scope.mode === 'live';
  const installed = query.data ? query.data.installed !== false && query.data.mode === 'live' : false;

  async function sendTest() {
    setOutcome(null);
    try {
      const result = await test.mutateAsync(randomKey());
      setOutcome(
        <StateMessage
          kind='success'
          layout='inline'
          title={result.replayed ? 'That test notice was already recorded' : 'Test notice added'}
          description={`It is in the list below and in your Rafii notifications; ${result.unread} unread now. Nothing was emailed or pushed.`}
        />
      );
    } catch (error) {
      const failure = writeFailureOf(error);
      setOutcome(<StateMessage kind={failure.kind === 'not_installed' ? 'partial' : failure.kind === 'permission' ? 'permission' : 'error'} layout='inline' title='The test notice was not added' description={failure.message} />);
    }
  }

  return (
    <div className='flex flex-col gap-3'>
      <div className='flex flex-wrap items-center gap-2'>
        <Button variant='glass' size='control' onClick={() => void sendTest()} disabled={!live || !installed || test.isPending}>
          {test.isPending ? <Icons.spinner className='animate-spin' /> : <Icons.notification />} Send a test notice
        </Button>
        <span className='text-muted-foreground text-xs'>{live ? 'In-app only: it proves the notice path without emailing or pushing anything.' : 'Switch to Live to send one. Demo has no founder notices.'}</span>
      </div>
      {outcome}
      <QueryState query={query} label='notices' layout='inline'>
        {(data) =>
          data.mode === 'demo' ? (
            <StateMessage kind='unsupported' layout='inline' title='Demo has no founder notices' description='Notices are never simulated, and Live notices are not shown in Demo.' />
          ) : data.installed === false ? (
            <StateMessage kind='partial' layout='inline' title='Founder notices are not installed yet' description={blockerCopy('notifications_not_installed')} />
          ) : data.notices.length === 0 ? (
            <StateMessage kind='empty' layout='inline' title='No founder notices yet' description='Incidents, recoveries, finished briefings and unavailable sources appear here as they happen.' />
          ) : (
            <div className='flex flex-col gap-2'>
              <p className='text-muted-foreground text-xs'>
                {data.unread} unread · newest {data.notices.length} shown
              </p>
              <ul className='flex flex-col gap-2'>
                {data.notices.map((notice) => {
                  const href = founderSafeHref(notice.href);
                  return (
                    <li key={notice.id} className='min-w-0'>
                      <Band className='gap-2'>
                        <div className='flex flex-wrap items-center gap-2'>
                          <StatusChip status={severityStatus(notice.severity)}>{notice.severity}</StatusChip>
                          {!notice.read && (
                            <StatusChip status='info' icon={null}>
                              Unread
                            </StatusChip>
                          )}
                          <span className='text-muted-foreground text-xs'>
                            {EVENT_LABEL[notice.type] ?? notice.type} · {whenDateTime(notice.createdAt)}
                          </span>
                        </div>
                        {href ? (
                          <Link href={href} className='rafii-focus text-foreground rounded text-sm font-medium break-words underline-offset-4 hover:underline'>
                            {notice.title}
                          </Link>
                        ) : (
                          <p className='text-foreground text-sm font-medium break-words'>{notice.title}</p>
                        )}
                        <p className='text-muted-foreground text-xs break-words'>{noticeChannelLines(notice).join(' · ')}</p>
                        {!notice.read && (
                          <Button type='button' variant='quiet' size='sm' className='self-start' onClick={() => markRead.mutate(notice.id)} disabled={markRead.isPending} aria-label={`Mark “${notice.title}” read`}>
                            Mark read
                          </Button>
                        )}
                      </Band>
                    </li>
                  );
                })}
              </ul>
            </div>
          )
        }
      </QueryState>
    </div>
  );
}

export function NotificationsTab() {
  const query = useNoticePreferences();
  return (
    <div className='flex flex-col gap-4'>
      <Panel title='Channels' description='Where founder notices can reach you right now. Email and push need live delivery and the channel in Contact & calls, the server flag, and an outbox transport.'>
        <QueryState query={query} label='channel readiness' layout='inline'>
          {(data) => <ChannelReadinessList data={data} />}
        </QueryState>
      </Panel>
      <Panel title='Preferences' description='Which notices may use email and push, the daily digest, and quiet hours. The same in Live and Demo.'>
        <QueryState query={query} label='notification preferences' layout='inline'>
          {(data) => <PreferencesForm data={data} />}
        </QueryState>
      </Panel>
      <Panel title='Notices' description='Your founder notices, newest first.'>
        <NoticeList />
      </Panel>
    </div>
  );
}
