'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import PageContainer from '@/components/layout/page-container';
import { Icons } from '@/components/icons';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { buttonVariants } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { QUICK_STARTS, QUICK_START_GROUPS, type QuickStart, type QuickStartGroup } from '@/config/quick-starts';
import { keys, useConversations, useModels, useSnapshot } from '@/lib/api/hooks';
import { ApiError } from '@/lib/api/client';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import { relativeTime } from '@/lib/time';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { cn } from '@/lib/utils';
import { Composer, DRAFT_PLATFORMS, type ChannelChip, type DraftPlatform, type Language } from './composer';
import { useModelChoice } from './use-model';

const CREATOR_PACK = { packId: 'pack.creator', version: '1.0.0' };

type ModeId = 'post' | 'thread' | 'carousel' | 'video' | 'research' | 'schedule';

const MODES: { id: ModeId; label: string; icon: keyof typeof Icons; placeholder: string; platforms: DraftPlatform[] }[] = [
  {
    id: 'post',
    label: 'Post',
    icon: 'sparkles',
    placeholder: 'Tell me the topic, paste a link, or drop your notes… e.g. “A post about what I learned redoing our onboarding. Instagram at 4pm today, LinkedIn at 5pm.”',
    platforms: ['LinkedIn', 'Instagram']
  },
  { id: 'thread', label: 'Thread', icon: 'listDetails', placeholder: 'What is the thread about? Give me the one thing you want people to take away…', platforms: ['Threads'] },
  { id: 'carousel', label: 'Carousel', icon: 'media', placeholder: 'What should the carousel teach or show? One idea per slide is enough to start…', platforms: ['Instagram', 'LinkedIn'] },
  { id: 'video', label: 'Video script', icon: 'video', placeholder: 'Paste the outline or your notes; I will draft the hook, the beats and the caption…', platforms: ['Instagram', 'Threads'] },
  { id: 'research', label: 'Research', icon: 'search', placeholder: 'What should I look into? Every source is logged before anything is written…', platforms: ['LinkedIn'] },
  { id: 'schedule', label: 'Schedule week', icon: 'calendar', placeholder: 'Tell me what goes out this week and when, e.g. “LinkedIn Tuesday 9am, Instagram Thursday 4pm, Threads Friday noon”…', platforms: ['LinkedIn', 'Instagram', 'Threads'] }
];

const infoContent = {
  title: 'How the agent works',
  sections: [
    { title: 'Channels in your message win', description: 'Name a channel and a time (“Instagram at 4pm today”) and the plan follows your words. The chips are the default when you name nothing.' },
    { title: 'Everything is a proposal', description: 'Drafts, schedule plans and memory notes are candidates until you approve them. The chat has no way to publish on its own.' },
    { title: 'Sources you chose', description: 'The agent reads only sources you added and marked usable; nothing else in your workspace is visible to it.' }
  ]
};

