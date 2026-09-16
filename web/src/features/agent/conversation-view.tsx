'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import { useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import PageContainer from '@/components/layout/page-container';
import { Icons } from '@/components/icons';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Skeleton } from '@/components/ui/skeleton';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { keys, useConversations, useMessages, useModels, useSnapshot } from '@/lib/api/hooks';
import { ApiError } from '@/lib/api/client';
import type { Message, Run, SchedulePlan } from '@/lib/api/types';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import { formatDate, relativeTime } from '@/lib/time';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { cn } from '@/lib/utils';
import { ActivityStrip } from './activity-strip';
import { Composer, DRAFT_PLATFORMS, type ChannelChip, type DraftPlatform, type Language } from './composer';
import { PlanCard } from './plan-card';
import { shortLabel, useModelChoice } from './use-model';
import { useRun } from './use-run';
import { VariantCard, destinationLabel } from './variant-card';

const STAGE_LABELS: Record<string, string> = {
  queued: 'Waiting for Claude Code on this machine…',
  writing: 'Claude Code is writing…',
  drafting: 'Drafting…'
};

interface AssistantBody {
  text?: string;
  intent?: string;
  destinations?: { platform: string; language: string }[];
  plan?: SchedulePlan | null;
  excluded?: { id: string; reason: string }[];
}

function bodyOf(message: Message): AssistantBody & { text: string } {
  const body = message.body as AssistantBody;
  return { ...body, text: String(body.text ?? '') };
}

