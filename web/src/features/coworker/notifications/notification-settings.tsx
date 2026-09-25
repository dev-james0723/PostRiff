'use client';

import { useId, useState } from 'react';
import { toast } from 'sonner';
import { StateMessage } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { SettingsSection } from '@/features/account/settings-section';
import { FIELD_CLASS, SelectField } from '@/features/workspace/rafii-parts';
import { errorMessage, isFeatureDisabled } from '@/lib/coworker/api';
import { useCoworkerApi, useCoworkerFlag, useNotificationPreferences, useSetPreference } from '@/lib/coworker/hooks';
import type { NotificationPreferences, PreferenceFields, PreferencePatch } from '@/lib/coworker/types';
import { CATEGORY_LABELS } from './labels';
import { PushOptIn } from './push-opt-in';

const MUTE_OPTIONS = [
  { hours: 1, label: '1 hour' },
  { hours: 8, label: '8 hours' },
  { hours: 24, label: '1 day' },
  { hours: 168, label: '1 week' }
];

function toClock(minutes: number | null | undefined): string {
  if (minutes === null || minutes === undefined) return '';
  return `${String(Math.floor(minutes / 60)).padStart(2, '0')}:${String(minutes % 60).padStart(2, '0')}`;
}

function fromClock(value: string): number | null {
  const match = /^(\d{2}):(\d{2})$/.exec(value);
  if (!match) return null;
  const minutes = Number(match[1]) * 60 + Number(match[2]);
  return minutes >= 0 && minutes <= 1439 ? minutes : null;
}

function browserZone() {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  } catch {
    return 'UTC';
  }
}

function row(prefs: NotificationPreferences, scope: string, category: string): PreferenceFields {
  return prefs.rows.find((r) => r.scope === scope && r.category === category) ?? {};
}

/** Transactional categories: their emails always go out, whatever the setting. */
function isTransactional(prefs: NotificationPreferences, category: string) {
  return Object.values(prefs.catalog.events).some((event) => event.category === category && event.transactional);
}

/** What the catalog sends for a category when nobody has chosen: the most immediate of its events. */
function defaultMode(prefs: NotificationPreferences, category: string, channel: 'email' | 'push'): string {
  const modes = Object.values(prefs.catalog.events).filter((e) => e.category === category).map((e) => e[channel]);
  if (modes.includes('immediate')) return 'now';
  if (modes.includes('digest')) return 'digest';
  return 'off';
}

/**
 * Per-person notification preferences for this workspace (coworker spec §14–§18): each category in the app, by
 * email and by push; quiet hours, digest, mute; and this browser's explicit push opt-in with its device list.
 * Hidden when the deployment has the notification centre off.
 */
export function NotificationSettings() {
  const centre = useCoworkerFlag('RAFII_NOTIFICATIONS_V2_ENABLED');
  const prefs = useNotificationPreferences();
  const set = useSetPreference();
  const { w } = useCoworkerApi();
  // With the centre off (or its status unknown) there is nothing to set, and the preferences query never runs.
  if (centre !== true) return null;
  if (prefs.isPending) return <StateMessage kind='loading' title='Loading notification settings…' />;
  if (prefs.isError) {
    if (isFeatureDisabled(prefs.error)) return null;
    return <StateMessage kind='error' title='Notification settings are unavailable right now.' description={errorMessage(prefs.error)} action={<Button variant='glass' size='control' onClick={() => void prefs.refetch()}>Retry</Button>} />;
  }
  const data = prefs.data;

  async function save(patch: PreferencePatch, done: string) {
    try {
      const result = await set.mutateAsync(patch);
      if (!result.verified) toast.warning('Rafii could not confirm that setting. Refresh to see what is stored.');
      else toast.success(done);
    } catch (err) {
      toast.error(errorMessage(err, 'The setting could not be saved.'));
    }
  }

  return (
    <>
      <SettingsSection id='notifications-push' title='Push notifications' description='Optional, per browser. Only what needs you: approvals, failed or uncertain posts, reconnects and a ready week.'>
        <PushOptIn available={data.push.available} vapidPublicKey={data.push.vapidPublicKey} />
      </SettingsSection>
      <CategoryTable prefs={data} workspaceId={w} busy={set.isPending} onSave={save} />
      <QuietHours prefs={data} busy={set.isPending} onSave={save} />
      <MuteAndDigest prefs={data} workspaceId={w} busy={set.isPending} onSave={save} />
    </>
  );
}

type Save = (patch: PreferencePatch, done: string) => Promise<void>;

