'use client';

import { useId, useRef, useState, type FormEvent } from 'react';
import { toast } from 'sonner';
import { Icons } from '@/components/icons';
import type { AnimatedBadgeStatus } from '@/components/motion/animated-badge';
import { RafiiDialog, RafiiDialogBody, RafiiDialogClose, RafiiDialogContent, RafiiDialogFooter, RafiiDialogHeader, StateMessage } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Band, FIELD_CLASS, SelectField, StatusChip } from '@/features/workspace/rafii-parts';
import { errorMessage, idempotencyKey } from '@/lib/growth-v2/request';
import { useConnectionAction, useCreateConnection, useResultConnections } from '@/lib/growth-v2/results-hooks';
import type { ConnectionSecret, ResultConnection, ResultProducer } from '@/lib/growth-v2/results-types';
import { formatDateTime, relativeTime } from '@/lib/time';
import { duration, problemText, type ResultsCopy } from './present';
import { useResultsCopy } from './use-results-copy';

const PRODUCERS: ResultProducer[] = ['form', 'booking', 'newsletter', 'store', 'other'];

function status(connection: ResultConnection): AnimatedBadgeStatus {
  if (connection.status !== 'active') return 'neutral';
  return connection.health.dataState === 'available' ? 'success' : connection.health.dataState === 'unavailable' ? 'neutral' : 'warning';
}

function endpointUrl(connection: ResultConnection): string {
  const endpoint = connection.endpoint;
  if (!endpoint) return '';
  return endpoint.url ?? (typeof window !== 'undefined' ? window.location.origin + endpoint.path : endpoint.path);
}

/** Signed first-party connections (owner only): create shows the secret once; rotate keeps the old key for 24 hours. */
export function ResultConnectionsView() {
  const { copy } = useResultsCopy();
  const query = useResultConnections();
  const [creating, setCreating] = useState(false);
  const [issued, setIssued] = useState<ConnectionSecret | null>(null);
  const [confirming, setConfirming] = useState<{ connection: ResultConnection; action: 'rotate' | 'remove' } | null>(null);
  const data = query.data;

  if (query.isPending) return <StateMessage kind='loading' layout='inline' title={copy.ledger.loading} />;
  if (query.isError || !data) {
    return (
      <StateMessage
        kind='error'
        layout='inline'
        title={copy.unavailableTitle}
        description={errorMessage(query.error)}
        action={
          <Button variant='glass' onClick={() => void query.refetch()}>
            <Icons.refresh /> {copy.retry}
          </Button>
        }
      />
    );
  }
  const live = data.connections.filter((connection) => connection.status !== 'removed').length;
  return (
    <>
      <div className='flex flex-wrap items-center justify-between gap-3'>
        <p className='text-muted-foreground text-xs'>{data.canManage ? copy.connections.limit(data.limit) : copy.connections.ownerOnly}</p>
        {data.canManage && (
          <Button variant='action' size='control' onClick={() => setCreating(true)} disabled={live >= data.limit}>
            <Icons.add /> {copy.connections.create}
          </Button>
        )}
      </div>
      {data.connections.length === 0 ? (
        <StateMessage kind='empty' layout='inline' title={copy.connections.empty} description={copy.connections.emptyDescription} />
      ) : (
        <ul className='flex flex-col gap-2' aria-label={copy.tabs.connections}>
          {data.connections.map((connection) => (
            <ConnectionRow key={connection.id} connection={connection} copy={copy} canManage={data.canManage} onConfirm={(action) => setConfirming({ connection, action })} />
          ))}
        </ul>
      )}
      <RafiiDialog open={creating} onOpenChange={setCreating}>
        <RafiiDialogContent size='sm'>
          {creating && (
            <CreateConnection
              onCreated={(result) => {
                setCreating(false);
                setIssued(result);
              }}
            />
          )}
        </RafiiDialogContent>
      </RafiiDialog>
      <RafiiDialog open={confirming !== null} onOpenChange={(open) => !open && setConfirming(null)}>
        <RafiiDialogContent size='sm'>
          {confirming && (
            <ConfirmAction
              key={`${confirming.connection.id}-${confirming.action}`}
              connection={confirming.connection}
              action={confirming.action}
              onDone={(result) => {
                setConfirming(null);
                if (result?.secretShown) setIssued(result);
              }}
            />
          )}
        </RafiiDialogContent>
      </RafiiDialog>
      {/* The secret lives only in this component's state, and only until the dialog closes. */}
      <RafiiDialog open={issued !== null} onOpenChange={(open) => !open && setIssued(null)} disablePointerDismissal>
        <RafiiDialogContent size='sm'>{issued && <SecretOnce issued={issued} onDone={() => setIssued(null)} />}</RafiiDialogContent>
      </RafiiDialog>
    </>
  );
}

