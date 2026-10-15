'use client';
import { CallRafii } from '@/features/rafii-phone/call-rafii';

/**
 * The Rafii conversation inside the side panel: one conversation per workspace that follows the person from page to
 * page, sent with the page's context. Answers render from their typed blocks; writing requests show the draft run,
 * automation or preference the writing pipeline made. States are the real ones: "working" only while a request is
 * in flight, each activity row only for a step the server reported, "applied" only after the server confirmed it.
 *
 * An answer can also ask the panel to act (docs/design/rafii-live-agent/CONTRACTS.md, Contract 2): open the page the
 * person asked for, start a guided walkthrough, or change how Rafii talks. `/` commands (Contract 7) either run here
 * (`client`) or travel with the message (`agent`).
 */
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent, type KeyboardEvent } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { IconMicrophone } from '@tabler/icons-react';
import { ThinkingShimmer } from '@/components/agents/loading-states/thinking-shimmer';
import { RafiiThinkingStatus } from '@/components/agents/thinking/rafii-thinking-status';
import { createImeGuard } from '@/lib/ime';
import { Icons } from '@/components/icons';
import { Button } from '@/components/ui/button';
import { Sheet, SheetContent, SheetTitle } from '@/components/ui/sheet';
import { siteConfig } from '@/config/site';
import { useModelChoice } from '@/features/agent/use-model';
import { SlashCommandMenu, type SlashPick } from '@/features/rafii-commands/command-menu';
import { autoActionsOf, createAutoLedger, type AutoAction } from '@/features/rafii-guide/auto-actions';
import { AgentExtras } from '@/features/rafii-voice/agent-extras';
import { AttachImage } from '@/features/rafii-voice/attach-image';
import { StyleButton } from '@/features/rafii-voice/style-sheet';
import { VoiceMode } from '@/features/rafii-voice/voice-mode';
import { ApiError } from '@/lib/api/client';
import { keys, useMe, useMessages, useModels, useSnapshot } from '@/lib/api/hooks';
import type { Message } from '@/lib/api/types';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import { commandPayload, parseSlash, type SlashCommand } from '@/lib/agent-runtime/commands';
import { panelActions, registerPanelActions } from '@/lib/agent-runtime/panel-actions';
import type { AgentStylePatch } from '@/lib/agent-runtime/style';
import type { AgentResult, AgentStatus, AgentTurnResponse } from '@/lib/agent-runtime/types';
import { agentStatusQuery, useAgent } from '@/lib/agent-runtime/use-agent';
import { thinkingOrbsEnabled } from '@/lib/agent-runtime/thinking-state';
import { useThinkingState } from '@/lib/agent-runtime/use-thinking-state';
import { useVoice, voiceSession } from '@/lib/agent-runtime/voice-session';
import { useTimeZone } from '@/lib/preferences';
import { timeDefaults } from '@/lib/time';
import { useMotionPreference } from '@/lib/rafii/motion';
import manifestJson from '@/lib/site-agent/route-manifest.json';
import { activityRows, isSiteAgentBody, suggestionsFor } from '@/lib/site-agent/panel-logic';
import { matchRoute, safeHref, type RouteManifest } from '@/lib/site-agent/routes';
import type { SiteAgentBlock, SiteAgentMessageBody, SiteAgentPageContext, SiteAgentTurnResult } from '@/lib/site-agent/types';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import type { UiSurface, UiTurnContextV1 } from '@/lib/agent-runtime/ui-contracts';
import type { ContinueRequest } from '@/features/agent/generative-ui/bridges/types';
import { currentUiContext, markFresh } from '@/features/agent/generative-ui/state/registry';
import { GeneratedAnswerSlot } from '@/features/agent/generative-ui/surfaces/generated-slot';
import { flushConversation } from '@/features/agent/generative-ui/surfaces/session';
import { useConsumerUiTransport } from '@/features/agent/generative-ui/surfaces/transport';
import { cn } from '@/lib/utils';
import { SiteAgentAnswer } from './answer';
import { ContextLens, useContextLensPreview } from './context-lens/context-lens';
import { exclusionsFor, lensLanguage, type LensItem } from './context-lens/model';
import { DelegatedMessage } from './delegated';
import { RafiiAvatar } from './rafii-avatar';
import { panelStore, usePanel } from './store';
import { currentPageContext } from './use-page-context';

const MANIFEST = manifestJson as RouteManifest;
const ENTITY_WORDS: Record<string, string> = { job: 'post', review: 'post', draft: 'draft', automation: 'automation', conversation: 'conversation', connection: 'account', source: 'source', help_document: 'article' };

/**
 * What answers asked the panel to do, run once each: only for a turn response in this session (text or voice), never
 * for history read back from the server, and never for an answer older than one that already ran. Module-level, so a
 * panel that re-mounts (dock ↔ sheet) keeps the record and a voice answer arriving with the panel closed still runs.
 */
const AUTO = createAutoLedger();

