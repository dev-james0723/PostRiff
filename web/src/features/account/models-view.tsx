'use client';

import { useQueryClient } from '@tanstack/react-query';
import PageContainer from '@/components/layout/page-container';
import { Icons } from '@/components/icons';
import { LevelBadge } from '@/components/app/level-badge';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { keys, useModels } from '@/lib/api/hooks';
import type { AgentInfo, ModelOption } from '@/lib/api/types';
import { useModelChoice } from '@/features/agent/use-model';
import { cn } from '@/lib/utils';

const infoContent = {
  title: 'Where drafts are written',
  sections: [
    { title: 'Local CLI', description: 'A coding agent CLI you already pay for, signed in on the machine that serves the API. PostRiff spawns it with no tools, no MCP servers, no settings and a per-run budget; it never reads your login.' },
    { title: 'PostRiff', description: 'The deterministic preview costs nothing and calls no model. A managed model route is listed only once it is qualified for this deployment.' },
    { title: 'Hosted service', description: 'On the hosted service the CLI route will run through the desktop companion on your own computer; until then it is available where the API runs locally.' }
  ]
};

function authBadge(agent: AgentInfo) {
  if (!agent.installed) return <LevelBadge level='Unsupported' label='Not installed' />;
  if (agent.authStatus === 'ok') return <LevelBadge level='Direct' label='Signed in' />;
  if (agent.authStatus === 'missing') return <LevelBadge level='Assisted' label='Sign-in required' />;
  return <LevelBadge level='Unsupported' label='Status unknown' />;
}