function ConnectionRow({ connection, copy, canManage, onConfirm }: { connection: ResultConnection; copy: ResultsCopy; canManage: boolean; onConfirm: (action: 'rotate' | 'remove') => void }) {
  const act = useConnectionAction();
  const [problem, setProblem] = useState('');
  const health = connection.health;

  async function toggle() {
    setProblem('');
    const action = connection.status === 'active' ? 'pause' : 'resume';
    try {
      await act.mutateAsync({ id: connection.id, action, idempotencyKey: idempotencyKey(`result-connection-${action}`), expectedRevision: connection.revision });
    } catch (error) {
      setProblem(errorMessage(error));
    }
  }

  const lines = [
    health.lastReceivedAt ? copy.connections.lastEvent(relativeTime(health.lastReceivedAt)) : copy.connections.never,
    health.lagSeconds !== null && health.lagSeconds >= 60 ? copy.connections.lag(duration(health.lagSeconds, copy)) : ''
  ].filter(Boolean);
  return (
    <li>
      <Band className='gap-2'>
        <div className='flex flex-wrap items-center justify-between gap-2'>
          <div className='flex min-w-0 flex-wrap items-center gap-2'>
            <span className='text-foreground text-sm font-medium'>{connection.label}</span>
            <span className='text-muted-foreground text-xs'>{copy.connections.producers[connection.producer]}</span>
            <StatusChip status={status(connection)}>{copy.connections.status[connection.status]}</StatusChip>
          </div>
          {canManage && connection.status !== 'removed' && (
            <div className='flex flex-wrap gap-2'>
              <Button variant='glass' onClick={() => onConfirm('rotate')} disabled={act.isPending}>
                <Icons.key /> {copy.connections.rotate}
              </Button>
              <Button variant='glass' onClick={() => void toggle()} disabled={act.isPending} aria-busy={act.isPending || undefined}>
                {connection.status === 'active' ? (
                  <>
                    <Icons.pause /> {copy.connections.pause}
                  </>
                ) : (
                  <>
                    <Icons.play /> {copy.connections.resume}
                  </>
                )}
              </Button>
              <Button variant='quiet' onClick={() => onConfirm('remove')} disabled={act.isPending}>
                {copy.connections.remove}
              </Button>
            </div>
          )}
        </div>
        {connection.status !== 'removed' && (
          <>
            <p className='text-muted-foreground text-xs leading-relaxed'>{lines.join(' · ')}</p>
            <p className='text-muted-foreground text-xs leading-relaxed'>
              {copy.connections.counts(health.accepted24h, health.reversals24h, health.testEvents24h)}
              {health.quarantined > 0 ? ` · ${copy.connections.held(health.quarantined)}` : ''}
            </p>
            {health.lastErrorCode && health.dataState !== 'available' && (
              <p className='text-foreground text-xs'>{copy.connections.problem(problemText(health.lastErrorCode, copy))}</p>
            )}
            {connection.fingerprint && (
              <p className='text-muted-foreground font-mono text-xs'>
                {copy.connections.fingerprint(connection.fingerprint)}
                {connection.previousFingerprint && connection.previousExpiresAt
                  ? ` · ${copy.connections.previousUntil(connection.previousFingerprint, formatDateTime(connection.previousExpiresAt))}`
                  : ''}
              </p>
            )}
          </>
        )}
        {problem && (
          <p role='alert' className='text-destructive text-sm'>
            {problem}
          </p>
        )}
      </Band>
    </li>
  );
}

function CreateConnection({ onCreated }: { onCreated: (result: ConnectionSecret) => void }) {
  const { copy } = useResultsCopy();
  const id = useId();
  const create = useCreateConnection();
  const [label, setLabel] = useState('');
  const [producer, setProducer] = useState<ResultProducer>('form');
  const [problem, setProblem] = useState('');
  const intent = useRef(idempotencyKey('result-connection-create'));

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setProblem('');
    try {
      const result = await create.mutateAsync({ label: label.trim(), producer, idempotencyKey: intent.current });
      create.reset(); // the secret is not kept in the mutation cache
      onCreated(result);
    } catch (error) {
      setProblem(errorMessage(error));
    }
  }

  return (
    <form onSubmit={(event) => void submit(event)} className='flex min-h-0 flex-1 flex-col'>
      <RafiiDialogHeader title={copy.connections.createTitle} intro={copy.connections.createIntro} closeLabel={copy.form.cancel} />
      <RafiiDialogBody className='flex flex-col gap-4'>
        <div className='flex flex-col gap-2'>
          <Label htmlFor={`${id}-name`}>{copy.connections.name}</Label>
          <Input id={`${id}-name`} required maxLength={80} value={label} onChange={(event) => setLabel(event.target.value)} placeholder={copy.connections.namePlaceholder} className={FIELD_CLASS} />
        </div>
        <SelectField label={copy.connections.producer} value={producer} onChange={(event) => setProducer(event.target.value as ResultProducer)}>
          {PRODUCERS.map((kind) => (
            <option key={kind} value={kind}>
              {copy.connections.producers[kind]}
            </option>
          ))}
        </SelectField>
        {problem && (
          <p role='alert' className='text-destructive text-sm'>
            {problem}
          </p>
        )}
      </RafiiDialogBody>
      <RafiiDialogFooter className='flex-row justify-end'>
        <RafiiDialogClose render={<Button type='button' variant='quiet' size='control' disabled={create.isPending} />}>{copy.form.cancel}</RafiiDialogClose>
        <Button type='submit' variant='action' size='control' disabled={create.isPending || !label.trim()} aria-busy={create.isPending || undefined}>
          {create.isPending ? copy.connections.creating : copy.connections.createButton}
        </Button>
      </RafiiDialogFooter>
    </form>
  );
}

