'use client';

import { useCallback, useState } from 'react';
import Link from 'next/link';
import PageContainer from '@/components/layout/page-container';
import { Icons } from '@/components/icons';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button, buttonVariants } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { useMemory, useModels, useRescanModels } from '@/lib/api/hooks';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import { useModelChoice } from '@/features/agent/use-model';
import { routeKind } from './models/catalog';
import { CheckAgainButton, CheckedLine } from './models/check-again';
import { CliEmpty } from './models/cli-empty';
import { CliRouteCard } from './models/cli-route-card';
import { PostriffRoutes } from './models/postriff-routes';
import { BillingCard, ConsentCard } from './models/side-cards';
import { useNowSeconds } from './models/use-saved-choice';
import { WritingNow } from './models/writing-now';

const PAGE_TITLE = 'Models & providers';
const PAGE_DESCRIPTION = 'Pick what writes your drafts, see where each writer runs, who pays for it and what it may read.';

const infoContent = {
  title: 'Where drafts are written',
  sections: [
    {
      title: 'Three kinds of writer',
      description:
        'A coding CLI signed in on the machine that serves the PostRiff API, paid by its own subscription. PostRiff’s managed model, metered to this workspace in writing batches. The deterministic preview, which calls no model and costs nothing.'
    },
    {
      title: 'Your pick',
      description: 'The writer you pick here is used by Home and every conversation in this browser. If it stops being available, PostRiff uses the first available writer and this page says so.'
    },
    {
      title: 'Checking again',
      description: 'Check again refreshes CLI installation and sign-in checks on the machine that serves PostRiff, including CLIs installed since startup.'
    },
    {
      title: 'Hosted service',
      description: 'On a hosted deployment a CLI will run through a desktop companion on your own computer. That companion is not available yet.'
    }
  ]
};

function NoEditAccess() {
  return (
    <div className='flex max-w-md flex-col items-center gap-3 text-center'>
      <Icons.lock className='text-muted-foreground size-6' />
      <h2 className='text-lg font-semibold'>Choosing a writer needs edit access</h2>
      <p className='text-muted-foreground text-sm'>
        This page picks which writer drafts for you, and only people who can edit drafts start a draft. Your role in this workspace can read but not edit, so there is nothing to choose here. Ask a workspace owner if you need edit access.
      </p>
      <Link href='/app/account/privacy' className={buttonVariants({ variant: 'outline', size: 'sm' })}>
        Privacy &amp; data
      </Link>
    </div>
  );
}

function ModelsBody() {
  const access = useWorkspaceAccess();
  const owner = checkAccess(access, { permission: 'owner' });
  const models = useModels();
  const memory = useMemory();
  const choice = useModelChoice(models.data);
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
      pageDescription={PAGE_DESCRIPTION}
      infoContent={infoContent}
      pageHeaderAction={<CheckAgainButton rescan={rescan.mutateAsync} checking={checking} disabled={loading} />}
    >
      {models.data ? (
        <div className='-mt-2 mb-4'>
          <CheckedLine receivedAt={models.dataUpdatedAt / 1000} now={now} />
        </div>
      ) : null}

      {models.isError && (
        <Alert variant='destructive' className='mb-4'>
          <Icons.alertCircle />
          <AlertTitle>The writer list could not be loaded</AlertTitle>
          <AlertDescription className='flex flex-col items-start gap-2'>
            <span>
              {models.error?.message ?? 'The request failed.'}
              {models.data ? ' The page shows the last list it received.' : ''}
            </span>
            <Button variant='outline' size='sm' onClick={() => void models.refetch()}>
              <Icons.refresh className='size-3.5' /> Retry
            </Button>
          </AlertDescription>
        </Alert>
      )}

      <div className='grid min-w-0 gap-4 lg:grid-cols-[minmax(0,1fr)_20rem]'>
        <div className='flex min-w-0 flex-col gap-6'>
          <WritingNow
            loading={loading}
            error={models.isError}
            onRetry={() => void models.refetch()}
            options={options}
            agents={agents}
            model={choice.model}
            option={choice.option}
            saved={models.data ? choice.saved : null}
            picked={picked}
          />

          <section data-tour='models-cli' className='flex flex-col gap-3' aria-labelledby='models-cli-heading'>
            <div className='flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1'>
              <h2 id='models-cli-heading' className='text-sm font-semibold'>
                Local CLI{models.data ? ` (${agents.length})` : ''}
              </h2>
              <span className='text-muted-foreground text-xs'>Found on the machine that serves the API. PostRiff never reads a CLI’s login.</span>
            </div>
            {agents.length > 0 && (
              <p className='text-muted-foreground max-w-prose text-xs'>
                Rafii applies cloud-consent checks to CLI writers too: Claude Code and Codex run on this machine but send selected context to their providers. Writing samples additionally require permission for the exact writer route. Picking one of its models makes it the writer for new drafts in this browser; every run still records which writer produced it.
              </p>
            )}
            {loading ? (
              <>
                <Skeleton className='h-40 w-full' />
                <Skeleton className='h-40 w-full' />
              </>
            ) : !models.data ? (
              <p className='text-muted-foreground text-sm'>Unavailable until the writer list loads.</p>
            ) : agents.length === 0 ? (
              <CliEmpty hosted={hosted} />
            ) : (
              agents.map((agent) => <CliRouteCard key={agent.id} agent={agent} options={options} current={choice.model} onChoose={onChoose} checking={checking} now={now} />)
            )}
            {unlisted.length > 0 && (
              <p className='text-muted-foreground text-xs'>
                The API lists {unlisted.length} CLI model{unlisted.length === 1 ? '' : 's'} without a matching CLI description: {unlisted.map((option) => option.label).join(', ')}.
              </p>
            )}
          </section>

          <PostriffRoutes
            loading={loading}
            listed={Boolean(models.data)}
            options={options}
            agents={agents}
            current={choice.model}
            onChoose={onChoose}
            consent={{ loading: memory.isLoading, egress: memory.data?.egress }}
          />
        </div>

        <div className='flex min-w-0 flex-col gap-4'>
          {loading ? <Skeleton className='h-48 w-full' /> : <BillingCard options={options} owner={owner} />}
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
