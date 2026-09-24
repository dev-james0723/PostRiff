'use client';

import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import PageContainer from '@/components/layout/page-container';
import { ChannelIcon } from '@/components/channel-icon';
import { Icons } from '@/components/icons';
import { Checkbox } from '@/components/motion/checkbox';
import { NotificationStack } from '@/components/motion/notification-stack';
import { SharedLayoutBg } from '@/components/motion/shared-layout-bg';
import { RafiiDialog, RafiiDialogBody, RafiiDialogContent, RafiiDialogFooter, RafiiDialogHeader, SemanticIllustration, Surface } from '@/components/rafii';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { ChannelBloomDialog, toFolderAccounts } from '@/features/channels/channel-bloom';
import type { QuickStart } from '@/config/quick-starts';
import { keys, useChannels, useConversations, useMe, useMemory, useMemoryProposals, useModels, useSnapshot, useUsage } from '@/lib/api/hooks';
import { ApiError } from '@/lib/api/client';
import { deriveAttention } from '@/lib/attention';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import { languageLabel } from '@/lib/locales';
import { useTimeZone } from '@/lib/preferences';
import { relativeTime } from '@/lib/time';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { cn } from '@/lib/utils';
import { DRAFT_PLATFORMS, type DraftPlatform } from './composer';
import { contentChoice, selectLibraryContent, type LibraryValue } from './content-choice';
import { ContentLibraryDialog } from './content-library-dialog';
import { ContextPocket, pocketSources } from './home/context-pocket';
import { ExpandedIdeaDialog } from './home/expanded-idea-dialog';
import { greetingName, QuickStartsDisclosure, StartingPoints } from './home/home-nudges';
import { IdeaComposer } from './home/idea-composer';
import { IdeaSplits, IdlePreview, type PreviewTarget } from './home/idea-splits';
import { useHomeGeneration } from './home/use-home-generation';
import { VoiceDialog, type VoiceMode } from './home/voice-dialog';
import { ImageGenerationCard } from './image-generation-card';
import { LanguageDialog } from './language-dialog';
import { ModelDialog } from './model-dialog';
import { StartVoiceInterview } from './onboarding-chat';
import { RaffiPlanner } from './raffi-planner';
import { REASONING_LABELS } from './reasoning-map';
import { SettingButtons } from './setting-buttons';
import { selectionKey, useChannelLanguages, type ChannelTarget } from './use-channel-languages';
import { useDestinations } from './use-destinations';
import { useModelChoice } from './use-model';
import { eligibleVoiceSources } from './voice-consent';
import { voiceLearningIntent, type VoiceLearningRequest } from './voice-learning-intent';
import { VoiceLearningPanel } from './voice-learning-panel';

const CREATOR_PACK = { packId: 'pack.creator', version: '1.0.0' };
const DEFAULT_LIBRARY: LibraryValue = { editorialId: 'status_update', nativeId: 'text' };
/** Platform-level defaults before any account is chosen (the existing composer default). */
const DEFAULT_TARGETS: ChannelTarget<DraftPlatform>[] = [{ platform: 'LinkedIn' }, { platform: 'Instagram' }];
const PLACEHOLDER = 'Drop a thought, a link, or a beautifully messy idea…';

/** Something on Home that is waiting on the writer; built only from the workspace snapshot. */
interface NeedsYou {
  id: string;
  icon: keyof typeof Icons;
  title: string;
  description: string;
  href: string;
  action: string;
}

const infoContent = {
  title: 'How the agent works',
  sections: [
    { title: 'Destinations are accounts', description: 'Pick the connected accounts (or folders of accounts) a draft is for. Two accounts on one app get two drafts. Channels and times you name in the message still win.' },
    { title: 'Everything is a proposal', description: 'Drafts, schedule plans and memory notes are candidates until you approve them. The chat has no way to publish on its own.' },
    { title: 'Sources you chose', description: 'The agent reads only the sources you included in the Context Pocket and marked usable; nothing else in your workspace is visible to it.' }
  ]
};

const isDraftable = (platform: string): platform is DraftPlatform => (DRAFT_PLATFORMS as readonly string[]).includes(platform);