function ConfirmAction({ connection, action, onDone }: { connection: ResultConnection; action: 'rotate' | 'remove'; onDone: (result: ConnectionSecret | null) => void }) {
  const { copy } = useResultsCopy();
  const act = useConnectionAction();
  const [problem, setProblem] = useState('');
  const intent = useRef(idempotencyKey(`result-connection-${action}`));

  async function confirm() {
    setProblem('');
    try {
      const result = await act.mutateAsync({ id: connection.id, action, idempotencyKey: intent.current, expectedRevision: connection.revision });
      act.reset(); // a rotated secret is not kept in the mutation cache
      onDone(result);
    } catch (error) {
      setProblem(errorMessage(error));
    }
  }

  const rotate = action === 'rotate';
  return (
    <>
      <RafiiDialogHeader
        title={rotate ? copy.connections.rotateTitle : copy.connections.removeTitle}
        intro={rotate ? copy.connections.rotateIntro : copy.connections.removeIntro}
        closeLabel={copy.form.cancel}
      />
      <RafiiDialogBody>
        <p className='text-foreground text-sm font-medium'>{connection.label}</p>
        {problem && (
          <p role='alert' className='text-destructive mt-2 text-sm'>
            {problem}
          </p>
        )}
      </RafiiDialogBody>
      <RafiiDialogFooter className='flex-row justify-end'>
        <RafiiDialogClose render={<Button type='button' variant='quiet' size='control' disabled={act.isPending} />}>{copy.form.cancel}</RafiiDialogClose>
        <Button variant={rotate ? 'action' : 'destructive'} size='control' onClick={() => void confirm()} disabled={act.isPending} aria-busy={act.isPending || undefined}>
          {act.isPending ? copy.connections.working : rotate ? copy.connections.confirmRotate : copy.connections.confirmRemove}
        </Button>
      </RafiiDialogFooter>
    </>
  );
}

function SecretOnce({ issued, onDone }: { issued: ConnectionSecret; onDone: () => void }) {
  const { copy } = useResultsCopy();
  const id = useId();
  const url = endpointUrl(issued.connection);
  const copyText = (text: string, done: string) =>
    navigator.clipboard.writeText(text).then(
      () => toast.success(done),
      () => toast.error(copy.secret.copyFailed)
    );
  return (
    <>
      <RafiiDialogHeader title={issued.secret ? copy.secret.title : copy.secret.replayedTitle} intro={issued.secret ? copy.secret.warning : copy.secret.replayed} closeLabel={copy.secret.done} />
      <RafiiDialogBody className='flex flex-col gap-4'>
        {issued.secret && (
          <div className='flex flex-col gap-2'>
            <Label htmlFor={`${id}-secret`}>{issued.connection.label}</Label>
            <div className='flex flex-wrap items-center gap-2'>
              <Input id={`${id}-secret`} readOnly value={issued.secret} onFocus={(event) => event.currentTarget.select()} className={`${FIELD_CLASS} min-w-0 flex-1 font-mono text-xs md:text-xs`} autoComplete='off' spellCheck={false} />
              <Button type='button' variant='glass' size='control' onClick={() => void copyText(issued.secret ?? '', copy.secret.copied)}>
                <Icons.copy /> {copy.secret.copy}
              </Button>
            </div>
            <p role='note' className='text-foreground text-xs font-medium'>
              <Icons.warning aria-hidden className='mr-1 inline size-3.5 align-[-2px]' />
              {copy.secret.warning}
            </p>
          </div>
        )}
        {url && (
          <dl className='grid gap-1 text-sm'>
            <dt className='text-muted-foreground text-xs'>{copy.secret.endpoint}</dt>
            <dd className='text-foreground font-mono text-xs break-all'>POST {url}</dd>
            <dt className='text-muted-foreground mt-2 text-xs'>{copy.secret.header}</dt>
            <dd className='text-foreground font-mono text-xs'>{issued.connection.endpoint?.signatureHeader}: t=…,v1=…</dd>
          </dl>
        )}
        <p className='text-muted-foreground text-xs leading-relaxed'>{copy.secret.format}</p>
      </RafiiDialogBody>
      <RafiiDialogFooter>
        <Button variant='action' size='control' className='w-full' onClick={onDone}>
          {copy.secret.done}
        </Button>
      </RafiiDialogFooter>
    </>
  );
}
