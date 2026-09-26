'use client';

import { useCallback, useState } from 'react';
import Link from 'next/link';
import PageContainer from '@/components/layout/page-container';
import { Icons } from '@/components/icons';
import { InfoTip, StateMessage } from '@/components/rafii';
import { Button, buttonVariants } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { useMemory, useModels, useRescanModels, useSnapshot } from '@/lib/api/hooks';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import { modelName, useModelChoice } from '@/features/agent/use-model';
import { routeKind } from './models/catalog';
import { CheckAgainButton, CheckedLine } from './models/check-again';
import { CliEmpty } from './models/cli-empty';
import { CliRouteCard } from './models/cli-route-card';
import { PostriffRoutes } from './models/postriff-routes';
import { BillingCard, ConsentCard } from './models/side-cards';
import { useNowSeconds } from './models/use-saved-choice';
import { WorkspaceDefaultCard } from './models/workspace-default';
import { WritingNow } from './models/writing-now';

const PAGE_TITLE = 'Models';
const infoContent = {
  title: 'Where drafts are written',
  sections: [
    {
      title: 'Three kinds of writer',
      description: 'A coding CLI you sign in to, paid by its own subscription. The managed model, which uses writing batches. The free preview, which uses no AI model.'
    },
    {
      title: 'Your pick',
      description: 'Your pick is saved in this browser. Auto follows the workspace default. If a writer you picked becomes unavailable, drafting waits until you choose another; nothing is switched for you.'
    },
    {
      title: 'Your own CLI',
      description: 'Running a CLI from your own computer isn’t available yet.'
    }
  ]
};

function NoEditAccess() {
  return (
    <StateMessage
      kind='permission'
      title='Choosing a writer needs edit access'
      description='Ask a workspace owner for edit access.'
      action={
        <Link href='/app/account/privacy' className={buttonVariants({ variant: 'glass', size: 'control' })}>
          Privacy &amp; data
        </Link>
      }
      className='w-full max-w-md'
    />
  );
}

function ModelsBody() {
  const access = useWorkspaceAccess();
  const owner = checkAccess(access, { permission: 'owner' });
  const models = useModels();
  const memory = useMemory();
  const snapshot = useSnapshot();
  const choice = useModelChoice(models.data, snapshot.data?.state.writerDefaults?.model);
  const rescan = useRescanModels();
  const [picked, setPicked] = useState(false);
  const now = useNowSeconds();

  const options = choice.options;
  const agents = models.data?.agents ?? [];
  const loading = models.isLoading;
  const checking = rescan.isPending || (models.isFetching && !models.isLoading);
  const { choose } = choice;

  const onChoose = useCallback(
    (id: string) => {
      setPicked(true);
      choose(id);
    },
    [choose]
  );

  const unlisted = options.filter((option) => routeKind(option, agents) === 'cli' && !agents.some((agent) => agent.id === option.route));
  const hosted = typeof memory.data?.research?.hosted === 'boolean' ? memory.data.research.hosted : null;

  return (
    <PageContainer
      pageTitle={PAGE_TITLE}
      infoContent={infoContent}
      pageHeaderAction={<CheckAgainButton rescan={rescan.mutateAsync} checking={checking} disabled={loading} />}
    >
      {models.data ? (
        <div className='-mt-2'>
          <CheckedLine receivedAt={models.dataUpdatedAt / 1000} now={now} />
        </div>
      ) : null}

      {models.isError && (
        <StateMessage
          kind={models.data ? 'stale' : 'error'}
          layout='inline'
          title='Couldn’t load writers'
          description={`${models.data ? 'Showing the last list. ' : ''}${models.error?.message ?? ''}`.trim() || undefined}
          action={
            <Button variant='glass' size='sm' className='min-h-9' onClick={() => void models.refetch()}>
              <Icons.refresh className='size-3.5' /> Retry
            </Button>
          }
        />
      )}

      <div className='grid min-w-0 gap-8 lg:grid-cols-[minmax(0,1fr)_20rem]'>
        <div className='flex min-w-0 flex-col gap-8'>
          <WritingNow
            loading={loading}
            error={models.isError}
            onRetry={() => void models.refetch()}
            options={options}
            agents={agents}
            model={choice.model}
            option={choice.option}
            saved={models.data && !choice.auto ? choice.saved : null}
            picked={picked}
            auto={choice.auto ? { source: choice.autoSource ?? 'deployment', note: choice.autoNote } : null}
          />

          {models.data && <WorkspaceDefaultCard catalog={models.data} agents={agents} isOwner={owner} />}

          <PostriffRoutes
            loading={loading}
            listed={Boolean(models.data)}
            options={options}
            agents={agents}
            current={choice.selection}
            onChoose={onChoose}
            consent={{ loading: memory.isLoading, egress: memory.data?.egress }}
            autoName={choice.autoWriter.option ? modelName(choice.autoWriter.option, choice.autoWriter.model) : null}
          />

          <section data-tour='models-cli' className='flex flex-col gap-3' aria-labelledby='models-cli-heading'>
            <div className='flex flex-wrap items-center gap-x-1 gap-y-1 px-1'>
              <h2 id='models-cli-heading' className='text-foreground text-lg font-medium tracking-tight'>
                CLI writers{models.data ? ` (${agents.length})` : ''}
              </h2>
              <InfoTip
                label='About CLI writers'
                className='-my-2 size-9'
                description='Your sign-in to a CLI is never read. The same cloud-consent checks apply, and writing samples need permission per writer. Every run records which writer produced it.'
              />
            </div>
            {agents.length > 0 && <p className='text-muted-foreground px-1 text-sm'>Claude Code and Codex send selected context to their own AI service.</p>}
            {loading ? (
              <>
                <Skeleton className='h-40 w-full rounded-[var(--rafii-radius-card)]' />
                <Skeleton className='h-40 w-full rounded-[var(--rafii-radius-card)]' />
              </>
            ) : !models.data ? (
              <StateMessage kind='offline' layout='inline' title='Unavailable until writers load' />
            ) : agents.length === 0 ? (
              <CliEmpty hosted={hosted} />
            ) : (
              agents.map((agent) => <CliRouteCard key={agent.id} agent={agent} options={options} current={choice.selection} onChoose={onChoose} checking={checking} now={now} />)
            )}
            {unlisted.length > 0 && (
              <p className='text-muted-foreground px-1 text-xs'>
                {unlisted.length} CLI model{unlisted.length === 1 ? '' : 's'} not shown: {unlisted.map((option) => option.label).join(', ')}
              </p>
            )}
          </section>

        </div>

        <div className='flex min-w-0 flex-col gap-8'>
          {loading ? <Skeleton className='h-48 w-full rounded-[var(--rafii-radius-card)]' /> : <BillingCard options={options} owner={owner} />}
          <ConsentCard
            loading={memory.isLoading}
            error={memory.isError}
            onRetry={() => void memory.refetch()}
            egress={memory.data?.egress}
            research={memory.data?.research}
            learning={memory.data?.learning}
          />
        </div>
      </div>
    </PageContainer>
  );
}

export function ModelsView() {
  const access = useWorkspaceAccess();
  if (!checkAccess(access, { permission: 'edit' })) {
    return (
      <PageContainer access={false} accessFallback={<NoEditAccess />}>
        {null}
      </PageContainer>
    );
  }
  return <ModelsBody />;
}
