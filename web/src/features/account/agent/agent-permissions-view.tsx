'use client';

import { useEffect, useRef, useState } from 'react';
import PageContainer from '@/components/layout/page-container';
import { Icons } from '@/components/icons';
import { RafiiDialog, RafiiDialogBody, RafiiDialogContent, RafiiDialogFooter, RafiiDialogHeader, SegmentedControl, StateMessage } from '@/components/rafii';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Switch } from '@/components/ui/switch';
import type { AgentPermissionsView as View, CategoryId, PresetId, ScopeChanges, SpendConfirmation, StatePreset } from '@/lib/api/agent-permissions-types';
import {
  CATEGORY_ORDER,
  CHOICE_LABEL,
  PRESET_ORDER,
  SPEND_ORDER,
  STATE_LABEL,
  categoryChoice,
  categoryScope,
  currentPreset,
  historyLine,
  needsFreshSignIn,
  notRecallable,
  presetTitle,
  type CategoryChoice
} from '@/lib/agent-permissions/model';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import { useSignInAgain } from '@/lib/auth/use-sign-in-again';
import { cn } from '@/lib/utils';
import { SettingsSection } from '../settings-section';
import {
  permissionsOff,
  useAgentPermissionChanges,
  useAgentPermissionHistory,
  useAgentPermissionMembers,
  useAgentPermissions,
  type Choice,
  type SaveOutcome
} from './use-agent-permissions';

const HOLD_MS = 1500;

function when(at: number | null | undefined) {
  if (!at) return '';
  return new Date(at * 1000).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
}

/** Settings → Rafii Agent → Permissions (rafii-agent-authz/1, CF-2 §17). */
export function AgentPermissionsView() {
  const query = useAgentPermissions();
  return (
    <PageContainer pageTitle='Rafii Agent' pageDescription='Choose what Rafii may do for you in this workspace.' width='reading'>
      {permissionsOff(query) ? (
        <StateMessage
          kind='unsupported'
          title='Permission settings aren’t available here yet'
          description='Rafii works the way it always has in this workspace. Nothing changes until these settings are turned on.'
        />
      ) : query.isPending ? (
        <StateMessage kind='loading' title='Loading Rafii’s permissions' />
      ) : query.error || !query.data ? (
        <StateMessage
          kind='error'
          title='Couldn’t load Rafii’s permissions'
          description={query.error instanceof Error ? query.error.message : 'Try again in a moment.'}
          action={<Button variant='glass' size='control' onClick={() => void query.refetch()}>Try again</Button>}
        />
      ) : (
        <Permissions view={query.data} />
      )}
    </PageContainer>
  );
}