function newKey() {
  return typeof crypto !== 'undefined' && 'randomUUID' in crypto ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

/** Esc on the `/` menu: the menu keeps itself closed until the word changes; nothing else to do here. */
const noop = () => {};

/** A panel command runs in the browser and never reaches the server; it answers with a line for the panel, or none. */
async function runClientCommand(command: SlashCommand, args: string): Promise<string | null> {
  if (!command.execute) return 'That command isn’t available here.';
  try {
    return (await command.execute(args)) ?? null;
  } catch (error) {
    return error instanceof Error && error.message ? `That didn’t work: ${error.message}` : 'That didn’t work here.';
  }
}

export function SiteAgentChat({ onClose, onNavigate, autoFocus = true, surface = 'panel' }: { onClose: () => void; onNavigate?: () => void; autoFocus?: boolean; surface?: UiSurface }) {
  const { api, workspaceId } = useWorkspaceApi();
  const client = useQueryClient();
  const router = useRouter();
  const pathname = usePathname() ?? '/app';
  const access = useWorkspaceAccess();
  const canEdit = checkAccess(access, { permission: 'edit' });
  const models = useModels();
  // The panel always names a concrete writer (`choice.model`), on Auto the one the workspace default resolves to:
  // the site agent phrases its answers with it (the snapshot is the app shell's, already loaded).
  const snapshot = useSnapshot();
  const choice = useModelChoice(models.data, snapshot.data?.state.writerDefaults?.model);
  const me = useMe();
  const timeZone = useTimeZone();
  const { reduced } = useMotionPreference();
  // The Rafii Agent Runtime answers text turns when this deployment enables it; the site agent stays the fallback.
  const agent = useAgent();
  const agentOn = Boolean(agent.status?.manager.available);
  // Generated views (rafii-genui/1): this scope's transport; its key separates every principal/workspace's views and selections.
  const uiTransport = useConsumerUiTransport();
  const uiScope = uiTransport?.scopeKey ?? null;
  const [images, setImages] = useState<{ assetId: string; index: number | null }[]>([]);

  useEffect(() => {
    if (workspaceId) panelStore.load(workspaceId);
  }, [workspaceId]);
  const conversationId = usePanel((s) => (workspaceId ? (s.conversations[workspaceId] ?? null) : null));
  const busy = usePanel((s) => Boolean(workspaceId && s.busy[workspaceId]));
  const pendingThinking = useThinkingState(conversationId, busy && agentOn);
  // Added images wait for the next turn of this conversation in this workspace; they never follow a switch elsewhere.
  useEffect(() => {
    setImages([]);
  }, [workspaceId, conversationId]);
  const live = usePanel((s) => s.live);
  const page = usePanel((s) => s.page);
  // Context Lens (only when the server reports it on for this workspace): what the next typed message will use, and what the
  // person removed from it. Removals apply to the next message only and never follow a switch of workspace or conversation.
  const lensOn = Boolean(agentOn && agent.status?.contextLens?.enabled);
  const [lensRemoved, setLensRemoved] = useState<ReadonlySet<string>>(() => new Set());
  const lens = useContextLensPreview({ enabled: lensOn, api: agent.api, workspaceId, conversationId, pathname, page, images,
                                       uiScope: agent.status?.genui?.enabled ? uiScope : null,
                                       ttlSeconds: agent.status?.contextLens?.previewTtlSeconds ?? 120 });
  const lensPreview = lensOn ? (lens.data ?? null) : null;
  useEffect(() => {
    setLensRemoved(new Set());
  }, [workspaceId, conversationId]);
  const toggleLens = useCallback((item: LensItem) => {
    setLensRemoved((current) => {
      const next = new Set(current);
      if (next.has(item.id)) next.delete(item.id);
      else next.add(item.id);
      return next;
    });
  }, []);
  const thread = useMessages(conversationId);
  const messages = useMemo(() => thread.data?.messages ?? [], [thread.data]);

  const [text, setText] = useState('');
  const [optimistic, setOptimistic] = useState<string | null>(null);
  const [failure, setFailure] = useState<{ text: string; message: string } | null>(null);
  // Lines from `/` commands that ran in the panel; they are local and clear when a message goes to Rafii.
  const [notes, setNotes] = useState<{ id: number; text: string }[]>([]);
  const noteId = useRef(0);
  const [caret, setCaret] = useState(0);
  const [styleOpen, setStyleOpen] = useState(false);
  const [mode, setMode] = useState<'chat' | 'live'>('chat');
  const [menuOpen, setMenuOpen] = useState(false);
  const [capabilitiesOpen, setCapabilitiesOpen] = useState(false);
  const [contextOpen, setContextOpen] = useState(false);
  const liveState = useVoice((state) => state.state);
  const input = useRef<HTMLTextAreaElement>(null);
  const composer = useRef<HTMLDivElement>(null);
  const end = useRef<HTMLDivElement>(null);
  const workspaceRef = useRef(workspaceId);
  workspaceRef.current = workspaceId;
  // Identity changes even after A → B → A: an old response must not clear a new conversation's exclusions or uploads.
  const composerScope = useRef({ workspaceId, conversationId });
  if (composerScope.current.workspaceId !== workspaceId || composerScope.current.conversationId !== conversationId) {
    composerScope.current = { workspaceId, conversationId };
  }

  useEffect(() => {
    setNotes([]);
    // An explicit selected passage is composer text. It must not follow a switch to another workspace.
    setText('');
    setFailure(null);
    setOptimistic(null);
  }, [workspaceId]);

  // A conversation that no longer exists here (another workspace's id, or removed) starts a new one.
  useEffect(() => {
    if (thread.error instanceof ApiError && (thread.error.status === 404 || thread.error.status === 403) && workspaceId) panelStore.setConversation(workspaceId, null);
  }, [thread.error, workspaceId]);

  // "Ask Rafii about this" links hand in a question; the person still sends it.
  const pendingPrefill = usePanel((state) => state.prefill);
  useEffect(() => {
    const prefill = panelStore.takePrefill(workspaceId);
    if (prefill) setText((current) => current.trim() ? `${current}\n\n${prefill}` : prefill);
    if (autoFocus) input.current?.focus({ preventScroll: true });
  }, [autoFocus, pendingPrefill, workspaceId]);

  useEffect(() => {
    end.current?.scrollIntoView({ block: 'end', behavior: reduced ? 'auto' : 'smooth' });
  }, [messages.length, optimistic, busy, reduced, live, notes.length]);

  const route = matchRoute(MANIFEST, pathname)?.route ?? null;
  const entity = page?.selectedEntity ?? (route?.id === 'conversation' ? { type: 'conversation', id: pathname.split('/').pop() ?? '' } : null);
  const contextLabel = route ? `${route.title}${entity ? ` · selected ${ENTITY_WORDS[entity.type] ?? entity.type}` : ''}` : 'A page Rafii does not know';
  const suggestions = suggestionsFor(route?.family ?? null, canEdit);
  const voiceEnabled = Boolean(agent.status?.flags?.RAFII_VOICE_ENABLED && agent.status?.flags?.RAFII_AGENT_V2_ENABLED);
  const lastAssistant = messages.findLast((m) => m.role === 'assistant')?.messageId;

  /** Carry out what an answer asked for: its guide, or its link (re-checked against the route manifest), or a style. */
  const runAuto = useCallback(
    (actions: AutoAction[]) => {
      for (const action of actions) {
        if (action.kind === 'guide') {
          const start = panelActions().startGuide;
          if (!start) continue;
          void Promise.resolve(start(action.guideId)).then((started) => {
            if (started) onNavigate?.();
          });
        } else if (action.kind === 'navigate') {
          const href = safeHref(MANIFEST, action.href);
          if (!href) continue;
          const navigate = panelActions().navigate;
          if (navigate) navigate(href);
          else router.push(href);
          onNavigate?.();
        } else {
          void Promise.resolve(panelActions().setStyle?.(action.style as AgentStylePatch)).catch(() => undefined);
        }
      }
    },
    [onNavigate, router]
  );

  /** A panel command runs here and never reaches Rafii; its sentence becomes a line in the panel. */
  const runCommand = useCallback(async (command: SlashCommand, args: string) => {
    setFailure(null);
    const line = await runClientCommand(command, args);
    if (line) {
      noteId.current += 1;
      const id = noteId.current;
      setNotes((prev) => [...prev.slice(-3), { id, text: line }]);
    } else if (command.name === 'help') {
      // `/help` answers with the menu itself: a bare `/` lists every command.
      setText('/');
      setCaret(1);
      requestAnimationFrame(() => {
        const el = input.current;
        if (!el) return;
        el.focus();
        el.setSelectionRange(1, 1);
      });
    }
  }, []);

  const send = useCallback(
    async (raw: string, extra?: { uiContext?: UiTurnContextV1 }) => {
      const message = raw.trim();
      const w = workspaceId;
      if (!message || !w || panelStore.get().busy[w]) return;
      const slash = parseSlash(message);
      if (slash?.command.kind === 'client') {
        setText('');
        await runCommand(slash.command, slash.args);
        return;
      }
      // An agent command goes as typed, with its name and words beside it (the site agent gets the text only).
      const command = slash?.command.kind === 'agent' ? commandPayload(slash) : undefined;
      setFailure(null);
      setNotes([]);
      setOptimistic(message);
      setText('');
      panelStore.setBusy(w, true);
      const ticket = AUTO.begin();
      const current = panelStore.get();
      const sentScope = composerScope.current;
      try {
        const pageContext = currentPageContext(pathname);
        let result: SiteAgentTurnResult;
        let blocks: readonly SiteAgentBlock[] | undefined;
        let answerId: string | null;
        // Which runtime answers is decided by the deployment status. A turn sent before it loaded must not silently fall back
        // to the site agent (no generated view, no agent features): wait for it here, bounded (the turn is already busy).
        const status = agent.status ?? (await loadStatus(client, agent.api, w));
        const agentOn = Boolean(status?.manager.available);
        const genuiOn = Boolean(status?.genui?.enabled);
        if (agentOn) {
          // The view the person is using (and its stored selection) travels as uiContext; its unsaved state is saved first so
          // "the second one" means what they just picked. Text and voice read the same registry.
          const conversation = current.conversations[w] ?? null;
          if (genuiOn) await flushConversation(uiScope, conversation);
          const uiContext = genuiOn ? (extra?.uiContext ?? currentUiContext(uiScope, conversation)) : undefined;
          // Context Lens: the chips the person removed go with the message; the server leaves them out of this turn.
          const exclude = status?.contextLens?.enabled ? exclusionsFor(lensPreview, lensRemoved) : [];
          // The Agent Runtime answers (same conversation; it falls back to the site agent by itself when it must).
          const response = await agent.api.turn(w, {
            message,
            idempotencyKey: newKey(),
            conversationId: current.conversations[w] ?? null,
            modality: 'text',
            pageContext,
            // The role is explicit: a panel image is something Rafii looks at, never media for a post (SPEC §9).
            attachments: images.map((image) => ({ assetId: image.assetId, role: 'reference' as const })),
            timeZone,
            model: choice.model,
            ...(command ? { command } : {}),
            ...(uiContext ? { uiContext } : {}),
            ...(exclude.length ? { contextLens: { exclude } } : {})
          });
          if (composerScope.current !== sentScope) return;
          setImages([]);
          if (status?.contextLens?.enabled) {
            setLensRemoved((pending) => pending === lensRemoved ? new Set() : pending);
            void client.invalidateQueries({ queryKey: ['agent-runtime', 'context-lens', w] });
          }
          // A turn answered here may build its one interactive view (the slot starts it; history never does).
          if (genuiOn && uiScope && response.runId && response.result?.ui?.eligible) markFresh(uiScope, response.runId);
          voiceSession.typedExchange(message, response.result);
          result = response.siteAgent ?? { conversationId: response.conversationId, runId: response.runId, status: response.status, messageId: response.messageId };
          blocks = response.result?.blocks ?? response.siteAgent?.message?.siteAgent?.blocks;
          answerId = response.messageId ?? response.siteAgent?.messageId ?? null;
        } else {
          // The site agent has no commands: a typed `/command` goes as plain text.
          result = await api.siteAgentTurn(w, {
            message,
            idempotencyKey: newKey(),
            ...(current.conversations[w] ? { conversationId: current.conversations[w] } : {}),
            model: choice.model,
            timeZone,
            pageContext
          });
          blocks = result.message?.siteAgent?.blocks;
          answerId = result.messageId ?? null;
        }
        if (composerScope.current !== sentScope) return;
        panelStore.setConversation(w, result.conversationId);
        if (result.runId && !result.delegated) panelStore.setLive(result.runId, { events: result.events ?? [], composing: Boolean(result.needsCompose) });
        await client.invalidateQueries({ queryKey: keys.messages(w, result.conversationId) });
        void client.invalidateQueries({ queryKey: keys.conversations(w) });
        setOptimistic(null);
        if (result.needsCompose && result.runId) {
          const final = await api.siteAgentCompose(w, result.runId);
          panelStore.setLive(result.runId, { events: final.events ?? [], composing: false });
          if (workspaceRef.current !== w) return;
          await client.invalidateQueries({ queryKey: keys.messages(w, result.conversationId) });
          blocks = final.message?.siteAgent?.blocks ?? blocks;
          answerId = final.messageId ?? answerId;
        }
        if (result.delegated) void client.invalidateQueries({ queryKey: keys.snapshot(w) });
        // "Take me to …" or "show me how": the answer's own link or guide, once, and only for the newest request.
        if (AUTO.claim(answerId ?? result.runId ?? `turn:${ticket}`, ticket)) runAuto(autoActionsOf(blocks, 'text'));
      } catch (error) {
        if (composerScope.current !== sentScope) return;
        setOptimistic(null);
        // No reply means the request may still have run (a link, a saved draft); only the server's own error says what happened.
        setFailure({ text: message, message: error instanceof ApiError ? error.message : "Rafii's answer didn't arrive. If you asked for a change, check before asking again: it may already have been made." });
        const conversation = panelStore.get().conversations[w];
        if (conversation) void client.invalidateQueries({ queryKey: keys.messages(w, conversation) });
      } finally {
        panelStore.setBusy(w, false);
      }
    },
    [agent.api, agent.status, api, choice.model, client, images, lensPreview, lensRemoved, pathname, runAuto, runCommand, timeZone, uiScope, workspaceId]
  );
  const continueFromView = useCallback((request: ContinueRequest) => {
    void send(request.message, { uiContext: { artifactId: request.artifactId, artifactRevision: request.artifactRevision, stateRevision: request.stateRevision } });
  }, [send]);

  // Voice Mode reads the page when a spoken request is delegated (the call outlives this component's render).
  const voicePageContext = useCallback((): SiteAgentPageContext => currentPageContext(window.location.pathname, { voice: true }), []);
  const onVoiceConversation = useCallback((id: string) => {
    if (workspaceId) panelStore.setConversation(workspaceId, id);
  }, [workspaceId]);
  const onVoiceAnswer = useCallback((response: AgentTurnResponse) => {
    // A spoken "show me how" or "take me to" runs here too; the call itself carries out its voice commands.
    const ticket = AUTO.begin();
    if (AUTO.claim(response.messageId ?? response.runId ?? response.traceId ?? `voice:${ticket}`, ticket)) {
      runAuto(autoActionsOf(response.result?.blocks ?? response.siteAgent?.message?.siteAgent?.blocks, 'voice'));
    }
    if (!workspaceId || !response.conversationId) return;
    void client.invalidateQueries({ queryKey: keys.messages(workspaceId, response.conversationId) });
    void client.invalidateQueries({ queryKey: keys.snapshot(workspaceId) });
  }, [client, runAuto, workspaceId]);

  const composingRun = messages.find((m) => m.role === 'assistant' && m.runId && live[m.runId]?.composing)?.runId ?? null;

  const ime = useRef(createImeGuard());

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    void send(text);
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    // The command menu handles its own keys (Enter picks a command) and marks them handled.
    if (event.defaultPrevented || event.nativeEvent.defaultPrevented) return;
    // Safari commits a composition with compositionend, then an Enter keydown (keyCode 229, isComposing false).
    if (event.key === 'Enter' && !event.shiftKey && !ime.current.composing(event)) {
      event.preventDefault();
      void send(text);
    }
  }

  const startOver = useCallback(() => {
    if (!workspaceId) return;
    panelStore.setConversation(workspaceId, null);
    setFailure(null);
    input.current?.focus();
  }, [workspaceId]);

  // `/new` does what the + button does; `/style` (and a spoken style request) opens the header's style sheet.
  useEffect(() => registerPanelActions({ newConversation: startOver, openStyle: () => setStyleOpen(true) }), [startOver]);

  /** A command picked from the `/` menu: the text becomes what the pick says; a panel command with its words runs now. */
  const pickCommand = useCallback(
    (command: SlashCommand, args: string, pick: SlashPick) => {
      setText(pick.value);
      setCaret(pick.caret);
      if (pick.action === 'run') void runCommand(command, args);
    },
    [runCommand]
  );

  const empty = !conversationId || (!thread.isLoading && messages.length === 0);
  const name = me.data && 'displayName' in me.data ? String((me.data as { displayName?: string | null }).displayName ?? '').split(' ')[0] : '';

  return (
    <div className='rafii-chat @container flex h-full min-h-0 flex-col' data-rafii-mode={mode}>
      <div className='rafii-chat-header flex shrink-0 items-center gap-2.5 px-4 pt-3 pb-2'>
        <Button type='button' variant='quiet' size='icon-control' className='shrink-0' aria-label={mode === 'live' ? 'Back to chat' : 'Close Rafii'} onClick={mode === 'live' ? () => setMode('chat') : onClose}>
          {mode === 'live' ? <Icons.chevronLeft className='size-5' /> : <Icons.close className='size-5' />}
        </Button>
        <RafiiAvatar size={36} thinking={busy} />
        <div className='flex min-w-0 flex-1 flex-col'>
          <h2 className='text-base leading-tight font-semibold'>{mode === 'live' ? `${siteConfig.name} Live` : siteConfig.name}</h2>
          <button type='button' className='rafii-focus text-muted-foreground w-fit max-w-full truncate rounded text-left text-xs' title={contextLabel} aria-expanded={contextOpen} onClick={() => setContextOpen((open) => !open)}>
            Viewing {contextLabel} <Icons.chevronDown aria-hidden className='inline size-3' />
          </button>
        </div>
        {mode === 'chat' && voiceEnabled && <Button type='button' variant='quiet' size='icon-control' aria-label='Open Rafii Live' onClick={() => setMode('live')}>
          <IconMicrophone className='size-5' />
          <span className='sr-only'>{liveState === 'live' ? 'Live call in progress' : 'Start voice conversation'}</span>
        </Button>}
        <Button type='button' variant='quiet' size='icon-control' aria-label='More Rafii options' aria-expanded={menuOpen} onClick={() => setMenuOpen((open) => !open)}>
          <Icons.dots className='size-5' />
        </Button>
      </div>
      {contextOpen && <section className='rafii-glass mx-4 mb-2 shrink-0 rounded-2xl p-4 text-sm' aria-label='Current page context'>
        <p className='font-medium'>Rafii is looking at {contextLabel}</p>
        {entity && <p className='text-muted-foreground mt-1'>Selected {ENTITY_WORDS[entity.type] ?? entity.type}: {entity.id}</p>}
        {page?.visibleState && Object.keys(page.visibleState).length > 0 && <ul className='text-muted-foreground mt-2 list-disc pl-5'>{Object.entries(page.visibleState).map(([key, value]) => <li key={key}>{key}: {Array.isArray(value) ? value.join(', ') : String(value)}</li>)}</ul>}
        <p className='text-muted-foreground mt-2'>Page headings and selected items are shared as context. Typed fields and unselected files are not read from the screen. Workspace access still follows your permissions.</p>
      </section>}
      {menuOpen && <div className='rafii-glass mx-4 mb-2 flex max-h-[60dvh] shrink-0 flex-col gap-2 overflow-y-auto rounded-2xl p-3' role='group' aria-label='Rafii options'>
        <StyleButton open={styleOpen} onOpenChange={setStyleOpen} />
        <Button type='button' variant='quiet' className='min-h-11 justify-start' onClick={() => { startOver(); setMenuOpen(false); }} disabled={busy}><Icons.add className='size-4' /> New conversation</Button>
        {conversationId && <Link href={`/app/agent/${conversationId}`} onClick={onNavigate} className='rafii-focus flex min-h-11 items-center gap-2 rounded-lg px-3 text-sm'><Icons.externalLink className='size-4' /> Open full conversation</Link>}
        <Link href='/app/account/models' onClick={onNavigate} className='rafii-focus flex min-h-11 items-center gap-2 rounded-lg px-3 text-sm'>Model settings</Link>
        <Link href='/app/channels' onClick={onNavigate} className='rafii-focus flex min-h-11 items-center gap-2 rounded-lg px-3 text-sm'>Connected accounts</Link>
        <Link href='/app/account/billing' onClick={onNavigate} className='rafii-focus flex min-h-11 items-center gap-2 rounded-lg px-3 text-sm'>Usage &amp; plan</Link>
        <Link href='/app/help' onClick={onNavigate} className='rafii-focus flex min-h-11 items-center gap-2 rounded-lg px-3 text-sm'><Icons.help className='size-4' /> Help articles</Link>
        <CallRafii conversationId={conversationId} onConversation={onVoiceConversation} />
      </div>}
      {mode === 'live' && voiceEnabled ? <VoiceMode immersive onKeyboard={() => setMode('chat')} contextLabel={contextLabel} conversationId={conversationId} pageContext={voicePageContext} onConversation={onVoiceConversation} onAnswer={onVoiceAnswer} timeZone={timeZone} model={choice.model} /> : <>
      <div className='rafii-chat-log min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 pb-3' role='log' aria-live='polite' aria-relevant='additions' aria-label={`Conversation with ${siteConfig.name}`}>
        {empty && !optimistic ? (
          <div className='flex flex-col items-start gap-5 pt-7'>
            <RafiiAvatar size={88} variant='full' className='self-center' />
            <div><h3 className='text-2xl font-semibold tracking-tight'>{name ? `Hi ${name}, ` : 'Hi, '}let’s get to work.</h3><p className='text-muted-foreground mt-2 text-sm leading-relaxed'>I can help with {route?.title ?? 'your workspace'}. Ask, create, or plan; you review changes before they happen.</p></div>
            <div className='flex flex-col items-stretch gap-2 self-stretch' role='group' aria-label='Suggested questions'>
              {suggestions.map((item) => (
                <Button key={item} type='button' variant='glass' className='h-auto min-h-14 justify-between rounded-2xl px-4 py-3 text-left text-sm whitespace-normal' onClick={() => void send(item)} disabled={busy}>
                  <span>{item}</span><Icons.arrowRight aria-hidden className='size-4 shrink-0' />
                </Button>
              ))}
            </div>
          </div>
        ) : (
          <ol className='flex flex-col gap-4 pt-2'>
            {thread.isLoading && <li className='text-muted-foreground text-xs'>Loading the conversation…</li>}
            {messages.map((message) => (
              <ThreadItem key={message.messageId} message={message} conversationId={conversationId} latest={message.messageId === lastAssistant} liveEvents={message.runId ? live[message.runId] : undefined}
                          onAsk={(value) => void send(value)} onNavigate={onNavigate} onStop={message.runId ? () => void api.siteAgentCancel(workspaceId as string, message.runId as string) : undefined}
                          surface={surface} onContinue={continueFromView} onOpenPath={(path) => { router.push(path); onNavigate?.(); }} />
            ))}
            {optimistic && (
              <li className='flex flex-col items-end gap-1'>
                <p className='rafii-glass max-w-[85%] rounded-2xl px-3 py-2 text-sm break-words whitespace-pre-wrap'>{optimistic}</p>
                {thinkingOrbsEnabled() && agentOn ? (
                  <RafiiThinkingStatus op={pendingThinking.op} startedAt={pendingThinking.startedAt} showElapsed={false} className='text-[11px]' />
                ) : (
                  <span role='status' className='text-muted-foreground flex items-center gap-1.5 text-[11px]'>
                    <ThinkingShimmer>Reading your question</ThinkingShimmer>
                  </span>
                )}
              </li>
            )}
            {failure && (
              <li role='alert' className='flex flex-col gap-2'>
                <p className='text-destructive text-sm'>{failure.message}</p>
                <Button type='button' variant='glass' size='sm' className='self-start' onClick={() => void send(failure.text)} disabled={busy}>
                  Try again
                </Button>
              </li>
            )}
          </ol>
        )}
        {notes.length > 0 && (
          <ul className='flex flex-col gap-1.5 pt-3' aria-label='Panel commands'>
            {notes.map((note) => (
              <li key={note.id} role='status' className='text-muted-foreground flex items-start justify-center gap-1.5 text-center text-xs'>
                <Icons.slash className='mt-0.5 size-3 shrink-0' aria-hidden />
                <span className='break-words'>{note.text}</span>
              </li>
            ))}
          </ul>
        )}
        <div ref={end} />
      </div>

      <form onSubmit={onSubmit} className='rafii-chat-form relative shrink-0 px-3 pt-2 pb-[calc(0.75rem+env(safe-area-inset-bottom))]'>
        {!agent.status && agent.statusError ? (
          // The agent runtime's status could not be read after its retries: say what still works instead of quietly answering
          // with the basic assistant (no interactive views, no agent tools) — and let the person check again.
          <div role='status' data-rafii-agent-status='unavailable' className='text-muted-foreground mb-2 flex flex-wrap items-center gap-2 px-2 text-xs'>
            <span>Rafii’s full assistant isn’t reachable right now. Answers still work; interactive views are off until it’s back.</span>
            <Button type='button' variant='quiet' size='xs' onClick={() => void agent.refetchStatus()}>Check again</Button>
          </div>
        ) : null}
        {lensOn && (
          <ContextLens preview={lensPreview} loading={lens.isLoading} failed={lens.isError} onRetry={() => void lens.refetch()} removed={lensRemoved}
            onToggle={toggleLens} text={text} lang={lensLanguage(timeDefaults().locale)} timeZone={timeZone} onNewConversation={startOver} />
        )}
        <SlashCommandMenu value={text} caret={caret} anchorRef={composer} onPick={pickCommand} onDismiss={noop} />
        <div ref={composer} className='rafii-composer flex items-end gap-2 rounded-[var(--rafii-radius-composer)] p-2'>
          <Button type='button' variant='quiet' size='icon-control' aria-label='Add or create' aria-haspopup='dialog' onClick={() => setCapabilitiesOpen(true)}><Icons.add className='size-5' /></Button>
          <textarea
            ref={input}
            value={text}
            onChange={(event) => {
              setText(event.target.value);
              setCaret(event.target.selectionStart ?? event.target.value.length);
            }}
            onSelect={(event) => setCaret(event.currentTarget.selectionStart ?? event.currentTarget.value.length)}
            onKeyDown={onKeyDown}
            onCompositionStart={() => ime.current.onCompositionStart()}
            onCompositionEnd={() => ime.current.onCompositionEnd()}
            rows={2}
            maxLength={4000}
            aria-label={`Ask ${siteConfig.name}`}
            placeholder={route ? `Ask about ${route.title}, or anything in ${siteConfig.name}…` : `Ask ${siteConfig.name}…`}
            className='placeholder:text-muted-foreground max-h-40 min-h-14 flex-1 resize-none bg-transparent px-2 py-3 text-base leading-snug outline-none field-sizing-content'
          />
          {composingRun ? (
            <Button type='button' variant='glass' size='icon-control' aria-label='Stop this answer' onClick={() => void api.siteAgentCancel(workspaceId as string, composingRun)}>
              <Icons.handStop className='size-4' />
            </Button>
          ) : text.trim() ? (
            <Button type='submit' variant='action' size='icon-control' aria-label='Send' disabled={!text.trim() || busy}>
              <Icons.send className='size-4' />
            </Button>
          ) : voiceEnabled ? (
            <Button type='button' variant='action' size='icon-control' aria-label='Open Rafii Live' onClick={() => setMode('live')}><IconMicrophone className='size-5' /></Button>
          ) : null}
        </div>
      </form>
      </>}
      <Sheet open={capabilitiesOpen} onOpenChange={setCapabilitiesOpen}>
        <SheetContent side='bottom' aria-label='Add to Rafii' data-rafii-capabilities className='rafii-elevated max-h-[70dvh] gap-3 rounded-t-3xl p-5 pb-[calc(1rem+env(safe-area-inset-bottom))]'>
          <SheetTitle className='text-lg font-semibold'>Add to Rafii</SheetTitle>
          <div className='grid grid-cols-2 gap-2 text-sm'>
            {agentOn && <div className='rafii-glass flex min-h-14 items-center gap-2 rounded-xl px-3'><AttachImage conversationId={conversationId} onAttached={(image) => { setImages((prev) => [...prev, image].slice(-4)); setCapabilitiesOpen(false); }} disabled={busy} /><span>Photo</span></div>}
            <button type='button' className='rafii-glass rafii-focus min-h-14 rounded-xl px-3 text-left' onClick={() => { setText('Research '); setCapabilitiesOpen(false); input.current?.focus(); }}>Research</button>
            <Link href='/app/library' onClick={onNavigate} className='rafii-glass rafii-focus flex min-h-14 items-center rounded-xl px-3'>Library</Link>
            <button type='button' className='rafii-glass rafii-focus min-h-14 rounded-xl px-3 text-left' onClick={() => { setText('Plan a campaign for '); setCapabilitiesOpen(false); input.current?.focus(); }}>Plan a campaign</button>
            <Link href='/app/ideas' onClick={onNavigate} className='rafii-glass rafii-focus flex min-h-14 items-center rounded-xl px-3'>Sources</Link>
            <Link href='/app/account/models' onClick={onNavigate} className='rafii-glass rafii-focus flex min-h-14 items-center rounded-xl px-3'>Model settings</Link>
          </div>
          <p className='text-muted-foreground text-xs'>Photos join this conversation. Other files are managed in Library and Sources.</p>
        </SheetContent>
      </Sheet>
    </div>
  );
}