function CategoryTable({ prefs, workspaceId, busy, onSave }: { prefs: NotificationPreferences; workspaceId: string; busy: boolean; onSave: Save }) {
  const categories = prefs.catalog.categories.filter((c) => CATEGORY_LABELS[c]);
  return (
    <SettingsSection
      id='notifications-categories'
      title='What reaches you'
      description={prefs.email.available ? 'For this workspace. “Default” follows Rafii’s own choice for each kind of message.' : 'For this workspace. Email isn’t set up yet, so only in-app and push apply.'}
      padding='sm'
    >
      <ul className='flex flex-col gap-1' aria-label='Notification categories'>
        {categories.map((category) => {
          const meta = CATEGORY_LABELS[category];
          const effective = prefs.effective[category] ?? {};
          const own = row(prefs, workspaceId, category);
          const transactional = isTransactional(prefs, category);
          const name = meta.label;
          return (
            <li key={category} data-category={category} className='flex flex-col gap-3 rounded-[var(--rafii-radius-control)] px-2 py-3 md:flex-row md:items-center md:justify-between md:gap-4'>
              <div className='min-w-0 md:max-w-[16rem]'>
                <p className='text-foreground text-sm font-medium'>{name}</p>
                <p className='text-muted-foreground text-xs leading-relaxed'>{meta.hint}</p>
              </div>
              <div className='grid grid-cols-[auto_1fr_1fr] items-end gap-3 md:w-[26rem]'>
                <Label className='flex min-h-12 flex-col items-start justify-end gap-2 text-xs font-normal'>
                  <span className='text-muted-foreground'>In app</span>
                  <Switch
                    checked={effective.in_app !== false}
                    disabled={busy}
                    onCheckedChange={(on) => void onSave({ scope: 'workspace', category, in_app: on }, on ? `${name}: shown in the app.` : `${name}: hidden in the app.`)}
                    aria-label={`${name} in the app`}
                  />
                </Label>
                <SelectField
                  label={<span className='text-muted-foreground text-xs font-normal'>Email</span>}
                  aria-label={`${name} by email`}
                  value={transactional ? 'always' : (own.email_mode ?? '')}
                  disabled={busy || transactional || !prefs.email.available}
                  onChange={(e) => void onSave({ scope: 'workspace', category, email_mode: (e.target.value || null) as PreferencePatch['email_mode'] }, `${name}: email updated.`)}
                >
                  {transactional ? (
                    <option value='always'>Always</option>
                  ) : (
                    <>
                      <option value=''>Default ({defaultMode(prefs, category, 'email')})</option>
                      <option value='immediate'>Right away</option>
                      <option value='digest'>In the digest</option>
                      <option value='off'>Off</option>
                    </>
                  )}
                </SelectField>
                <SelectField
                  label={<span className='text-muted-foreground text-xs font-normal'>Push</span>}
                  aria-label={`${name} by push`}
                  value={own.push_mode ?? ''}
                  disabled={busy || !prefs.push.available}
                  onChange={(e) => void onSave({ scope: 'workspace', category, push_mode: (e.target.value || null) as PreferencePatch['push_mode'] }, `${name}: push updated.`)}
                >
                  <option value=''>Default ({defaultMode(prefs, category, 'push')})</option>
                  <option value='immediate'>Right away</option>
                  <option value='off'>Off</option>
                </SelectField>
              </div>
            </li>
          );
        })}
      </ul>
    </SettingsSection>
  );
}