function Permissions({ view }: { view: View }) {
  const changes = useAgentPermissionChanges();
  const signInAgain = useSignInAgain();
  const access = useWorkspaceAccess();
  const manager = checkAccess(access, { permission: 'manage_members' });
  const [preset, setPreset] = useState<PresetId | null>(null);
  const [edits, setEdits] = useState<ScopeChanges>({});
  const [spend, setSpend] = useState<SpendConfirmation | null>(null);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState('');
  const [confirming, setConfirming] = useState<Choice | null>(null);
  const [signIn, setSignIn] = useState<string | null>(null);

  const current = currentPreset(view);
  const chosen: StatePreset = preset ?? current;
  const custom = chosen === 'custom';
  const dirty = preset !== null && (preset !== current || Object.keys(edits).length > 0 || spend !== null);

  function reset() {
    setPreset(null);
    setEdits({});
    setSpend(null);
  }

  async function outcome(result: SaveOutcome, choice: Choice) {
    if (result.kind === 'saved') {
      reset();
      setStatus(result.view.mode === 'shadow' ? 'Saved. ' + view.copy.shadow : 'Saved.');
    } else if (result.kind === 'confirm') {
      setConfirming(choice);
    } else if (result.kind === 'sign_in') {
      setSignIn(result.message);
    } else if (result.kind === 'reload') {
      reset();
      setStatus(result.message);
    } else {
      setStatus(result.message);
    }
  }

  async function save(flags: { confirmed?: boolean } = {}, choice?: Choice) {
    const next: Choice = choice ?? { preset: (preset ?? 'recommended') as PresetId, changes: custom ? edits : undefined, spend: custom ? spend : null, source: 'settings' };
    setBusy(true);
    setStatus('');
    try {
      const stepUp = needsFreshSignIn(view, next.preset, next.changes);
      await outcome(await changes.save(view, next, { ...flags, stepUp }), next);
    } finally {
      setBusy(false);
    }
  }

  async function revoke(scopes: string[] | 'all') {
    setBusy(true);
    setStatus('');
    try {
      const result = await changes.revoke(scopes);
      if (result.kind === 'saved') {
        reset();
        const lines = result.view.receipt ? notRecallable(result.view, result.view.receipt) : [];
        setStatus(['Turned off.', ...lines].join(' '));
      } else {
        setStatus(result.kind === 'error' || result.kind === 'reload' || result.kind === 'sign_in' ? result.message : 'Couldn’t turn that off. Try again.');
      }
    } finally {
      setBusy(false);
    }
  }

  function choose(id: CategoryId, value: CategoryChoice) {
    setEdits((prev) => ({ ...prev, [categoryScope(id)]: value }));
  }

  return (
    <div className='flex flex-col gap-8'>
      <ModeNote view={view} />

      <SettingsSection id='agent-preset' title='How Rafii works for you' description={view.copy.intro}>
        <fieldset className='flex flex-col gap-2'>
          <legend className='sr-only'>Choose how much Rafii may do</legend>
          {view.state.needsChoice && (
            <PresetOption id='legacy' title={presetTitle(view, 'legacy')} summary={view.copy.presets.legacy?.summary ?? ''} checked={chosen === 'legacy'} onSelect={() => reset()} />
          )}
          {PRESET_ORDER.map((id) => (
            <PresetOption
              key={id}
              id={id}
              title={presetTitle(view, id)}
              summary={view.copy.presets[id]?.summary ?? ''}
              checked={chosen === id}
              note={id === 'full' ? 'You’ll sign in again to choose this.' : undefined}
              onSelect={() => {
                setPreset(id);
                setEdits({});
                setSpend(null);
              }}
            />
          ))}
        </fieldset>
      </SettingsSection>

      <SettingsSection id='agent-categories' title='What Rafii may do' description={custom ? 'Choose each area. Your role still decides what you can do.' : 'Your role still decides what you can do. Rafii never does more than you could.'}>
        <ul className='flex flex-col gap-4'>
          {CATEGORY_ORDER.map((id) => {
            const row = view.categories.find((c) => c.id === id);
            const copy = view.copy.categories[id];
            const state = row?.effective.state ?? 'unavailable';
            const value = (edits[categoryScope(id)] as CategoryChoice | undefined) ?? categoryChoice(view, id);
            return (
              <li key={id} className='flex flex-col gap-2'>
                <div className='flex flex-wrap items-start justify-between gap-2'>
                  <div className='flex min-w-0 flex-col gap-0.5'>
                    <span className='text-foreground text-sm font-medium break-words'>{copy?.title ?? id}</span>
                    <span className='text-muted-foreground text-xs leading-relaxed'>{copy?.summary}</span>
                  </div>
                  {!custom && (
                    <Badge variant={state === 'on' ? 'secondary' : 'outline'} className='shrink-0'>
                      {STATE_LABEL[state]}
                    </Badge>
                  )}
                </div>
                {state === 'clipped' && (
                  <StateMessage
                    kind='permission'
                    layout='inline'
                    title={row?.effective.reasons[0]?.code === 'workspace_ceiling' ? 'An owner limited this for the workspace.' : 'Your role here doesn’t allow this, so Rafii can’t do it either.'}
                  />
                )}
                {custom ? (
                  <SegmentedControl<CategoryChoice>
                    label={copy?.title ?? id}
                    size='md'
                    options={(['off', 'ask', 'assist'] as CategoryChoice[]).map((v) => ({ value: v, label: CHOICE_LABEL[v] }))}
                    value={value}
                    onChange={(v) => choose(id, v)}
                  />
                ) : (
                  row?.mode &&
                  !view.state.needsChoice && (
                    <div>
                      <Button variant='quiet' size='control' className='min-h-11' disabled={busy} onClick={() => void revoke([categoryScope(id)])}>
                        Turn off
                      </Button>
                    </div>
                  )
                )}
              </li>
            );
          })}
        </ul>
      </SettingsSection>

      <SettingsSection id='agent-domains' title='What Rafii may use' description={custom ? 'Turn off anything Rafii shouldn’t read for you.' : 'Choose Custom to turn individual kinds of information off.'}>
        <ul className='flex flex-col gap-1'>
          {view.domains.map((domain) => {
            const scope = `domain:${domain.id}`;
            const on = scope in edits ? Boolean(edits[scope]) : domain.granted;
            const label = view.copy.domains[domain.id] ?? domain.id;
            return (
              <li key={domain.id} className='flex min-h-11 items-center justify-between gap-4'>
                <span className='text-sm break-words'>{label}</span>
                <Switch checked={on} disabled={!custom || busy} aria-label={label} onCheckedChange={(checked: boolean) => setEdits((prev) => ({ ...prev, [scope]: checked }))} />
              </li>
            );
          })}
        </ul>
      </SettingsSection>

      <SettingsSection id='agent-spend' title='Spending credits'>
        {custom ? (
          <SegmentedControl<SpendConfirmation>
            label='When Rafii asks before spending credits'
            widths='content'
            options={SPEND_ORDER.map((v) => ({ value: v, label: view.copy.spend[v] }))}
            value={spend ?? (view.state.needsChoice ? 'all' : view.state.spendConfirmation)}
            onChange={(v) => setSpend(v)}
          />
        ) : (
          <p className='text-sm'>{view.copy.spend[view.state.needsChoice ? 'none' : view.state.spendConfirmation]}</p>
        )}
      </SettingsSection>

      <SettingsSection id='agent-autopilot' title='Autopilot'>
        <p className='text-muted-foreground text-sm'>Not available yet. Rafii doesn’t act on its own on a schedule.</p>
      </SettingsSection>

      {dirty && (
        <div className='flex flex-wrap items-center gap-2'>
          <Button variant='action' size='control' className='min-h-11' disabled={busy} onClick={() => void save()}>
            {busy ? <Icons.spinner className='size-4 animate-spin motion-reduce:animate-none' aria-hidden /> : null}
            Save
          </Button>
          <Button variant='glass' size='control' className='min-h-11' disabled={busy} onClick={reset}>
            Cancel
          </Button>
        </div>
      )}
      <p role='status' aria-live='polite' className='text-sm empty:hidden'>
        {status}
      </p>

      <History view={view} />
      {manager && <Members view={view} />}

      <SettingsSection id='agent-off' title={view.copy.revoke.title} description={view.copy.revoke.summary}>
        <HoldButton label={view.copy.revoke.confirm} disabled={busy || view.state.preset === 'none'} onHeld={() => void revoke('all')} />
      </SettingsSection>

      <RafiiDialog open={confirming !== null} onOpenChange={(open) => !open && setConfirming(null)}>
        <RafiiDialogContent size='sm'>
          <RafiiDialogHeader title='Let Rafii do more?' intro='This choice lets Rafii do things it couldn’t do before, or do them without asking first. You can turn it off here at any time.' />
          <RafiiDialogBody>
            <p className='text-sm'>{confirming ? presetTitle(view, confirming.preset) : ''}</p>
          </RafiiDialogBody>
          <RafiiDialogFooter>
            <Button
              variant='action'
              size='control'
              disabled={busy}
              onClick={() => {
                const choice = confirming;
                setConfirming(null);
                if (choice) void save({ confirmed: true }, choice);
              }}
            >
              Allow
            </Button>
            <Button variant='glass' size='control' onClick={() => setConfirming(null)}>
              Not now
            </Button>
          </RafiiDialogFooter>
        </RafiiDialogContent>
      </RafiiDialog>

      <RafiiDialog open={signIn !== null} onOpenChange={(open) => !open && setSignIn(null)}>
        <RafiiDialogContent size='sm'>
          <RafiiDialogHeader title='Sign in again to confirm' intro={signIn ?? undefined} />
          <RafiiDialogBody>
            <p className='text-muted-foreground text-sm'>For your safety, choosing this needs a sign-in from the last five minutes. After you sign in, you come back here to save it.</p>
          </RafiiDialogBody>
          <RafiiDialogFooter>
            <Button variant='action' size='control' onClick={() => void signInAgain()}>
              Sign out and sign in again
            </Button>
            <Button variant='glass' size='control' onClick={() => setSignIn(null)}>
              Cancel
            </Button>
          </RafiiDialogFooter>
        </RafiiDialogContent>
      </RafiiDialog>
    </div>
  );
}