function AgentCard({ agent, models, current, onChoose }: { agent: AgentInfo; models: ModelOption[]; current: string; onChoose: (id: string) => void }) {
  const mine = models.filter((m) => m.route === agent.id);
  return (
    <Card>
      <CardHeader>
        <CardTitle className='flex flex-wrap items-center gap-2 text-base'>
          {agent.name}
          {agent.vendor && <span className='text-muted-foreground text-sm font-normal'>{agent.vendor}</span>}
          {authBadge(agent)}
        </CardTitle>
        <CardDescription className='flex flex-wrap gap-x-3 gap-y-1'>
          {agent.version ? <span className='font-mono'>{agent.version}</span> : <span>version unknown</span>}
          {agent.authMethod && <span>login: {agent.authMethod}</span>}
          <span>runs on: {agent.host === 'api-process' ? 'the machine serving the API' : agent.host ?? 'unknown'}</span>
        </CardDescription>
      </CardHeader>
      <CardContent className='flex flex-col gap-4'>
        {agent.guidance && (
          <p className='flex items-start gap-2 text-sm text-amber-700 dark:text-amber-300'>
            <Icons.warning className='mt-0.5 size-4 shrink-0' />
            {agent.guidance}
          </p>
        )}
        <div className='flex flex-col gap-2'>
          <span className='text-sm font-medium'>Models {agent.modelsSource === 'aliases' ? '· the CLI’s own aliases' : ''}</span>
          <div className='flex flex-wrap gap-2'>
            {mine.map((model) => (
              <button
                key={model.id}
                type='button'
                disabled={!model.qualified}
                onClick={() => onChoose(model.id)}
                className={cn(
                  'inline-flex h-8 items-center gap-2 rounded-lg border px-3 text-sm transition-colors disabled:opacity-50',
                  current === model.id ? 'border-primary bg-primary text-primary-foreground' : 'border-border bg-background hover:bg-muted'
                )}
                title={model.detail}
              >
                <span className='font-mono text-xs'>{model.id.split(':')[1] ?? model.id}</span>
                {current === model.id && <Icons.check className='size-3.5' />}
              </button>
            ))}
          </div>
          <span className='text-muted-foreground text-xs'>Click a model to make it the default for new drafts in this browser. Every run still shows what wrote it.</span>
        </div>
        {agent.execution && (
          <div className='grid gap-x-6 gap-y-1.5 text-sm sm:grid-cols-2'>
            <span className='text-muted-foreground'>Budget per run</span>
            <span className='font-mono'>${agent.execution.budgetUsd.toFixed(2)} · stops the run, never overcharges</span>
            <span className='text-muted-foreground'>Time limit</span>
            <span className='font-mono'>{agent.execution.timeoutSeconds}s</span>
            <span className='text-muted-foreground'>Tools · MCP · settings</span>
            <span>
              {agent.execution.tools} · {agent.execution.mcp} · {agent.execution.settingSources} (no hooks, no skills)
            </span>
            <span className='text-muted-foreground'>Session persistence</span>
            <span>{agent.execution.sessionPersistence ? 'on' : 'off'}</span>
            <span className='text-muted-foreground'>Environment passed</span>
            <span className='font-mono text-xs'>{agent.execution.environment.join(' ')}</span>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export function ModelsView() {
  const models = useModels();
  const client = useQueryClient();
  const choice = useModelChoice(models.data);
  const agents = models.data?.agents ?? [];
  const postriff = choice.options.filter((m) => !m.route || m.route === 'fixture' || m.route === 'managed');

  return (
    <PageContainer
      pageTitle='Models & providers'
      pageDescription='Choose what writes for you: a CLI you already pay for on your own machine, or PostRiff.'
      infoContent={infoContent}
      pageHeaderAction={
        <Button variant='outline' onClick={() => void client.invalidateQueries({ queryKey: keys.models })} disabled={models.isFetching}>
          <Icons.history className={cn('size-4', models.isFetching && 'animate-spin')} /> Rescan
        </Button>
      }
    >
      <div className='grid gap-4 lg:grid-cols-[minmax(0,1fr)_20rem]'>
        <div className='flex flex-col gap-4'>
          <div className='flex items-center justify-between'>
            <h2 className='text-sm font-semibold'>Local CLI ({agents.length})</h2>
            <span className='text-muted-foreground text-xs'>Detected on the machine serving the API. PostRiff never reads CLI credentials.</span>
          </div>
          {models.isLoading ? (
            <Skeleton className='h-40 w-full' />
          ) : agents.length === 0 ? (
            <Card>
              <CardContent className='text-muted-foreground flex flex-col gap-1 text-sm'>
                <span className='text-foreground font-medium'>No CLI is available to this deployment.</span>
                <span>Install Claude Code where the API runs and sign in with `claude auth login`, then rescan. On the hosted service this becomes the desktop companion.</span>
              </CardContent>
            </Card>
          ) : (
            agents.map((agent) => <AgentCard key={agent.id} agent={agent} models={choice.options} current={choice.model} onChoose={choice.choose} />)
          )}

          <h2 className='mt-2 text-sm font-semibold'>PostRiff</h2>
          <Card>
            <CardContent className='flex flex-col divide-y'>
              {postriff.map((model) => (
                <div key={model.id} className='flex flex-wrap items-center justify-between gap-3 py-3 first:pt-0 last:pb-0'>
                  <div className='flex min-w-0 flex-col gap-0.5'>
                    <span className='flex items-center gap-2 text-sm font-medium'>
                      {model.label}
                      {model.qualified ? <LevelBadge level='Direct' label='Available' /> : <LevelBadge level='Unsupported' label='Not qualified' />}
                    </span>
                    <span className='text-muted-foreground text-xs'>{model.detail}</span>
                  </div>
                  <Button variant={choice.model === model.id ? 'default' : 'outline'} size='sm' disabled={!model.qualified} onClick={() => choice.choose(model.id)}>
                    {choice.model === model.id ? 'Default' : 'Use by default'}
                  </Button>
                </div>
              ))}
            </CardContent>
          </Card>
        </div>

        <div className='flex flex-col gap-4'>
          <Card>
            <CardHeader>
              <CardTitle className='text-base'>How each option is billed</CardTitle>
            </CardHeader>
            <CardContent className='flex flex-col gap-3 text-sm'>
              <div className='flex items-start gap-2'>
                <LevelBadge level='Direct' label='Local CLI' />
                <span className='text-muted-foreground'>Uses the subscription you already have. PostRiff spends $0 and records the run and the cost the CLI reports.</span>
              </div>
              <div className='flex items-start gap-2'>
                <LevelBadge level='Assisted' label='Managed' />
                <span className='text-muted-foreground'>Counts against writing batches on your plan once a managed model is qualified.</span>
              </div>
              <div className='flex items-start gap-2'>
                <Badge variant='outline'>Preview</Badge>
                <span className='text-muted-foreground'>Deterministic, no model request, $0.</span>
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle className='text-base'>Current default</CardTitle>
              <CardDescription>Used by the composer on Home and in every conversation, in this browser.</CardDescription>
            </CardHeader>
            <CardContent className='font-mono text-sm'>{choice.label}</CardContent>
          </Card>
        </div>
      </div>
    </PageContainer>
  );
}