/** The agent runtime status for a workspace when the panel's own query hasn't answered yet (shared cache, at most 8 s). */
async function loadStatus(client: ReturnType<typeof useQueryClient>, api: ReturnType<typeof useAgent>['api'], workspaceId: string): Promise<AgentStatus | null> {
  const query = agentStatusQuery(api, workspaceId);
  const cached = client.getQueryData<AgentStatus>(query.queryKey);
  if (cached) return cached;
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    return await Promise.race([
      client.fetchQuery(query),
      new Promise<null>((resolve) => { timer = setTimeout(() => resolve(null), 8000); })
    ]);
  } catch {
    return null;
  } finally {
    if (timer) clearTimeout(timer);
  }
}

function ThreadItem({ message, conversationId, latest, liveEvents, onAsk, onNavigate, onStop, surface, onContinue, onOpenPath }: {
  message: Message;
  conversationId: string | null;
  latest: boolean;
  liveEvents?: { events: { type: string }[]; composing: boolean };
  onAsk: (text: string) => void;
  onNavigate?: () => void;
  onStop?: () => void;
  surface: UiSurface;
  onContinue: (request: ContinueRequest) => void;
  onOpenPath: (path: string) => void;
}) {
  const body = message.body as SiteAgentMessageBody;
  const agentBody = (body as { agent?: AgentResult & { modality?: string } }).agent;
  if (message.role === 'user') {
    const spoken = agentBody?.modality === 'voice';
    return (
      <li className='flex justify-end'>
        <p className='rafii-glass max-w-[85%] rounded-2xl px-3 py-2 text-sm break-words whitespace-pre-wrap'>
          {spoken && <span className='text-muted-foreground mr-1 text-[11px]'>Said:</span>}
          {body.text}
        </p>
      </li>
    );
  }
  if (isSiteAgentBody(body) && body.siteAgent) {
    const running = body.siteAgent.status === 'running' || body.pending;
    if (running) {
      const rows = activityRows(liveEvents?.events as never, true);
      return (
        <li className='flex gap-2.5'>
          <RafiiAvatar size={24} thinking />
          <div className='flex min-w-0 flex-1 flex-col gap-1.5' role='status'>
            <ul className='flex flex-col gap-1 text-xs'>
              {rows.map((row) => (
                <li key={row.key} className={cn('flex items-center gap-1.5', row.status === 'running' ? 'text-foreground' : 'text-muted-foreground')}>
                  {row.status === 'running' ? <ThinkingShimmer>{row.label}</ThinkingShimmer> : <>{row.status === 'done' ? <Icons.check className='size-3' aria-hidden /> : <Icons.warning className='size-3' aria-hidden />} {row.label} {row.status !== 'done' && `(${row.status})`}</>}
                </li>
              ))}
            </ul>
            {onStop && (
              <Button type='button' variant='quiet' size='xs' className='self-start' onClick={onStop}>
                Stop
              </Button>
            )}
          </div>
        </li>
      );
    }
    return (
      <li className='flex gap-2.5'>
        <RafiiAvatar size={24} className='mt-0.5' />
        <article className='min-w-0 flex-1' aria-label={`${siteConfig.name}'s answer`}>
          <SiteAgentAnswer body={body.siteAgent} actions={{ onAsk, onNavigate, messageId: message.messageId, conversationId, latest }}
            generated={agentBody ? <GeneratedAnswerSlot message={message} conversationId={conversationId} surface={surface} latest={latest} onContinue={onContinue}
              onNavigate={onOpenPath} /> : undefined} />
          {agentBody && agentBody.traceId && <AgentExtras result={agentBody} conversationId={conversationId} />}
        </article>
      </li>
    );
  }
  return (
    <li className='flex gap-2.5'>
      <RafiiAvatar size={24} className='mt-0.5' />
      <div className='min-w-0 flex-1'>
        <DelegatedMessage body={body} runId={message.runId} conversationId={conversationId} latest={latest} onAsk={onAsk} onNavigate={onNavigate} />
      </div>
    </li>
  );
}