function ModeNote({ view }: { view: View }) {
  const lines = [view.mode === 'shadow' ? view.copy.shadow : view.copy.enforce];
  if (view.state.needsChoice) lines.push('You haven’t chosen yet, so Rafii works the way it always has.');
  if (view.state.ended) lines.push('You rejoined this workspace, so earlier choices no longer apply.');
  if (view.pendingApprovals > 0) lines.push(`${view.pendingApprovals} ${view.pendingApprovals === 1 ? 'request is' : 'requests are'} waiting for your confirmation.`);
  return <StateMessage kind={view.mode === 'shadow' ? 'partial' : 'success'} layout='inline' title={lines[0]} description={lines.slice(1).join(' ') || undefined} />;
}

function PresetOption({ id, title, summary, note, checked, onSelect }: { id: string; title: string; summary: string; note?: string; checked: boolean; onSelect: () => void }) {
  return (
    <label
      className={cn(
        'rafii-focus flex min-h-11 cursor-pointer items-start gap-3 rounded-[var(--rafii-radius-control)] p-3',
        checked ? 'rafii-glass-selected' : 'rafii-glass'
      )}
    >
      <input type='radio' name='agent-preset' value={id} checked={checked} onChange={onSelect} className='mt-1 size-4 shrink-0' />
      <span className='flex min-w-0 flex-col gap-0.5'>
        <span className='text-foreground text-sm font-medium break-words'>{title}</span>
        <span className='text-muted-foreground text-xs leading-relaxed break-words'>{summary}</span>
        {note && <span className='text-muted-foreground text-xs'>{note}</span>}
      </span>
    </label>
  );
}