export function HomeView() {
  const params = useSearchParams();
  const router = useRouter();
  const client = useQueryClient();
  const { api, workspaceId } = useWorkspaceApi();
  const access = useWorkspaceAccess();
  const canEdit = checkAccess(access, { permission: 'edit' });
  const snapshot = useSnapshot();
  const conversations = useConversations();
  const models = useModels();
  const composer = useRef<HTMLTextAreaElement>(null);

  const [mode, setMode] = useState<ModeId>('post');
  const [text, setText] = useState('');
  const [selected, setSelected] = useState<DraftPlatform[]>(['LinkedIn', 'Instagram']);
  const [language, setLanguageState] = useState<Language>('English');
  const [languageTouched, setLanguageTouched] = useState(false);
  const [own, setOwn] = useState(true);
  const [use, setUse] = useState(true);
  const [busy, setBusy] = useState(false);
  const [template, setTemplate] = useState<QuickStart | null>(null);
  const [group, setGroup] = useState<QuickStartGroup | 'all'>('all');

  useEffect(() => {
    if (params.get('new') === '1') composer.current?.focus();
  }, [params]);

  const state = snapshot.data?.state;
  const revision = snapshot.data?.revision ?? 0;
  const voiceActive = Boolean(state?.speaker?.activeRevision);
  const voiceRevision = state?.speaker?.activeRevision ?? null;
  const channels = useMemo(() => state?.phase2?.channels ?? [], [state?.phase2?.channels]);
  const chips: ChannelChip[] = DRAFT_PLATFORMS.map((platform) => {
    const account = channels.find((c) => c.platform === platform);
    return { platform, account: account?.account, state: account?.displayState };
  });
  const activeSources = (state?.sources ?? []).filter((s) => s.active).length;
  const needsReview = (state?.phase2?.reviews ?? []).filter((r) => r.status === 'needs_review').length;
  const choice = useModelChoice(models.data);
  const current = MODES.find((m) => m.id === mode) ?? MODES[0];
  const timeZone = useMemo(() => Intl.DateTimeFormat().resolvedOptions().timeZone, []);

  // Until the writer picks a language, follow the message: CJK text drafts in 繁體中文 (the server detects the same way).
  useEffect(() => {
    if (!languageTouched) setLanguageState(/[一-鿿]/.test(text) ? '繁體中文' : 'English');
  }, [text, languageTouched]);

  function setLanguage(next: Language) {
    setLanguageTouched(true);
    setLanguageState(next);
  }

  function pickMode(next: ModeId) {
    setMode(next);
    const meta = MODES.find((m) => m.id === next);
    if (meta) setSelected(meta.platforms);
  }

  function pickTemplate(item: QuickStart) {
    setTemplate(item);
    setMode(item.mode);
    setSelected(item.platforms);
    setText(item.example);
    composer.current?.focus();
  }

  function toggle(platform: DraftPlatform) {
    setSelected((current) => (current.includes(platform) ? current.filter((p) => p !== platform) : [...current, platform]));
  }

  /** A template is a workspace content type: install the starter pack once, then select the type and format. */
  async function selectContentType(item: QuickStart, startRevision: number) {
    let current = startRevision;
    const installed = state?.contentTypes?.installedPacks?.some((pack) => pack.id === CREATOR_PACK.packId);
    if (!installed) {
      const after = await api.act(workspaceId, current, 'p2_content_install_pack', CREATOR_PACK);
      current = after.revision;
    }
    const after = await api.act(workspaceId, current, 'p2_content_select', { contentTypeId: item.contentTypeId, formatId: item.formatId });
    client.setQueryData(keys.snapshot(workspaceId), after);
    return after.revision;
  }

  async function start() {
    const body = text.trim();
    if (!body || !use || selected.length === 0 || busy) return;
    setBusy(true);
    try {
      const current = template ? await selectContentType(template, revision) : revision;
      const result = await api.quickStart(workspaceId, current, {
        text: body,
        ownContent: own,
        confirmUse: true,
        destinations: selected.map((platform) => ({ platform, language })),
        ...(languageTouched ? { language } : {}),
        model: choice.model,
        timeZone
      });
      client.setQueryData(['agent-run', workspaceId, result.runId], result);
      await Promise.all([
        client.invalidateQueries({ queryKey: keys.conversations(workspaceId) }),
        client.invalidateQueries({ queryKey: keys.snapshot(workspaceId) }),
        client.invalidateQueries({ queryKey: keys.usage(workspaceId) })
      ]);
      router.push(`/app/agent/${encodeURIComponent(result.conversationId)}`);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : 'The message could not be sent.');
      setBusy(false);
    }
  }

  const recent = conversations.data?.conversations ?? [];

  return (
    <PageContainer infoContent={infoContent}>
      <div className='mx-auto flex w-full max-w-3xl flex-col gap-6 pt-6 md:pt-10'>
        <div className='flex flex-col items-center gap-1.5 text-center'>
          <h1 className='text-2xl font-semibold tracking-tight md:text-[28px]'>What are we putting out this week?</h1>
          <p className='text-muted-foreground text-sm'>Tell me the topic. I write it in your voice for each channel and line up the schedule for you to approve.</p>
        </div>

        <div className='flex flex-wrap justify-center gap-2' role='tablist' aria-label='What to make'>
          {MODES.map((item) => {
            const Icon = Icons[item.icon];
            const on = item.id === mode;
            return (
              <button
                key={item.id}
                type='button'
                role='tab'
                aria-selected={on}
                onClick={() => pickMode(item.id)}
                className={cn(
                  'inline-flex h-9 items-center gap-1.5 rounded-full border px-3.5 text-sm font-medium transition-colors',
                  on ? 'border-primary bg-primary text-primary-foreground' : 'border-border bg-background text-foreground hover:bg-muted'
                )}
              >
                <Icon className='size-4' />
                {item.label}
              </button>
            );
          })}
        </div>

        {canEdit ? (
          <Composer
            ref={composer}
            value={text}
            onChange={setText}
            onSubmit={() => void start()}
            busy={busy}
            placeholder={current.placeholder}
            chips={chips}
            selected={selected}
            onToggle={toggle}
            language={language}
            onLanguage={setLanguage}
            models={choice.options}
            model={choice.model}
            onModel={choice.choose}
            consent={{ own, use, onOwn: setOwn, onUse: setUse }}
            hint='⌘↵ to send · nothing publishes without your approval'
          />
        ) : (
          <p className='text-muted-foreground text-center text-sm'>You need the edit permission to draft in this workspace.</p>
        )}

        <div className='text-muted-foreground -mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 px-1 text-xs'>
          <Link href='/app/workspace/brand' className='hover:text-foreground inline-flex items-center gap-1.5'>
            <Icons.user className='size-3.5' />
            Voice · <span className='text-foreground font-medium'>{snapshot.isLoading ? '…' : voiceActive ? `rev ${voiceRevision}` : 'not set up'}</span>
          </Link>
          <span className='bg-border h-3.5 w-px' />
          <Link href='/app/workspace/memory' className='hover:text-foreground inline-flex items-center gap-1.5'>
            <Icons.page className='size-3.5' />
            Memory · <span className='text-foreground font-medium'>5 files</span>
          </Link>
          <span className='bg-border h-3.5 w-px' />
          <Link href='/app/ideas' className='hover:text-foreground inline-flex items-center gap-1.5'>
            <Icons.paperclip className='size-3.5' />
            Sources · <span className='text-foreground font-medium'>{snapshot.isLoading ? '…' : `${activeSources} usable`}</span>
          </Link>
          <span className='ml-auto inline-flex items-center gap-1.5'>
            <Icons.shieldCheck className='size-3.5' />
            Nothing publishes until you approve.
          </span>
        </div>
        {template && (
          <div className='-mt-3 flex flex-wrap items-center gap-2 px-1 text-xs'>
            <Badge variant='secondary' className='gap-1.5'>
              <Icons.page className='size-3' />
              Template · {template.title}
            </Badge>
            <span className='text-muted-foreground'>Selects the “{template.title}” content type and its checks for this draft.</span>
            <button type='button' className='text-muted-foreground hover:text-foreground underline underline-offset-2' onClick={() => setTemplate(null)}>
              Clear
            </button>
          </div>
        )}

        {!snapshot.isLoading && !voiceActive && (
          <Alert>
            <Icons.info className='size-4' />
            <AlertTitle>Set up your voice first</AlertTitle>
            <AlertDescription className='flex flex-col gap-2'>
              <span>Previews work now, but drafts can only be scheduled once a voice profile is active. It takes two minutes.</span>
              <Link href='/app/workspace/brand' className={cn(buttonVariants({ size: 'sm', variant: 'outline' }), 'w-fit')}>
                Set up your voice
              </Link>
            </AlertDescription>
          </Alert>
        )}
        {needsReview > 0 && (
          <Alert>
            <Icons.clock className='size-4' />
            <AlertTitle>
              {needsReview} draft{needsReview === 1 ? '' : 's'} waiting for approval
            </AlertTitle>
            <AlertDescription className='flex flex-col gap-2'>
              <span>Nothing publishes until you approve the exact text, media and time.</span>
              <Link href='/app/queue' className={cn(buttonVariants({ size: 'sm', variant: 'outline' }), 'w-fit')}>
                Review now
              </Link>
            </AlertDescription>
          </Alert>
        )}

        <section className='flex flex-col gap-3'>
          <div className='flex flex-wrap items-center justify-between gap-2'>
            <div className='flex flex-col gap-0.5'>
              <h2 className='text-base font-semibold'>Quick starts</h2>
              <p className='text-muted-foreground text-xs'>Eleven kinds of post people actually publish. Pick one, replace the brackets, send.</p>
            </div>
            <div className='flex flex-wrap gap-1.5' role='tablist' aria-label='Quick start groups'>
              {QUICK_START_GROUPS.map((item) => (
                <button
                  key={item.id}
                  type='button'
                  role='tab'
                  aria-selected={group === item.id}
                  onClick={() => setGroup(item.id)}
                  className={cn(
                    'inline-flex h-6 items-center rounded-full border px-2.5 text-xs font-medium transition-colors',
                    group === item.id ? 'border-primary bg-primary text-primary-foreground' : 'border-border bg-background text-foreground hover:bg-muted'
                  )}
                >
                  {item.label}
                </button>
              ))}
            </div>
          </div>
          <div className='grid gap-3 sm:grid-cols-2 lg:grid-cols-3'>
            {QUICK_STARTS.filter((item) => group === 'all' || item.group === group).map((item) => (
              <button
                key={item.id}
                type='button'
                aria-pressed={template?.id === item.id}
                onClick={() => pickTemplate(item)}
                className={cn(
                  'bg-card ring-foreground/10 hover:bg-muted/40 flex flex-col gap-1.5 rounded-xl p-3.5 text-left ring-1 transition-colors',
                  template?.id === item.id && 'ring-primary ring-2'
                )}
              >
                <span className='text-sm font-medium'>{item.title}</span>
                <span className='text-muted-foreground text-xs leading-relaxed'>{item.explanation}</span>
                <span className='text-muted-foreground/80 mt-auto pt-1 text-[11px] leading-relaxed'>Usually: {item.usually}</span>
              </button>
            ))}
          </div>
        </section>

        <section className='flex flex-col gap-3'>
          <div className='flex items-center justify-between'>
            <h2 className='text-base font-semibold'>Recent conversations</h2>
            <Link href='/app/ideas' className='text-muted-foreground hover:text-foreground text-xs'>
              Sources &amp; older drafts
            </Link>
          </div>
          <div className='bg-card ring-foreground/10 overflow-hidden rounded-xl ring-1'>
            {conversations.isLoading ? (
              <div className='flex flex-col gap-2 p-4'>
                <Skeleton className='h-8 w-full' />
                <Skeleton className='h-8 w-full' />
              </div>
            ) : recent.length === 0 ? (
              <p className='text-muted-foreground p-4 text-sm'>No conversations yet. Your first message starts one.</p>
            ) : (
              <ul className='divide-y'>
                {recent.slice(0, 8).map((c) => (
                  <li key={c.conversationId}>
                    <Link href={`/app/agent/${encodeURIComponent(c.conversationId)}`} className='hover:bg-muted/40 flex items-center gap-3 px-4 py-3'>
                      <span className='bg-muted flex size-8 shrink-0 items-center justify-center rounded-lg'>
                        <Icons.sparkles className='size-4' />
                      </span>
                      <span className='flex min-w-0 flex-1 flex-col'>
                        <span className='truncate text-sm font-medium'>{c.title || 'Untitled'}</span>
                      </span>
                      {c.archived && <Badge variant='outline'>Archived</Badge>}
                      <span className='text-muted-foreground shrink-0 text-xs'>{relativeTime(c.updatedAt)}</span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </section>
      </div>
    </PageContainer>
  );
}
