'use client';

import { useState } from 'react';
import { StateMessage } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { modelName } from '@/features/agent/use-model';
import { ConfirmChoice, useDecidedLine, useSaveError } from '@/features/memory/access-card';
import { SelectField } from '@/features/workspace/rafii-parts';
import { useAct, useSnapshot } from '@/lib/api/hooks';
import type { AgentInfo, ModelCatalog, ModelOption } from '@/lib/api/types';
import { SettingsSection } from '../settings-section';
import { routeKind } from './catalog';

/** "GPT gpt-6-sol": the family and the display name, as the confirmation names the writer that will receive sources. */
function writerTitle(option: ModelOption | undefined, id: string) {
  return [option?.family, modelName(option, id)].filter(Boolean).join(' ');
}

/**
 * The owner's default writer for everyone on Auto (snapshot `writerDefaults`, action `writer_defaults`). Changing it
 * changes who receives cloud-allowed sources and what drafts cost for the whole workspace, so nothing is sent until the
 * owner confirms; a stale revision offers a reload. Editors see the choice read-only. Hosted workspaces only: the card
 * renders when the catalogue names a deployment default (a managed writer exists).
 */
export function WorkspaceDefaultCard({ catalog, agents, isOwner }: { catalog: ModelCatalog; agents: AgentInfo[]; isOwner: boolean }) {
  const snapshot = useSnapshot();
  const act = useAct();
  const saveError = useSaveError();
  const settings = snapshot.data?.state.writerDefaults;
  const decidedLine = useDecidedLine(settings?.decidedAt ?? null, settings?.decidedBy ?? null, isOwner);
  // null follows the saved value; '' is "Rafii's default" (model null).
  const [picked, setPicked] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);

  const deployment = catalog.defaultModel ?? null;
  if (!deployment) return null;

  const offered = catalog.models.filter((option) => routeKind(option, agents) === 'managed' && option.qualified && option.priced !== false);
  const find = (id: string) => catalog.models.find((option) => option.id === id);
  const deploymentName = writerTitle(find(deployment), deployment);
  const current = settings?.model ?? null;
  const currentOffered = current ? offered.some((option) => option.id === current) : true;
  const selected = picked ?? (current && currentOffered ? current : '');
  const target = selected || deployment;
  const targetName = writerTitle(find(target), target);
  const unchanged = selected === (current && currentOffered ? current : '') && currentOffered;

  function save() {
    act.mutate(
      { revision: snapshot.data?.revision ?? 0, action: 'writer_defaults', payload: { model: selected || null, confirmed: true } },
      {
        onSuccess: () => {
          setConfirming(false);
          setPicked(null);
        },
        onError: (err) => {
          setConfirming(false);
          saveError(err, 'The workspace default could not be saved.');
        }
      }
    );
  }

  return (
    <SettingsSection
      id='models-workspace-default'
      title='Workspace default (Auto)'
      description='Everyone whose writer is Auto drafts with this writer, and so do Rafii’s own drafts that name no writer.'
      data-tour='models-workspace-default'
    >
      <div className='flex flex-col gap-3 text-sm'>
        <p>
          <span className='text-muted-foreground'>Now: </span>
          <span className='text-foreground font-medium'>{current && currentOffered ? writerTitle(find(current), current) : `Rafii’s default (${deploymentName})`}</span>
        </p>
        {current && !currentOffered && (
          <StateMessage kind='stale' layout='inline' title={`The workspace default writer ${current} is no longer offered, so Rafii uses ${deploymentName}.`} className='py-0' />
        )}
        {isOwner ? (
          <div className='flex flex-col gap-2 sm:flex-row sm:items-end'>
            <SelectField label='Default writer' value={selected} onChange={(event) => setPicked(event.target.value)} disabled={act.isPending || !snapshot.data} className='min-w-0 flex-1'>
              <option value=''>Rafii’s default ({deploymentName})</option>
              {offered.map((option) => (
                <option key={option.id} value={option.id}>
                  {writerTitle(option, option.id)}
                  {option.costTierLabel ? ` · ${option.costTierLabel}` : ''}
                </option>
              ))}
            </SelectField>
            <Button variant='glass' size='control' disabled={unchanged || act.isPending || !snapshot.data} onClick={() => setConfirming(true)}>
              Save default
            </Button>
          </div>
        ) : null}
        <p className='text-muted-foreground text-xs'>{isOwner ? decidedLine : ['Only an owner can change this.', decidedLine].filter(Boolean).join(' ')}</p>
      </div>
      {isOwner && (
        <ConfirmChoice
          open={confirming}
          pending={act.isPending}
          title={`Make ${targetName} the workspace default?`}
          description={`Everyone in this workspace whose writer is Auto — and Rafii’s weekly plans, campaign drafts, reply suggestions and agent drafts that name no writer — will use ${targetName} through Vercel AI Gateway. Sources allowed for cloud processing are sent to it.`}
          confirmLabel='Use this writer'
          cancelLabel='Keep the current one'
          onConfirm={save}
          onClose={() => setConfirming(false)}
        />
      )}
    </SettingsSection>
  );
}