export function HomeView() {
  const params = useSearchParams();
  const router = useRouter();
  const client = useQueryClient();
  const { api, workspaceId } = useWorkspaceApi();
  const access = useWorkspaceAccess();
  const canEdit = checkAccess(access, { permission: 'edit' });
  const snapshot = useSnapshot();
  const conversations = useConversations();
  const channelQuery = useChannels();
  const usage = useUsage();
  const models = useModels();
  const memory = useMemory();
  const memoryProposals = useMemoryProposals();
  const me = useMe();
  const timeZone = useTimeZone();
  const composer = useRef<HTMLTextAreaElement>(null);
  const ids = { language: useId(), model: useId(), voice: useId() };

  const state = snapshot.data?.state;
  const revision = snapshot.data?.revision ?? 0;
  const channels = useMemo(() => state?.phase2?.channels ?? [], [state?.phase2?.channels]);
  const accounts = useMemo(() => toFolderAccounts(channels), [channels]);
  const folders = useMemo(() => state?.phase2?.channelFolders ?? [], [state?.phase2?.channelFolders]);
  const memoryFiles = memory.data?.files?.length ?? null;
  const pendingProposals = memoryProposals.data?.pending?.length ?? 0;
  const voiceActive = Boolean(state?.speaker?.activeRevision);
  const voiceRevision = state?.speaker?.activeRevision ?? null;
  const sources = useMemo(() => pocketSources(state?.sources), [state?.sources]);

  /* ---- composer state: original input, applied settings, staged dialog choices ---- */
  const [text, setText] = useState('');
  const [own, setOwn] = useState(true);
  const [use, setUse] = useState(true);
  const [voiceMode, setVoiceMode] = useState<VoiceMode>('neutral');
  const [imageRequested, setImageRequested] = useState(false);
  const [template, setTemplate] = useState<QuickStart | null>(null);
  const [library, setLibrary] = useState<LibraryValue>(DEFAULT_LIBRARY);
  const [included, setIncluded] = useState<string[]>([]);
  const [learning, setLearning] = useState<(VoiceLearningRequest & { workspaceId: string; id: string }) | null>(null);
  const [dialog, setDialog] = useState<null | 'expand' | 'context' | 'library' | 'channels' | 'platforms' | 'language' | 'model' | 'voice'>(null);

  /* ---- destinations: accounts (Channel Bloom) → selection items with languages ---- */
  const destinations = useDestinations(accounts);
  const languages = useChannelLanguages<DraftPlatform>([]);
  const targets = useMemo<ChannelTarget<DraftPlatform>[]>(() => {
    const fromAccounts = destinations.selected.flatMap((id) => {
      const account = accounts.find((a) => a.id === id);
      return account && account.connected && isDraftable(account.platform) ? [{ platform: account.platform, channelId: id } as ChannelTarget<DraftPlatform>] : [];
    });
    const fromPlatforms = destinations.platformOnly.filter(isDraftable).map((platform) => ({ platform }) as ChannelTarget<DraftPlatform>);
    const all = [...fromAccounts, ...fromPlatforms];
    return all.length ? all : DEFAULT_TARGETS;
  }, [destinations.selected, destinations.platformOnly, accounts]);
  const targetsKey = targets.map(selectionKey).join('|');
  const setTargets = languages.setTargets;
  useEffect(() => {
    setTargets(targets);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- re-sync only when the set of targets changes
  }, [targetsKey]);

  const choice = useModelChoice(models.data);
  const voiceSourceIds = eligibleVoiceSources(state?.sources ?? [], choice.option);
  const voiceAvailable = voiceSourceIds.length > 0;
  const imageCapability = models.data?.imageGeneration;
  const generation = useHomeGeneration();
  const chosenContent = contentChoice(library);

  useEffect(() => {
    if (params.get('new') === '1') composer.current?.focus();
  }, [params]);

  const attention = deriveAttention({ snapshot, channels: channelQuery, usage, now: Date.now() / 1000 });
  const needsYou: NeedsYou[] = attention.items.map((item) => ({ ...item, icon: item.id.startsWith('voice') ? 'user' : item.id === 'approvals' ? 'clock' : 'broadcast' }));

  /* ---- labels ---- */
  const previewTargets = useMemo<PreviewTarget[]>(
    () =>
      languages.selection.flatMap((item) => {
        const account = item.channelId ? accounts.find((a) => a.id === item.channelId) : undefined;
        return languages.languagesOf(item).map((language) => ({ platform: item.platform, language, channelId: item.channelId, account: account?.account }));
      }),
    [languages, accounts]
  );
  const languageSummary = useMemo(() => {
    const tags = Array.from(new Set(languages.selection.flatMap((item) => languages.languagesOf(item))));
    return tags.length === 0 ? 'Choose' : tags.length === 1 ? languageLabel(tags[0]) : `${tags.length} languages`;
  }, [languages]);
  const modelSummary = `${choice.label}${choice.reasoningMapping.applied ? ` · ${REASONING_LABELS[choice.reasoningMapping.preference]} reasoning` : ''}`;
  const destinationCount = languages.destinations.length;
  const accountsSelected = targets.filter((t) => t.channelId).length;
  const channelsLabel = destinations.selected.length > 0 ? destinations.summary : accounts.length === 0 ? 'Platforms only' : 'Channels';
  const channelsDetail = accountsSelected > 0 ? `${destinationCount} draft${destinationCount === 1 ? '' : 's'}` : `${targets.length} platform${targets.length === 1 ? '' : 's'} · no account`;
  const platformStack = Array.from(new Set(targets.map((t) => t.platform))).slice(0, 3);

  /* ---- actions ---- */
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

  async function applyLibrary(value: LibraryValue) {
    try {
      const result = await selectLibraryContent(api, workspaceId, revision, state?.contentTypes?.installedPacks, value);
      client.setQueryData(keys.snapshot(workspaceId), result.snapshot);
      setLibrary(value);
      setTemplate(null);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : 'The content type could not be selected.');
    }
  }

  function pickTemplate(item: QuickStart) {
    setTemplate(item);
    setText(item.example);
    composer.current?.focus();
  }

  const canGenerate = canEdit && Boolean(models.data && snapshot.data) && text.trim().length > 0 && destinationCount > 0 && use && (!imageRequested || Boolean(imageCapability?.available)) && !generation.busy && !generation.running;

  async function start() {
    const body = text.trim();
    if (!body || !canGenerate) return;
    const learningRequest = voiceLearningIntent(body);
    if (learningRequest) {
      setLearning({ ...learningRequest, workspaceId, id: crypto.randomUUID() });
      setText('');
      return; // No draft, model call, retention, analysis grant or publishing action.
    }
    let current = revision;
    try {
      if (template) current = await selectContentType(template, revision);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : 'The content type could not be selected.');
      return;
    }
    await generation.start(
      {
        text: body,
        ownContent: own,
        destinations: languages.destinations,
        model: choice.model,
        reasoning: choice.reasoning,
        voiceMode,
        voiceSourceIds,
        imageGeneration: imageRequested ? { enabled: true, count: 1 } : undefined,
        timeZone,
        sourceIds: included
      },
      current
    );
  }

  const draftAgain = useCallback(() => {
    generation.reset();
    composer.current?.focus();
  }, [generation]);

  const helpText = !canEdit
    ? 'You need the edit permission to draft in this workspace.'
    : generation.busy || generation.running
      ? 'Writing your drafts. Nothing publishes without your approval.'
      : destinationCount === 0
        ? 'Choose at least one destination.'
        : !text.trim()
          ? 'Start with an idea. We’ll take it from there.'
          : !use
            ? 'Confirm the text may be used to draft with.'
            : imageRequested && !imageCapability?.available
              ? (imageCapability?.detail ?? 'Image generation is not available on this route.')
              : `${destinationCount} draft${destinationCount === 1 ? '' : 's'} · one per destination and language · ⌘↵ to send`;

  const recent = conversations.data?.conversations ?? [];
  const firstName = greetingName(me.data?.displayName);
  const speaker = state?.speaker?.label ?? 'You';

  return (
    <PageContainer infoContent={infoContent} className='pt-6 md:pt-8'>
      <div className='mx-auto grid w-full max-w-[1192px] gap-10 lg:grid-cols-[minmax(0,580px)_minmax(310px,1fr)] lg:gap-16 xl:gap-[88px]'>
        {/* Creation column */}
        <div className='flex min-w-0 flex-col gap-6'>
          <div className='flex flex-col gap-3'>
            <span className='rafii-eyebrow inline-flex items-center gap-2.5'>
              <span aria-hidden className='bg-foreground/70 h-px w-4' />A little idea. A bigger reach.
            </span>
            <h1 className='text-foreground text-[2.5rem] leading-[1.05] font-normal tracking-[-0.03em] md:text-[2.75rem] xl:text-[3.05rem]'>
              What’s the idea
              {firstName ? (
                <>
                  , <em className='rafii-serif'>{firstName}?</em>
                </>
              ) : (
                <>
                  {' '}
                  <em className='rafii-serif'>today?</em>
                </>
              )}
            </h1>
            <p className='text-muted-foreground max-w-[450px] text-[15px] leading-relaxed'>Give it a thought. Rafii drafts one version per destination, in your voice, for your review.</p>
          </div>

          {canEdit ? (
            <IdeaComposer
              ref={composer}
              value={text}
              onChange={setText}
              placeholder={template ? `${template.title}: replace the brackets and send.` : PLACEHOLDER}
              disabled={!models.data || !snapshot.data}
              busy={generation.busy || generation.running}
              onExpand={() => setDialog('expand')}
              contextCount={included.length}
              onOpenContext={() => setDialog('context')}
              onTryIdea={() => setText('A behind-the-scenes thought: the quiet, imperfect work is usually where the best ideas begin.')}
              extras={
                <button
                  type='button'
                  aria-pressed={imageRequested}
                  disabled={!imageCapability?.available}
                  onClick={() => setImageRequested((v) => !v)}
                  title={imageCapability?.detail ?? 'Checking the managed image route…'}
                  className={cn('rafii-focus inline-flex min-h-11 items-center gap-1.5 rounded-md text-xs font-medium', imageRequested ? 'text-foreground' : 'text-muted-foreground hover:text-foreground', !imageCapability?.available && 'opacity-50')}
                >
                  <Icons.media className='size-3.5' />
                  {imageRequested ? 'Image on' : 'Generate image'}
                </button>
              }
              contentType={{
                visual: (
                  <span aria-hidden className='relative block h-8 w-9'>
                    <span className='absolute top-0.5 left-0 h-5 w-[30px] -rotate-[9deg] overflow-hidden rounded-[3px] shadow-sm'>
                      <SemanticIllustration id={library.editorialId} size='compact' decorative className='h-full w-full' />
                    </span>
                    <span className='absolute top-2.5 left-1.5 h-5 w-[30px] rotate-[8deg] overflow-hidden rounded-[3px] shadow-sm'>
                      <SemanticIllustration id={library.nativeId} size='compact' decorative className='h-full w-full' />
                    </span>
                  </span>
                ),
                label: template ? template.title : (chosenContent?.summary ?? 'Content type'),
                detail: template ? 'Quick start template' : chosenContent?.planningOnly ? chosenContent.planningOnly.label : (chosenContent?.formatLabel ?? undefined),
                ariaLabel: `Choose content type and native format, ${chosenContent?.summary ?? 'not chosen'}`,
                onOpen: () => setDialog('library'),
                open: dialog === 'library'
              }}
              channels={{
                visual: (
                  <span aria-hidden className='flex items-center'>
                    {platformStack.map((platform, index) => (
                      <ChannelIcon key={platform} platform={platform} size='sm' className={cn('ring-background rounded-lg ring-2', index > 0 && '-ml-2')} />
                    ))}
                  </span>
                ),
                label: channelsLabel,
                detail: channelsDetail,
                ariaLabel: `Choose channels, ${accountsSelected} account${accountsSelected === 1 ? '' : 's'} selected`,
                onOpen: () => setDialog(accounts.length > 0 ? 'channels' : 'platforms'),
                open: dialog === 'channels' || dialog === 'platforms'
              }}
              settings={
                <SettingButtons
                  language={{ value: languageSummary, onClick: () => setDialog('language'), expanded: dialog === 'language', controls: ids.language, disabled: languages.selection.length === 0 }}
                  model={{ value: modelSummary, onClick: () => setDialog('model'), expanded: dialog === 'model', controls: ids.model, disabled: !models.data }}
                  voice={{ value: voiceMode === 'personalized' ? 'Writing like you' : 'Neutral', onClick: () => setDialog('voice'), expanded: dialog === 'voice', controls: ids.voice }}
                />
              }
              generate={{ label: generation.run ? 'Generate again' : 'Generate drafts', count: destinationCount, disabled: !canGenerate, onClick: () => void start(), help: helpText }}
              consent={
                <div className='mt-3 flex flex-wrap items-center gap-x-5 gap-y-2 pt-3'>
                  <Checkbox checked={use} onCheckedChange={setUse} label='Use this text to draft with' className='gap-2 [&>button]:size-4 [&>span]:text-xs' />
                  <Checkbox checked={own} onCheckedChange={setOwn} label='My own writing (may be quoted publicly)' className='gap-2 [&>button]:size-4 [&>span]:text-xs' />
                  <span className='text-muted-foreground ml-auto inline-flex items-center gap-1.5 text-xs'>
                    <Icons.shieldCheck className='size-3.5' />
                    Your approval. Always. Nothing publishes here.
                  </span>
                </div>
              }
            />
          ) : (
            <Surface material='quiet' padding='md'>
              <p className='text-muted-foreground text-sm'>You need the edit permission to draft in this workspace.</p>
            </Surface>
          )}

          {canEdit && <StartingPoints onPick={(sample) => { setText(sample); composer.current?.focus(); }} disabled={generation.busy || generation.running} />}
          {generation.busy && imageRequested && <ImageGenerationCard running className='mx-auto' />}
          {learning?.workspaceId === workspaceId && <VoiceLearningPanel key={learning.id} request={learning} onClose={() => setLearning(null)} />}

          {template && (
            <div className='flex flex-wrap items-center gap-2 text-xs'>
              <Badge variant='secondary' className='gap-1.5'>
                <Icons.page className='size-3' />
                Template · {template.title}
              </Badge>
              <span className='text-muted-foreground'>Selects the “{template.title}” content type and its checks for this draft.</span>
              <button type='button' className='rafii-focus text-muted-foreground hover:text-foreground rounded-md underline underline-offset-2' onClick={() => setTemplate(null)}>
                Clear
              </button>
            </div>
          )}

          <div className='text-muted-foreground flex flex-wrap items-center gap-x-4 gap-y-1 text-xs'>
            <Link href='/app/workspace/brand' className='hover:text-foreground inline-flex min-h-8 items-center gap-1.5'>
              <Icons.user className='size-3.5' />
              Voice · <span className='text-foreground font-medium'>{snapshot.isLoading ? '…' : voiceActive ? `rev ${voiceRevision}` : 'not set up'}</span>
            </Link>
            <Link href='/app/workspace/memory' className='hover:text-foreground inline-flex min-h-8 items-center gap-1.5'>
              <Icons.page className='size-3.5' />
              Memory · <span className='text-foreground font-medium'>{memoryFiles === null ? '…' : `${memoryFiles} files`}</span>
              {pendingProposals > 0 && (
                <span className='rafii-glass-selected text-foreground rounded-full px-1.5 py-0.5 text-[11px] font-medium' aria-label={`${pendingProposals} learned preference${pendingProposals === 1 ? '' : 's'} waiting for your decision`}>
                  Rafii noticed {pendingProposals} · review
                </span>
              )}
            </Link>
            <Link href='/app/ideas' className='hover:text-foreground inline-flex min-h-8 items-center gap-1.5'>
              <Icons.paperclip className='size-3.5' />
              Sources · <span className='text-foreground font-medium'>{snapshot.isLoading ? '…' : `${sources.length} usable`}</span>
            </Link>
            {canEdit && <StartVoiceInterview key={workspaceId} />}
          </div>

          {canEdit && <QuickStartsDisclosure selected={template} onPick={pickTemplate} disabled={generation.busy || generation.running} />}
        </div>

        {/* Preview column */}
        <aside aria-label='Channel draft previews' className='min-w-0 lg:pt-2'>
          {generation.run || generation.busy || generation.error ? (
            <IdeaSplits generation={generation} timeZone={timeZone} speaker={speaker} onDraftAgain={draftAgain} />
          ) : (
            <IdlePreview targets={previewTargets} idea={text} timeZone={timeZone} speaker={speaker} />
          )}
        </aside>
      </div>

      <div className='mx-auto mt-10 flex w-full max-w-[1192px] flex-col gap-6'>
        {state && <RaffiPlanner state={state} revision={revision} canEdit={canEdit} isOwner={checkAccess(access, { permission: 'owner' })} />}

        {needsYou.length > 0 && (
          <div>
            {/* The stack is one button labelled by its count, so the items themselves are listed for screen readers here. */}
            <ul className='sr-only'>
              {needsYou.map((item) => (
                <li key={item.id}>
                  {item.title}. {item.description}
                </li>
              ))}
            </ul>
            <NotificationStack
              items={needsYou.map((item) => {
                const Icon = Icons[item.icon];
                return {
                  id: item.id,
                  title: (
                    <span className='inline-flex items-center gap-1.5'>
                      <Icon className='text-muted-foreground size-3.5 shrink-0' />
                      {item.title}
                    </span>
                  ),
                  description: item.description
                };
              })}
              collapsedLabel='Needs you'
              expandedLabel={needsYou.length === 1 ? needsYou[0].action : 'Open overview'}
              onViewAll={() => router.push(needsYou.length === 1 ? needsYou[0].href : '/app/overview')}
              classNames={{ content: 'py-3', count: 'bg-primary text-primary-foreground dark:bg-primary' }}
            />
          </div>
        )}

        <section className='flex flex-col gap-3'>
          <div className='flex items-center justify-between'>
            <h2 className='text-base font-semibold'>Recent conversations</h2>
            <Link href='/app/ideas' className='text-muted-foreground hover:text-foreground text-xs'>
              Sources &amp; older drafts
            </Link>
          </div>
          <Surface material='quiet' padding='none' className='overflow-hidden'>
            {conversations.isLoading ? (
              <div className='flex flex-col gap-2 p-4'>
                <Skeleton className='h-8 w-full' />
                <Skeleton className='h-8 w-full' />
              </div>
            ) : recent.length === 0 ? (
              <p className='text-muted-foreground p-4 text-sm'>No conversations yet. Your first message starts one.</p>
            ) : (
              <SharedLayoutBg as='ul' inset={0} pillClassName='rounded-none rafii-glass-selected' className='divide-border/60 divide-y'>
                {recent.slice(0, 8).map((c) => (
                  <li key={c.conversationId}>
                    <Link href={`/app/agent/${encodeURIComponent(c.conversationId)}`} className='flex min-h-12 items-center gap-3 px-4 py-2.5'>
                      <span className='rafii-glass flex size-8 shrink-0 items-center justify-center rounded-lg'>
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
              </SharedLayoutBg>
            )}
          </Surface>
        </section>
      </div>

      {/* Dialogs: each stages its own choices and applies on its primary action. */}
      <ExpandedIdeaDialog open={dialog === 'expand'} onOpenChange={(open) => setDialog(open ? 'expand' : null)} value={text} onChange={setText} placeholder={PLACEHOLDER} />
      <ContextPocket open={dialog === 'context'} onOpenChange={(open) => setDialog(open ? 'context' : null)} sources={sources} included={included} onIncludedChange={setIncluded} revision={revision} />
      <ContentLibraryDialog open={dialog === 'library'} onOpenChange={(open) => setDialog(open ? 'library' : null)} value={library} onApply={(value) => void applyLibrary(value)} platformsForFit={Array.from(new Set(targets.map((t) => t.platform)))} />
      <ChannelBloomDialog open={dialog === 'channels'} onOpenChange={(open) => setDialog(open ? 'channels' : null)} accounts={accounts} folders={folders} selected={destinations.selected} context={destinations.context} onCommit={(result) => { destinations.commit({ accountIds: result.accountIds, context: result.context, platformOnly: [] }); setDialog(null); }} />
      <PlatformOnlyDialog open={dialog === 'platforms'} onOpenChange={(open) => setDialog(open ? 'platforms' : null)} value={destinations.platformOnly.filter(isDraftable)} onApply={(platforms) => destinations.setPlatformOnly(platforms)} />
      <LanguageDialog open={dialog === 'language'} onOpenChange={(open) => setDialog(open ? 'language' : null)} selection={languages.selection} languages={languages} accountLabel={(item) => (item.channelId ? `${item.platform} · ${accounts.find((a) => a.id === item.channelId)?.account ?? 'account'}` : item.platform)} id={ids.language} />
      <ModelDialog open={dialog === 'model'} onOpenChange={(open) => setDialog(open ? 'model' : null)} catalog={models.data} value={{ model: choice.model, reasoning: choice.reasoningMapping.preference }} onApply={(next) => { choice.choose(next.model); choice.setReasoningFor(next.model, next.reasoning); }} reasoningFor={choice.reasoningFor} id={ids.model} />
      <VoiceDialog open={dialog === 'voice'} onOpenChange={(open) => setDialog(open ? 'voice' : null)} value={voiceMode} onApply={setVoiceMode} available={voiceAvailable} sampleCount={voiceSourceIds.length} voiceRevision={voiceRevision} modelLabel={choice.label} />
    </PageContainer>
  );
}

/**
 * Drafting without a connected account (the existing "drafts only" path) for workspaces that have
 * not connected anything yet: choose the platforms to write for. Connecting an account replaces this.
 */
function PlatformOnlyDialog({ open, onOpenChange, value, onApply }: { open: boolean; onOpenChange: (open: boolean) => void; value: DraftPlatform[]; onApply: (platforms: DraftPlatform[]) => void }) {
  const [staged, setStaged] = useState<DraftPlatform[]>(value);
  useEffect(() => {
    if (open) setStaged(value.length ? value : DEFAULT_TARGETS.map((t) => t.platform));
  }, [open, value]);
  return (
    <RafiiDialog open={open} onOpenChange={onOpenChange}>
      <RafiiDialogContent size='sm' aria-describedby={undefined}>
        <RafiiDialogHeader eyebrow='Channels' title='Where should it' accent='go?' intro='No account is connected yet, so drafts are written per platform. Connect an account to choose real destinations.' />
        <RafiiDialogBody className='flex flex-col gap-2'>
          {DRAFT_PLATFORMS.map((platform) => {
            const on = staged.includes(platform);
            return (
              <button key={platform} type='button' role='checkbox' aria-checked={on} onClick={() => setStaged((current) => (on ? current.filter((p) => p !== platform) : [...current, platform]))} className={cn('rafii-focus flex min-h-14 items-center gap-3 rounded-[var(--rafii-radius-control)] px-3 text-left', on ? 'rafii-glass-selected' : 'rafii-quiet')}>
                <ChannelIcon platform={platform} size='md' />
                <span className='flex min-w-0 flex-1 flex-col'>
                  <span className='text-foreground text-sm font-medium'>{platform}</span>
                  <span className='text-muted-foreground text-xs'>No account connected · drafts only</span>
                </span>
                <span aria-hidden className={cn('flex size-5 items-center justify-center rounded-full', on ? 'bg-foreground text-background' : 'rafii-quiet')}>{on && <Icons.check className='size-3' />}</span>
              </button>
            );
          })}
          <Link href='/app/channels' className='text-foreground mt-1 text-xs underline underline-offset-2'>
            Connect an account
          </Link>
        </RafiiDialogBody>
        <RafiiDialogFooter>
          <Button variant='action' size='control' className='w-full' disabled={staged.length === 0} onClick={() => { onApply(staged); onOpenChange(false); }}>
            Done · {staged.length} platform{staged.length === 1 ? '' : 's'}
            <Icons.check />
          </Button>
        </RafiiDialogFooter>
      </RafiiDialogContent>
    </RafiiDialog>
  );
}
