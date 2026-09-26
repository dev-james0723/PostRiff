'use client';

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
import { ThinkingShimmer } from '@/components/agents/loading-states/thinking-shimmer';
import { createImeGuard } from '@/lib/ime';
import { Icons } from '@/components/icons';
import { Button } from '@/components/ui/button';
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
import type { AgentResult, AgentTurnResponse } from '@/lib/agent-runtime/types';
import { useAgent } from '@/lib/agent-runtime/use-agent';
import { voiceSession } from '@/lib/agent-runtime/voice-session';
import { useTimeZone } from '@/lib/preferences';
import { useMotionPreference } from '@/lib/rafii/motion';
import manifestJson from '@/lib/site-agent/route-manifest.json';
import { activityRows, isSiteAgentBody, suggestionsFor } from '@/lib/site-agent/panel-logic';
import { matchRoute, safeHref, type RouteManifest } from '@/lib/site-agent/routes';
import type { SiteAgentBlock, SiteAgentMessageBody, SiteAgentPageContext, SiteAgentTurnResult } from '@/lib/site-agent/types';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { cn } from '@/lib/utils';
import { SiteAgentAnswer } from './answer';
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

export function SiteAgentChat({ onClose, onNavigate, autoFocus = true }: { onClose: () => void; onNavigate?: () => void; autoFocus?: boolean }) {
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
  const [images, setImages] = useState<{ assetId: string; index: number | null }[]>([]);

  useEffect(() => {
    if (workspaceId) panelStore.load(workspaceId);
  }, [workspaceId]);
  const conversationId = usePanel((s) => (workspaceId ? (s.conversations[workspaceId] ?? null) : null));
  const busy = usePanel((s) => Boolean(workspaceId && s.busy[workspaceId]));
  // Added images wait for the next turn of this conversation in this workspace; they never follow a switch elsewhere.
  useEffect(() => {
    setImages([]);
  }, [workspaceId, conversationId]);
  const live = usePanel((s) => s.live);
  const page = usePanel((s) => s.page);
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
  const input = useRef<HTMLTextAreaElement>(null);
  const composer = useRef<HTMLDivElement>(null);
  const end = useRef<HTMLDivElement>(null);
  const workspaceRef = useRef(workspaceId);
  workspaceRef.current = workspaceId;

  useEffect(() => {
    setNotes([]);
  }, [workspaceId]);

  // A conversation that no longer exists here (another workspace's id, or removed) starts a new one.
  useEffect(() => {
    if (thread.error instanceof ApiError && (thread.error.status === 404 || thread.error.status === 403) && workspaceId) panelStore.setConversation(workspaceId, null);
  }, [thread.error, workspaceId]);

  // "Ask Rafii about this" links hand in a question; the person still sends it.
  useEffect(() => {
    const prefill = panelStore.takePrefill();
    if (prefill) setText(prefill);
    if (autoFocus) input.current?.focus({ preventScroll: true });
  }, [autoFocus]);

  useEffect(() => {
    end.current?.scrollIntoView({ block: 'end', behavior: reduced ? 'auto' : 'smooth' });
  }, [messages.length, optimistic, busy, reduced, live, notes.length]);

  const route = matchRoute(MANIFEST, pathname)?.route ?? null;
  const entity = page?.selectedEntity ?? (route?.id === 'conversation' ? { type: 'conversation', id: pathname.split('/').pop() ?? '' } : null);
  const contextLabel = route ? `${route.title}${entity ? ` · selected ${ENTITY_WORDS[entity.type] ?? entity.type}` : ''}` : 'A page Rafii does not know';
  const suggestions = suggestionsFor(route?.family ?? null, canEdit);
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
    async (raw: string) => {
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
      try {
        const pageContext = currentPageContext(pathname);
        let result: SiteAgentTurnResult;
        let blocks: readonly SiteAgentBlock[] | undefined;
        let answerId: string | null;
        if (agentOn) {
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
            ...(command ? { command } : {})
          });
          setImages([]);
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
        if (workspaceRef.current !== w) return;
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
        if (workspaceRef.current !== w) return;
        setOptimistic(null);
        // No reply means the request may still have run (a link, a saved draft); only the server's own error says what happened.
        setFailure({ text: message, message: error instanceof ApiError ? error.message : "Rafii's answer didn't arrive. If you asked for a change, check before asking again: it may already have been made." });
        const conversation = panelStore.get().conversations[w];
        if (conversation) void client.invalidateQueries({ queryKey: keys.messages(w, conversation) });
      } finally {
        panelStore.setBusy(w, false);
      }
    },
    [agent.api, agentOn, api, choice.model, client, images, pathname, runAuto, runCommand, timeZone, workspaceId]
  );

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
    <div className='@container flex h-full min-h-0 flex-col'>
      <div className='flex shrink-0 items-center gap-2.5 px-4 pt-3 pb-2'>
        <RafiiAvatar size={32} thinking={busy} />
        <div className='flex min-w-0 flex-1 flex-col'>
          <h2 className='text-sm leading-tight font-semibold'>{siteConfig.name}</h2>
          <span className='text-muted-foreground truncate text-[11px]' title={contextLabel}>
            Looking at: {contextLabel}
          </span>
        </div>
        {/* How Rafii talks; below about 360px of panel width the pill keeps only its icon. */}
        <StyleButton open={styleOpen} onOpenChange={setStyleOpen} className='shrink-0 @max-[22.5rem]:px-2 @max-[22.5rem]:[&>.truncate]:hidden' />
        <Button type='button' variant='quiet' size='icon-sm' aria-label='Start a new conversation' title='New conversation' onClick={startOver} disabled={busy}>
          <Icons.add className='size-4' />
        </Button>
        {conversationId && (
          <Link
            href={`/app/agent/${conversationId}`}
            onClick={onNavigate}
            aria-label='Open this conversation in full'
            title='Open in full'
            className='rafii-focus text-muted-foreground hover:text-foreground inline-flex size-7 items-center justify-center rounded-[var(--rafii-radius-control)]'
          >
            <Icons.externalLink className='size-4' />
          </Link>
        )}
        <Link href='/app/help' onClick={onNavigate} aria-label='Rafii help articles' title='Help articles' className='rafii-focus text-muted-foreground hover:text-foreground inline-flex size-7 items-center justify-center rounded-[var(--rafii-radius-control)]'>
          <Icons.help className='size-4' />
        </Link>
        <Button type='button' variant='quiet' size='icon-sm' aria-label='Close Rafii' onClick={onClose}>
          <Icons.close className='size-4' />
        </Button>
      </div>

      {agent.status?.flags?.RAFII_VOICE_ENABLED && agent.status?.flags?.RAFII_AGENT_V2_ENABLED && (
        <VoiceMode conversationId={conversationId} pageContext={voicePageContext} onConversation={onVoiceConversation} onAnswer={onVoiceAnswer} timeZone={timeZone} model={choice.model} />
      )}
      <div className='min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 pb-3' role='log' aria-live='polite' aria-relevant='additions' aria-label={`Conversation with ${siteConfig.name}`}>
        {empty && !optimistic ? (
          <div className='flex flex-col items-start gap-3 pt-4'>
            <RafiiAvatar size={88} variant='full' className='self-center' />
            <p className='text-sm leading-relaxed'>
              {name ? `Hi ${name}, ` : 'Hi, '}I&apos;m {siteConfig.name}. Ask me about this page, a post or an automation, or ask me to write something. I show what I looked at, and I never publish, reply or change settings from a chat.
            </p>
            <div className='flex flex-col items-stretch gap-2 self-stretch' role='group' aria-label='Suggested questions'>
              {suggestions.map((item) => (
                <Button key={item} type='button' variant='glass' className='h-auto min-h-10 justify-start px-3 py-2 text-left text-sm whitespace-normal' onClick={() => void send(item)} disabled={busy}>
                  {item}
                </Button>
              ))}
            </div>
          </div>
        ) : (
          <ol className='flex flex-col gap-4 pt-2'>
            {thread.isLoading && <li className='text-muted-foreground text-xs'>Loading the conversation…</li>}
            {messages.map((message) => (
              <ThreadItem key={message.messageId} message={message} conversationId={conversationId} latest={message.messageId === lastAssistant} liveEvents={message.runId ? live[message.runId] : undefined}
                          onAsk={(value) => void send(value)} onNavigate={onNavigate} onStop={message.runId ? () => void api.siteAgentCancel(workspaceId as string, message.runId as string) : undefined} />
            ))}
            {optimistic && (
              <li className='flex flex-col items-end gap-1'>
                <p className='rafii-glass max-w-[85%] rounded-2xl px-3 py-2 text-sm break-words whitespace-pre-wrap'>{optimistic}</p>
                <span role='status' className='text-muted-foreground flex items-center gap-1.5 text-[11px]'>
                  <ThinkingShimmer>Reading your question</ThinkingShimmer>
                </span>
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

      <form onSubmit={onSubmit} className='relative shrink-0 px-3 pt-1 pb-[calc(0.75rem+env(safe-area-inset-bottom))]'>
        <SlashCommandMenu value={text} caret={caret} anchorRef={composer} onPick={pickCommand} onDismiss={noop} />
        <div ref={composer} className='rafii-composer flex items-end gap-2 rounded-[var(--rafii-radius-composer)] p-2'>
          {agentOn && <AttachImage conversationId={conversationId} onAttached={(image) => setImages((prev) => [...prev, image].slice(-4))} disabled={busy} />}
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
            rows={1}
            maxLength={4000}
            aria-label={`Ask ${siteConfig.name}`}
            placeholder={route ? `Ask about ${route.title}, or anything in ${siteConfig.name}…` : `Ask ${siteConfig.name}…`}
            className='placeholder:text-muted-foreground max-h-40 min-h-11 flex-1 resize-none bg-transparent px-2 py-2.5 text-base leading-snug outline-none md:text-sm field-sizing-content'
          />
          {composingRun ? (
            <Button type='button' variant='glass' size='icon-control' aria-label='Stop this answer' onClick={() => void api.siteAgentCancel(workspaceId as string, composingRun)}>
              <Icons.handStop className='size-4' />
            </Button>
          ) : (
            <Button type='submit' variant='action' size='icon-control' aria-label='Send' disabled={!text.trim() || busy}>
              <Icons.send className='size-4' />
            </Button>
          )}
        </div>
        <p className='text-muted-foreground px-2 pt-1.5 text-[10.5px] leading-snug'>
          {siteConfig.name} answers from its help and your workspace, and can propose changes you apply yourself.
        </p>
      </form>
    </div>
  );
}

function ThreadItem({ message, conversationId, latest, liveEvents, onAsk, onNavigate, onStop }: {
  message: Message;
  conversationId: string | null;
  latest: boolean;
  liveEvents?: { events: { type: string }[]; composing: boolean };
  onAsk: (text: string) => void;
  onNavigate?: () => void;
  onStop?: () => void;
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
                  {row.status === 'running' ? <ThinkingShimmer>{row.label}</ThinkingShimmer> : <><Icons.check className='size-3' aria-hidden /> {row.label}</>}
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
          <SiteAgentAnswer body={body.siteAgent} actions={{ onAsk, onNavigate, messageId: message.messageId, conversationId, latest }} />
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
