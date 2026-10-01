'use client';

import { useState } from 'react';
import { Icons } from '@/components/icons';
import { StateMessage } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { Band, Panel, StatusChip } from '@/features/workspace/rafii-parts';
import { signInHref } from '@/lib/founder/api';
import { useCapability, useFounderScope } from '../customers/kit/api';
import { QueryState } from '../customers/kit/page-frame';
import { opsWorkspaceSummary, type OpsWorkspaceCreated } from './comms';
import { useCreateOpsWorkspace, useOpsWorkspace, writeFailureOf } from './comms-hooks';

/**
 * The founder workspace (CONTRACTS §8.H): the one internal workspace Founder Rafii, voice and founder calls run in.
 * `GET /ops-workspace` says where it comes from (the server variable, this page, or nowhere yet); `POST /ops-workspace`
 * creates it once — Live only, control.settings, and a second factor from the last five minutes. A stale second factor
 * comes back 403 STEP_UP_REQUIRED and the panel asks for a fresh sign-in; nothing is created until then.
 */

type Outcome = { kind: 'done'; data: OpsWorkspaceCreated } | { kind: 'failed'; failure: ReturnType<typeof writeFailureOf> } | null;

export function OpsWorkspacePanel() {
  const scope = useFounderScope();
  const query = useOpsWorkspace();
  const create = useCreateOpsWorkspace();
  const canSettings = useCapability('control.settings');
  const [outcome, setOutcome] = useState<Outcome>(null);
  const live = scope.mode === 'live';

  async function run() {
    setOutcome(null);
    try {
      setOutcome({ kind: 'done', data: await create.mutateAsync() });
    } catch (error) {
      setOutcome({ kind: 'failed', failure: writeFailureOf(error) });
    }
  }

  return (
    <Panel title='Founder workspace' description='The internal workspace Founder Rafii, voice and founder calls run in. Its usage is classified internal, never a customer’s.'>
      <QueryState query={query} label='founder workspace' layout='inline'>
        {(ops) => {
          const summary = opsWorkspaceSummary(ops);
          return (
            <div className='flex flex-col gap-3'>
              <Band className='gap-2'>
                <div className='flex flex-wrap items-center justify-between gap-2'>
                  <span className='text-foreground text-sm font-medium'>{summary.title}</span>
                  <StatusChip status={summary.state === 'set' ? 'success' : 'neutral'} icon={summary.state === 'set' ? 'check' : 'info'}>
                    {summary.state === 'set' ? (ops.source === 'environment' ? 'Set by the server' : 'Created here') : 'Not set'}
                  </StatusChip>
                </div>
                <p className='text-muted-foreground text-xs'>{summary.description}</p>
                {ops.workspaceId && (
                  <p className='text-muted-foreground text-xs'>
                    Workspace <code className='text-foreground font-mono break-all'>{ops.workspaceId}</code>
                  </p>
                )}
              </Band>
              {summary.state === 'creatable' && (
                <div className='flex flex-col gap-2'>
                  <p id='ops-workspace-note' className='text-muted-foreground text-xs'>
                    Creating it needs the control.settings capability and a second factor from the last five minutes. If your sign-in is older, Control refuses the request and this panel asks you to sign in again; nothing is created until then.
                  </p>
                  <Button type='button' variant='action' size='control' className='self-start' onClick={() => void run()} disabled={!live || !canSettings || create.isPending} aria-describedby='ops-workspace-note'>
                    {create.isPending ? <Icons.spinner className='animate-spin' /> : <Icons.add />} Create founder workspace
                  </Button>
                  {!live && <p className='text-muted-foreground text-xs'>Switch to Live to create it. Demo never writes.</p>}
                  {live && !canSettings && <p className='text-muted-foreground text-xs'>This operator does not hold the control.settings capability.</p>}
                </div>
              )}
              {outcome?.kind === 'done' && (
                <StateMessage
                  kind='success'
                  layout='inline'
                  title={outcome.data.created ? 'Founder workspace created' : 'A founder workspace already exists'}
                  description={`${outcome.data.name ?? 'Workspace'} · ${outcome.data.workspaceId}${outcome.data.created ? '. Founder Rafii and voice use it from their next request.' : ` (${outcome.data.source === 'environment' ? 'set by the server' : 'created earlier'}). Nothing new was created.`}`}
                />
              )}
              {outcome?.kind === 'failed' &&
                (outcome.failure.kind === 'step_up' ? (
                  <StateMessage
                    kind='permission'
                    layout='inline'
                    title='Sign in again to create the founder workspace'
                    description={outcome.failure.message}
                    action={
                      <a href={signInHref('/founder/settings')} className='rafii-focus text-foreground rounded text-sm font-medium underline underline-offset-4'>
                        Sign in again
                      </a>
                    }
                  />
                ) : (
                  <StateMessage kind={outcome.failure.kind === 'permission' ? 'permission' : 'error'} layout='inline' title='The founder workspace was not created' description={outcome.failure.message} />
                ))}
            </div>
          );
        }}
      </QueryState>
    </Panel>
  );
}