function History({ view }: { view: View }) {
  const history = useAgentPermissionHistory();
  const items = history.data?.items ?? [];
  return (
    <SettingsSection id='agent-history' title='History' description='Every change to what Rafii may do, newest first.'>
      {history.isPending ? (
        <StateMessage kind='loading' layout='inline' title='Loading history' />
      ) : items.length === 0 ? (
        <StateMessage kind='empty' layout='inline' title='No changes yet' />
      ) : (
        <ul className='flex flex-col gap-3'>
          {items.map((item) => (
            <li key={item.id} className='flex flex-col gap-0.5'>
              <span className='text-sm font-medium'>{historyLine(view, item)}</span>
              <span className='text-muted-foreground text-xs'>
                {when(item.at)}
                {item.actorIsYou === false ? ' · by someone else' : ''}
              </span>
              {notRecallable(view, item).map((line) => (
                <span key={line} className='text-muted-foreground text-xs'>
                  {line}
                </span>
              ))}
            </li>
          ))}
        </ul>
      )}
    </SettingsSection>
  );
}

function Members({ view }: { view: View }) {
  const members = useAgentPermissionMembers();
  const rows = members.data?.members ?? [];
  return (
    <SettingsSection id='agent-members' title='People in this workspace' description='What each member chose for Rafii. Each person decides for themselves.'>
      {members.isPending ? (
        <StateMessage kind='loading' layout='inline' title='Loading members' />
      ) : (
        <ul className='flex flex-col gap-2'>
          {rows.map((member) => (
            <li key={member.userId} className='flex min-h-11 flex-wrap items-center justify-between gap-2'>
              <span className='min-w-0 text-sm break-words'>{member.displayName || 'A member'}</span>
              <Badge variant='outline'>{presetTitle(view, member.preset)}</Badge>
            </li>
          ))}
        </ul>
      )}
    </SettingsSection>
  );
}

/** Press and hold to confirm (keyboard: hold Space or Enter). Letting go early does nothing. */
function HoldButton({ label, disabled, onHeld }: { label: string; disabled?: boolean; onHeld: () => void }) {
  const [holding, setHolding] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current);
  }, []);
  function start() {
    if (disabled || timer.current) return;
    setHolding(true);
    timer.current = setTimeout(() => {
      timer.current = null;
      setHolding(false);
      onHeld();
    }, HOLD_MS);
  }
  function stop() {
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
    setHolding(false);
  }
  return (
    <button
      type='button'
      disabled={disabled}
      aria-describedby='agent-off-hint'
      onPointerDown={start}
      onPointerUp={stop}
      onPointerLeave={stop}
      onKeyDown={(event) => {
        if ((event.key === ' ' || event.key === 'Enter') && !event.repeat) {
          event.preventDefault();
          start();
        }
      }}
      onKeyUp={(event) => {
        if (event.key === ' ' || event.key === 'Enter') stop();
      }}
      className='rafii-focus text-destructive relative inline-flex min-h-11 items-center overflow-hidden rounded-[var(--rafii-radius-control)] border border-current px-4 text-sm font-medium disabled:opacity-50'
    >
      <span aria-hidden className={cn('bg-destructive/15 absolute inset-y-0 left-0 transition-[width] ease-linear motion-reduce:transition-none', holding ? 'w-full duration-[1500ms]' : 'w-0 duration-150')} />
      <span className='relative'>{label}</span>
      <span id='agent-off-hint' className='sr-only'>
        Hold for a moment to confirm.
      </span>
    </button>
  );
}