function QuietHours({ prefs, busy, onSave }: { prefs: NotificationPreferences; busy: boolean; onSave: Save }) {
  const global = row(prefs, '*', '*');
  const [start, setStart] = useState(toClock(global.quiet_start ?? null) || '22:00');
  const [end, setEnd] = useState(toClock(global.quiet_end ?? null) || '07:00');
  const [zone, setZone] = useState(global.time_zone || browserZone());
  const uid = useId();
  const active = global.quiet_start !== null && global.quiet_start !== undefined && global.quiet_end !== null && global.quiet_end !== undefined;
  const zones = (() => {
    try {
      return Array.from(new Set([zone, 'UTC', ...Intl.supportedValuesOf('timeZone')]));
    } catch {
      return [zone, 'UTC'];
    }
  })();

  return (
    <SettingsSection
      id='notifications-quiet'
      title='Quiet hours'
      description={active ? `On: ${toClock(global.quiet_start)}–${toClock(global.quiet_end)} (${global.time_zone ?? 'UTC'}). Push waits until they end; security alerts still come through.` : 'Off. Push can arrive at any time.'}
    >
      <div className='grid gap-3 sm:grid-cols-3'>
        <div className='flex flex-col gap-2 text-sm'>
          <label htmlFor={`${uid}-from`} className='text-foreground font-medium'>
            From
          </label>
          <Input id={`${uid}-from`} type='time' value={start} onChange={(e) => setStart(e.target.value)} className={FIELD_CLASS} />
        </div>
        <div className='flex flex-col gap-2 text-sm'>
          <label htmlFor={`${uid}-until`} className='text-foreground font-medium'>
            Until
          </label>
          <Input id={`${uid}-until`} type='time' value={end} onChange={(e) => setEnd(e.target.value)} className={FIELD_CLASS} />
        </div>
        <SelectField label='Time zone' value={zone} onChange={(e) => setZone(e.target.value)}>
          {zones.map((z) => (
            <option key={z} value={z}>
              {z.replace(/_/g, ' ')}
            </option>
          ))}
        </SelectField>
      </div>
      <div className='flex flex-wrap gap-2'>
        <Button
          variant='action'
          size='control'
          disabled={busy || fromClock(start) === null || fromClock(end) === null}
          onClick={() => void onSave({ scope: 'all', category: '*', quiet_start: fromClock(start), quiet_end: fromClock(end), time_zone: zone }, 'Quiet hours saved.')}
        >
          Save quiet hours
        </Button>
        {active && (
          <Button variant='glass' size='control' disabled={busy} onClick={() => void onSave({ scope: 'all', category: '*', quiet_start: null, quiet_end: null }, 'Quiet hours are off.')}>
            Turn off quiet hours
          </Button>
        )}
      </div>
    </SettingsSection>
  );
}

function MuteAndDigest({ prefs, workspaceId, busy, onSave }: { prefs: NotificationPreferences; workspaceId: string; busy: boolean; onSave: Save }) {
  const global = row(prefs, '*', '*');
  const here = row(prefs, workspaceId, '*');
  const [hours, setHours] = useState(8);
  const mutedUntil = here.muted_until && here.muted_until * 1000 > Date.now() ? here.muted_until : null;
  const until = mutedUntil ? new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(mutedUntil * 1000)) : null;

  return (
    <SettingsSection id='notifications-digest' title='Digest and mute' description='A digest gathers the less urgent messages into one email.'>
      <SelectField
        label='Email digest'
        value={global.digest_frequency ?? ''}
        disabled={busy || !prefs.email.available}
        onChange={(e) => void onSave({ scope: 'all', category: '*', digest_frequency: (e.target.value || null) as PreferencePatch['digest_frequency'] }, 'Digest updated.')}
        className='max-w-xs'
      >
        <option value=''>Default (daily)</option>
        <option value='daily'>Daily</option>
        <option value='weekly'>Weekly (Monday)</option>
        <option value='off'>Off</option>
      </SelectField>

      <div className='flex flex-col gap-2'>
        <p className='text-foreground text-sm font-medium'>Mute this workspace</p>
        <p className='text-muted-foreground text-xs' aria-live='polite'>
          {until ? `Muted until ${until}. Nothing is lost: notifications still collect in the app.` : 'Not muted.'}
        </p>
        <div className='flex flex-wrap items-end gap-2'>
          {!mutedUntil && (
            <>
              <SelectField label='Mute for' hideLabel value={String(hours)} onChange={(e) => setHours(Number(e.target.value))} className='w-40'>
                {MUTE_OPTIONS.map((o) => (
                  <option key={o.hours} value={o.hours}>
                    {o.label}
                  </option>
                ))}
              </SelectField>
              <Button variant='glass' size='control' disabled={busy} onClick={() => void onSave({ scope: 'workspace', category: '*', mute_hours: hours }, 'Muted. Email and push pause; the app still collects notifications.')}>
                Mute
              </Button>
            </>
          )}
          {mutedUntil && (
            <Button variant='glass' size='control' disabled={busy} onClick={() => void onSave({ scope: 'workspace', category: '*', mute_hours: null }, 'Unmuted.')}>
              Unmute
            </Button>
          )}
        </div>
      </div>

      {prefs.email.available && (
        <Label className='flex min-h-11 items-start justify-between gap-4 text-sm font-normal'>
          <span className='flex flex-col gap-1'>
            <span className='text-foreground font-medium'>Stop non-essential email</span>
            <span className='text-muted-foreground text-xs leading-relaxed'>Security and billing emails still reach you.</span>
          </span>
          <Switch
            checked={global.email_unsubscribed === true}
            disabled={busy}
            onCheckedChange={(on) => void onSave({ scope: 'all', category: '*', email_unsubscribed: on }, on ? 'Non-essential email is off.' : 'Email is back on.')}
            aria-label='Stop non-essential email'
          />
        </Label>
      )}
    </SettingsSection>
  );
}