export function ConversationView({ conversationId }: { conversationId: string }) {
  const { api, workspaceId } = useWorkspaceApi();
  const client = useQueryClient();
  const access = useWorkspaceAccess();
  const canEdit = checkAccess(access, { permission: 'edit' });
  const snapshot = useSnapshot();
  const conversations = useConversations();
  const thread = useMessages(conversationId);
  const models = useModels();
  const composer = useRef<HTMLTextAreaElement>(null);

  const messages = useMemo(() => thread.data?.messages ?? [], [thread.data]);
  const lastAssistant = useMemo(() => messages.toReversed().find((m) => m.role === 'assistant' && m.runId) ?? null, [messages]);
  const lastRunId = lastAssistant?.runId ?? null;
  const seed = (lastRunId ? client.getQueryData<Run>(['agent-run', workspaceId, lastRunId]) : undefined) ?? null;
  const run = useRun(lastRunId, seed);

  const [text, setText] = useState('');
  const [selected, setSelected] = useState<DraftPlatform[]>(['LinkedIn', 'Instagram']);
  const [language, setLanguage] = useState<Language>('English');
  const [busy, setBusy] = useState(false);
  const [variantIndex, setVariantIndex] = useState(0);

  // The composer follows the last turn's destinations so "draft again" keeps the same targets.
  useEffect(() => {
    const last = lastAssistant ? bodyOf(lastAssistant).destinations : undefined;
    if (last && last.length > 0) {
      setSelected(last.map((d) => d.platform).filter((p): p is DraftPlatform => (DRAFT_PLATFORMS as readonly string[]).includes(p)));
      setLanguage((last[0].language as Language) ?? 'English');
    }
  }, [lastAssistant]);

  const state = snapshot.data?.state;
  const channels = useMemo(() => state?.phase2?.channels ?? [], [state?.phase2?.channels]);
  const chips: ChannelChip[] = DRAFT_PLATFORMS.map((platform) => {
    const account = channels.find((c) => c.platform === platform);
    return { platform, account: account?.account, state: account?.displayState };
  });
  const choice = useModelChoice(models.data);
  const runModelLabel = run ? shortLabel(choice.options.find((m) => m.id === run.model), run.model) : choice.label;
  const timeZone = useMemo(() => Intl.DateTimeFormat().resolvedOptions().timeZone, []);
  const running = run?.status === 'running';
  const streamed = useMemo(() => (run?.events ?? []).filter((e) => e.type === 'message.delta').map((e) => e.text ?? '').join(''), [run?.events]);
  const stage = useMemo(() => (run?.events ?? []).filter((e) => e.type === 'progress.updated').at(-1)?.stage ?? null, [run?.events]);

  // When a background run finishes, the assistant turn and the workspace snapshot changed on the server.
  const settledRun = run && !running ? `${run.runId}:${run.status}` : null;
  useEffect(() => {
    if (!settledRun) return;
    void client.invalidateQueries({ queryKey: keys.messages(workspaceId, conversationId) });
    void client.invalidateQueries({ queryKey: keys.snapshot(workspaceId) });
    void client.invalidateQueries({ queryKey: keys.usage(workspaceId) });
  }, [settledRun, client, workspaceId, conversationId]);
  const list = conversations.data?.conversations ?? [];
  const title = list.find((c) => c.conversationId === conversationId)?.title || thread.data?.title || 'Conversation';
  const plan = run?.artifact?.plan ?? null;
  const variants = run?.artifact?.variants ?? [];
  const sources = (state?.sources ?? []).filter((s) => s.active);

  async function sendTurn() {
    const body = text.trim();
    if (!body || selected.length === 0 || busy) return;
    setBusy(true);
    try {
      const result = await api.turn(workspaceId, conversationId, {
        text: body,
        destinations: selected.map((platform) => ({ platform, language })),
        language,
        model: choice.model,
        timeZone
      });
      client.setQueryData(['agent-run', workspaceId, result.runId], result);
      setText('');
      setVariantIndex(0);
      await client.invalidateQueries({ queryKey: keys.messages(workspaceId, conversationId) });
      await client.invalidateQueries({ queryKey: keys.usage(workspaceId) });
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : 'The message could not be sent.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <PageContainer>
      <div className='grid gap-4 lg:grid-cols-[13rem_1fr] xl:grid-cols-[13rem_1fr_20rem]'>
        {/* Conversations */}
        <aside className='hidden lg:flex lg:flex-col lg:gap-2'>
          <div className='flex items-center justify-between px-1'>
            <span className='text-sm font-semibold'>Conversations</span>
            <Link href='/app?new=1' className='text-muted-foreground hover:text-foreground inline-flex items-center gap-1 text-xs'>
              <Icons.add className='size-3.5' /> New
            </Link>
          </div>
          <ScrollArea className='h-[70vh]'>
            {conversations.isLoading ? (
              <div className='flex flex-col gap-2 p-1'>
                <Skeleton className='h-9 w-full' />
                <Skeleton className='h-9 w-full' />
              </div>
            ) : (
              <ul className='flex flex-col gap-0.5'>
                {list.map((c) => (
                  <li key={c.conversationId}>
                    <Link
                      href={`/app/agent/${encodeURIComponent(c.conversationId)}`}
                      className={cn('hover:bg-muted flex flex-col gap-0.5 rounded-lg px-2.5 py-2 text-sm', c.conversationId === conversationId && 'bg-muted font-medium')}
                    >
                      <span className='line-clamp-1'>{c.title || 'Untitled'}</span>
                      <span className='text-muted-foreground text-xs font-normal'>{formatDate(c.updatedAt)}</span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </ScrollArea>
        </aside>

        {/* Thread */}
        <section className='flex min-w-0 flex-col gap-4'>
          <div className='flex flex-wrap items-center justify-between gap-2'>
            <h1 className='truncate text-base font-semibold'>{title}</h1>
            <div className='flex items-center gap-2'>
              {plan && run?.status !== 'applied' && <Badge variant='outline' className='border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300'>Plan awaiting your approval</Badge>}
              <Badge variant='outline' className='gap-1 font-normal'>
                <Icons.sparkles className='size-3' />
                <span className='font-mono text-[11px]'>{runModelLabel}</span>
              </Badge>
              <Link href='/app/queue' className='text-muted-foreground hover:text-foreground text-xs underline-offset-2 hover:underline'>
                Open Queue
              </Link>
            </div>
          </div>

          <ol className='flex flex-col gap-5'>
            {thread.isLoading && <Skeleton className='h-24 w-full' />}
            {messages.map((message) => {
              const body = bodyOf(message);
              if (message.role === 'user') {
                return (
                  <li key={message.messageId} className='flex justify-end'>
                    <div className='bg-secondary text-secondary-foreground max-w-[80%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed whitespace-pre-wrap'>{body.text}</div>
                  </li>
                );
              }
              const isCurrent = message.runId != null && message.runId === lastRunId;
              return (
                <li key={message.messageId} className='flex gap-3'>
                  <span className='bg-primary text-primary-foreground mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-lg'>
                    <Icons.sparkles className='size-3.5' />
                  </span>
                  <div className='flex min-w-0 flex-1 flex-col gap-3'>
                    {isCurrent && run && <ActivityStrip run={run} plan={plan} intent={body.intent} destinations={body.destinations} />}
                    {body.text && <p className='text-sm leading-relaxed'>{body.text}</p>}
                    {body.excluded && body.excluded.length > 0 && (
                      <ul className='text-muted-foreground text-xs'>
                        {body.excluded.map((item) => (
                          <li key={item.id}>Source excluded — {item.reason.replace(/_/g, ' ')}</li>
                        ))}
                      </ul>
                    )}
                    {isCurrent && run ? (
                      <>
                        {running && (
                          <div className='bg-card ring-foreground/10 flex flex-col gap-2 rounded-xl p-4 ring-1'>
                            <span className='text-muted-foreground flex items-center gap-2 text-xs'>
                              <Icons.spinner className='size-3.5 animate-spin' />
                              {STAGE_LABELS[stage ?? ''] ?? 'Working…'}
                              <button type='button' className='ml-auto underline underline-offset-2' onClick={() => void api.cancelRun(workspaceId, run.runId)}>
                                Cancel
                              </button>
                            </span>
                            {streamed ? <p className='text-sm leading-relaxed whitespace-pre-wrap'>{streamed}</p> : <Skeleton className='h-16 w-full' />}
                          </div>
                        )}
                        {run.status === 'failed' && !(message.body as { failed?: boolean }).failed && (
                          <p className='text-sm text-amber-700 dark:text-amber-300'>{run.events.findLast((e) => e.type === 'run.failed')?.message ?? 'The run did not complete.'}</p>
                        )}
                        {variants.length > 0 && <VariantCard variants={variants} selected={variantIndex} onSelect={setVariantIndex} />}
                        {plan && snapshot.data && <PlanCard run={run} plan={plan} snapshot={snapshot.data} />}
                        {!plan && variants.length > 0 && (
                          <p className='text-muted-foreground text-xs'>
                            No times were named, so nothing is scheduled. Say when each post should go out, or{' '}
                            <Link href='/app/queue' className='underline underline-offset-2'>
                              schedule a draft in the Queue
                            </Link>
                            .
                          </p>
                        )}
                      </>
                    ) : (
                      body.plan && (
                        <p className='text-muted-foreground text-xs'>
                          Proposed {body.plan.destinations.length} post{body.plan.destinations.length === 1 ? '' : 's'} ({body.plan.destinations.map((d) => d.platform).join(', ')}) · earlier turn
                        </p>
                      )
                    )}
                    <span className='text-muted-foreground text-[11px]'>{relativeTime(message.at)}</span>
                  </div>
                </li>
              );
            })}
          </ol>

          {canEdit ? (
            <Composer
              ref={composer}
              value={text}
              onChange={setText}
              onSubmit={() => void sendTurn()}
              busy={busy}
              compact
              placeholder='Ask for another angle, a shorter version, or a different time…'
              chips={chips}
              selected={selected}
              onToggle={(platform) => setSelected((current) => (current.includes(platform) ? current.filter((p) => p !== platform) : [...current, platform]))}
              language={language}
              onLanguage={setLanguage}
              models={choice.options}
              model={choice.model}
              onModel={choice.choose}
              hint='⌘↵ to send · channels and times you name in the message win over the chips'
            />
          ) : (
            <p className='text-muted-foreground text-sm'>You need the edit permission to draft in this workspace.</p>
          )}
        </section>

        {/* Inspector */}
        <aside className='hidden xl:block'>
          <Tabs defaultValue='preview'>
            <TabsList className='w-full'>
              <TabsTrigger value='preview' className='flex-1'>
                Preview
              </TabsTrigger>
              <TabsTrigger value='sources' className='flex-1'>
                Sources · {sources.length}
              </TabsTrigger>
            </TabsList>
            <TabsContent value='preview' className='flex flex-col gap-3'>
              {variants[variantIndex] ? (
                <div className='bg-card ring-foreground/10 overflow-hidden rounded-xl ring-1'>
                  <div className='flex items-center gap-2 px-3 py-2.5'>
                    <span className='bg-muted size-7 rounded-full' />
                    <span className='flex flex-col leading-tight'>
                      <span className='text-xs font-semibold'>{channels.find((c) => c.platform === variants[variantIndex].platform)?.account ?? state?.speaker?.label ?? 'You'}</span>
                      <span className='text-muted-foreground text-[11px]'>{destinationLabel(variants[variantIndex])}</span>
                    </span>
                  </div>
                  {variants[variantIndex].platform === 'Instagram' && (
                    <div className='bg-muted text-muted-foreground flex h-40 flex-col items-center justify-center gap-1 text-xs'>
                      <Icons.media className='size-5' />
                      Image required for Instagram
                    </div>
                  )}
                  <p className='px-3 py-2.5 text-xs leading-relaxed whitespace-pre-wrap'>{variants[variantIndex].text}</p>
                </div>
              ) : (
                <p className='text-muted-foreground text-xs'>The selected draft renders here as it would look on the channel.</p>
              )}
              <p className='text-muted-foreground text-[11px]'>A preview, not a guarantee of how the provider renders it.</p>
            </TabsContent>
            <TabsContent value='sources' className='flex flex-col gap-2'>
              {sources.length === 0 ? (
                <p className='text-muted-foreground text-xs'>No usable sources in this workspace yet.</p>
              ) : (
                sources.slice(0, 12).map((s) => (
                  <div key={s.id} className='bg-card ring-foreground/10 flex flex-col gap-1 rounded-lg p-2.5 text-xs ring-1'>
                    <span className='flex items-center justify-between gap-2'>
                      <span className='truncate font-medium'>{s.title}</span>
                      <Badge variant='outline' className='shrink-0'>
                        {s.kind}
                      </Badge>
                    </span>
                    <span className='text-muted-foreground line-clamp-2'>{s.text}</span>
                  </div>
                ))
              )}
              <Button variant='outline' size='sm' className='w-fit' onClick={() => composer.current?.focus()}>
                Add context in the message
              </Button>
            </TabsContent>
          </Tabs>
        </aside>
      </div>
    </PageContainer>
  );
}
