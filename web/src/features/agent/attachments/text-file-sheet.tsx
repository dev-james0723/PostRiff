'use client';

/**
 * "Use {file}" after a text file becomes a source (chat-context SPEC §7.5, DNA §10.6): two separately explained controls,
 * both unticked, and nothing is granted implicitly. "Done" applies only what was ticked: approving the file's facts,
 * and letting cloud writers read it (as `rewrite_approval`, so a public post that quotes it still needs approval).
 */
import { useId, useState } from 'react';

import {
  RafiiDialog,
  RafiiDialogBody,
  RafiiDialogContent,
  RafiiDialogFooter,
  RafiiDialogHeader
} from '@/components/rafii/rafii-dialog';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { ApiError } from '@/lib/api/client';
import { useAct, useSnapshot } from '@/lib/api/hooks';
import { openedAsMessage } from '@/lib/media/text-file';

import type { TextFileResult } from './use-composer-attachments';

function Choice({
  checked,
  onChange,
  title,
  detail
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  title: string;
  detail?: string;
}) {
  const id = useId();
  return (
    <div className='flex items-start gap-3'>
      <Checkbox
        id={id}
        checked={checked}
        onCheckedChange={(next) => onChange(next === true)}
        className='mt-0.5'
      />
      <label htmlFor={id} className='flex min-w-0 flex-col gap-0.5 text-sm'>
        <span className='text-foreground'>{title}</span>
        {detail ? <span className='text-muted-foreground'>{detail}</span> : null}
      </label>
    </div>
  );
}

export function TextFileSheet({
  result,
  onDone
}: {
  result: TextFileResult | null;
  onDone: () => void;
}) {
  const snapshot = useSnapshot();
  const act = useAct();
  const [facts, setFacts] = useState(false);
  const [cloud, setCloud] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function done() {
    if (!result) return onDone();
    setError(null);
    try {
      let revision = snapshot.data?.revision ?? 0;
      if (facts) {
        const source = snapshot.data?.state.sources?.find((item) => item.id === result.sourceId);
        const after = await act.mutateAsync({
          revision,
          action: 'approve_source',
          payload: {
            sourceId: result.sourceId,
            factIds: (source?.facts ?? []).map((fact) => fact.id)
          }
        });
        revision = after.revision;
      }
      if (cloud) {
        await act.mutateAsync({
          revision,
          action: 'source_policy',
          payload: {
            sourceId: result.sourceId,
            policy: 'rewrite_approval',
            egressConsent: ['local', 'cloud'],
            confirmed: true
          }
        });
      }
      setFacts(false);
      setCloud(false);
      onDone();
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.message : 'Upload failed. Try again.');
    }
  }

  return (
    <RafiiDialog open={Boolean(result)} onOpenChange={(open) => (open ? undefined : onDone())}>
      <RafiiDialogContent size='sm'>
        <RafiiDialogHeader
          title={`Use ${result?.name ?? ''}`}
          intro={
            result
              ? result.reused
                ? 'This file is already in your sources.'
                : openedAsMessage(result.encoding)
              : undefined
          }
        />
        <RafiiDialogBody className='flex flex-col gap-4'>
          <Choice
            checked={facts}
            onChange={setFacts}
            title='Rafii may use the facts in this file'
          />
          <Choice
            checked={cloud}
            onChange={setCloud}
            title='Cloud writers may read it'
            detail='Public posts that quote it need your approval first.'
          />
          {error ? (
            <p role='alert' className='text-sm'>
              {error}
            </p>
          ) : null}
        </RafiiDialogBody>
        <RafiiDialogFooter>
          <Button onClick={() => void done()} disabled={act.isPending}>
            Done
          </Button>
        </RafiiDialogFooter>
      </RafiiDialogContent>
    </RafiiDialog>
  );
}
