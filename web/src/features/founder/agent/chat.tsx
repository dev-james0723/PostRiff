'use client';

/**
 * The Founder Rafii conversation (CONTRACTS §4, §6): one thread per data mode and environment, sent with the page's
 * context (section, selected entity, chart, period, filters, incident) to `POST /agent/turns` under an
 * `Idempotency-Key`. A running turn is polled through `GET /agent/runs/{id}` and can be cancelled. Every state is
 * the real one: "working" only while a request is in flight, receipts only when the server returned them, and a
 * failed turn is resent with its own key so the server sees one request. Voice (`voice.tsx`) opens under the header: a
 * GPT-Live call whose every spoken question is a founder turn in this same conversation, or the blocker codes that keep
 * it off here.
 */
import { usePathname } from 'next/navigation';
import { useCallback, useEffect, useId, useMemo, useRef, useState, type FormEvent, type KeyboardEvent } from 'react';
import { IconMicrophone } from '@tabler/icons-react';
import { ThinkingShimmer } from '@/components/agents/loading-states/thinking-shimmer';
import { Icons } from '@/components/icons';
import { Button } from '@/components/ui/button';
import { FOUNDER_SECTIONS, isFounderSectionId } from '@/config/founder-nav';
import { useFounderSession } from '@/features/founder/shell/founder-session';
import { RafiiAvatar } from '@/features/site-agent/rafii-avatar';
import { randomKey } from '@/lib/founder/api';
import { describeFounderError, isFounderApiError } from '@/lib/founder/errors';
import { currentFounderPageContext, sectionFromPathname, useRegisteredFounderContext, type FounderPageRegistration } from '@/lib/founder/page-context';
import type { FounderAgentRun, FounderAgentTurnResponse } from '@/lib/founder/types';
import { createImeGuard } from '@/lib/ime';
import { useMotionPreference } from '@/lib/rafii/motion';
import { cn } from '@/lib/utils';
import { FounderAnswer } from './answer';
import { suggestedPrompts } from './prompts';
import { conversationKey, founderPanelStore, useFounderPanel, useFounderThread, type FounderThreadItem } from './store';
import { FounderVoice } from './voice';

const TERMINAL = new Set(['completed', 'failed', 'cancelled', 'canceled', 'blocked', 'error', 'done']);
const POLL_MS = 1500;
const POLL_LIMIT = 80;
const NOT_CONNECTED = 'Founder Rafii is not connected in this environment yet: no founder workspace is set. Create one in Settings → Contact & calls → Founder workspace.';

function wait(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** Only the fields an Ask request set override the page's registered context. */
function compact(context: FounderPageRegistration): Partial<FounderPageRegistration> {
  return Object.fromEntries(Object.entries(context).filter(([, value]) => value !== undefined && value !== null && !(typeof value === 'object' && Object.keys(value).length === 0)));
}

/** A run's final shape folded into the turn response the thread keeps. */
function merge(initial: FounderAgentTurnResponse, run: FounderAgentRun): FounderAgentTurnResponse {
  return { ...initial, status: run.status, result: run.result ?? initial.result, founder: run.founder ?? initial.founder, messageId: run.messageId ?? initial.messageId };
}

export function FounderChat({ onClose, onNavigate, autoFocus = true }: { onClose: () => void; onNavigate?: () => void; autoFocus?: boolean }) {
  const { api, mode, environment, sessionStatus, sessionError, retrySession } = useFounderSession();
  const sessionReady = sessionStatus === 'ready' && Boolean(environment);
  const sessionStatusId = useId();
  const pathname = usePathname() ?? '/founder';
  const { reduced } = useMotionPreference();
  const key = conversationKey(mode, environment);
  const keyRef = useRef(key);
  keyRef.current = key;

  useEffect(() => {
    founderPanelStore.load(key);
  }, [key]);
  const conversationId = useFounderPanel((s) => s.conversations[key] ?? null);
  const busy = useFounderPanel((s) => Boolean(s.busy[key]));
  const thread = useFounderThread(key);
  const registered = useRegisteredFounderContext();

  const [text, setText] = useState('');
  const [menuOpen, setMenuOpen] = useState(false);
  const [contextOpen, setContextOpen] = useState(false);
  const [voiceOpen, setVoiceOpen] = useState(false);
  const input = useRef<HTMLTextAreaElement>(null);
  const end = useRef<HTMLDivElement>(null);
  const activeRun = useRef<string | null>(null);
  const ime = useRef(createImeGuard());
  /** Context an "Ask Rafii about this" press handed over; it rides on the next turn, then clears. */
  const askContext = useRef<FounderPageRegistration | null>(null);

  useEffect(() => {
    const prefill = founderPanelStore.takePrefill();
    if (prefill) {
      setText(prefill.text);
      askContext.current = prefill.context ?? null;
    }
    if (autoFocus) input.current?.focus({ preventScroll: true });
  }, [autoFocus]);
  // A later "Ask Rafii about this" while the panel is already open replaces the draft, like the site agent's prefill.
  const prefill = useFounderPanel((s) => s.prefill);
  useEffect(() => {
    if (!prefill) return;
    const taken = founderPanelStore.takePrefill();
    if (!taken) return;
    setText(taken.text);
    askContext.current = taken.context ?? null;
    input.current?.focus({ preventScroll: true });
  }, [prefill]);

  useEffect(() => {
    end.current?.scrollIntoView({ block: 'end', behavior: reduced ? 'auto' : 'smooth' });
  }, [thread.length, busy, reduced]);

  const sectionId = registered?.section ?? sectionFromPathname(pathname);
  const sectionTitle = isFounderSectionId(sectionId) ? FOUNDER_SECTIONS[sectionId].title : 'a page Rafii does not know';
  const contextLabel = `${sectionTitle} · ${mode === 'demo' ? 'Demo data' : 'Live'}${environment ? ` · ${environment}` : ''}`;
  const suggestions = useMemo(() => suggestedPrompts(sectionId), [sectionId]);
  const lastAssistant = thread.findLast((item) => item.role === 'assistant')?.id;

  const waitForRun = useCallback(
    async (initial: FounderAgentTurnResponse, runId: string): Promise<FounderAgentTurnResponse> => {
      activeRun.current = runId;
      let latest = initial;
      try {
        for (let attempt = 0; attempt < POLL_LIMIT; attempt += 1) {
          if (activeRun.current !== runId) return latest;
          await wait(POLL_MS);
          const run = (await api.agentRun(runId)).data;
          latest = merge(initial, run);
          if (TERMINAL.has(run.status)) return latest;
        }
        return { ...latest, status: 'timeout' };
      } finally {
        if (activeRun.current === runId) activeRun.current = null;
      }
    },
    [api]
  );

  const send = useCallback(
    async (raw: string, retryKey?: string) => {
      const message = raw.trim();
      const k = keyRef.current;
      if (!sessionReady || !message || founderPanelStore.get().busy[k]) return;
      const idempotencyKey = retryKey ?? randomKey();
      const assistantId = `a-${idempotencyKey}`;
      if (!retryKey) {
        founderPanelStore.append(k, { id: `u-${idempotencyKey}`, role: 'user', text: message, at: Date.now() });
        founderPanelStore.append(k, { id: assistantId, role: 'assistant', text: '', at: Date.now(), pending: true });
      } else {
        founderPanelStore.update(k, assistantId, { pending: true, error: null });
      }
      setText('');
      founderPanelStore.setBusy(k, true);
      try {
        const asked = askContext.current;
        askContext.current = null;
        const pageContext = { ...currentFounderPageContext(pathname, mode, environment), ...(asked ? compact(asked) : {}) };
        const response = (
          await api.agentTurn({
            message,
            idempotencyKey,
            conversationId: founderPanelStore.get().conversations[k] ?? null,
            mode,
            modality: 'text',
            pageContext,
            timeZone: Intl.DateTimeFormat().resolvedOptions().timeZone
          })
        ).data;
        if (response.conversationId) founderPanelStore.setConversation(k, response.conversationId);
        founderPanelStore.update(k, assistantId, { runId: response.runId });
        const final = !TERMINAL.has(response.status) && response.runId ? await waitForRun(response, response.runId) : response;
        founderPanelStore.update(k, assistantId, { pending: false, response: final, text: final.result?.answerText ?? '', runId: final.runId });
      } catch (error) {
        const notConnected = isFounderApiError(error) && error.status === 409 && error.blocker === 'ops_workspace_not_configured';
        founderPanelStore.update(k, assistantId, { pending: false, error: notConnected ? NOT_CONNECTED : describeFounderError(error), retryKey: notConnected ? null : idempotencyKey, retryText: message });
      } finally {
        founderPanelStore.setBusy(k, false);
      }
    },
    [api, environment, mode, pathname, sessionReady, waitForRun]
  );

  const stop = useCallback(async () => {
    const runId = activeRun.current;
    if (!runId) return;
    activeRun.current = null;
    try {
      await api.cancelRun(runId);
    } catch {
      /* the poll has already stopped; the server keeps its own state */
    }
  }, [api]);

  const startOver = useCallback(() => {
    founderPanelStore.setConversation(keyRef.current, null);
    setMenuOpen(false);
    input.current?.focus();
  }, []);

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    void send(text);
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.defaultPrevented || event.nativeEvent.defaultPrevented) return;
    if (event.key === 'Enter' && !event.shiftKey && !ime.current.composing(event)) {
      event.preventDefault();
      void send(text);
    }
  }

  const empty = thread.length === 0;

  return (
    <div className='rafii-chat @container flex h-full min-h-0 flex-col' data-rafii-mode='chat'>
      <div className='rafii-chat-header flex shrink-0 items-center gap-2.5 px-4 pt-3 pb-2'>
        <Button type='button' variant='quiet' size='icon-control' className='shrink-0' aria-label='Close Rafii' onClick={onClose}>
          <Icons.close className='size-5' />
        </Button>
        <RafiiAvatar size={36} thinking={busy} />
        <div className='flex min-w-0 flex-1 flex-col'>
          <h2 className='text-base leading-tight font-semibold'>Rafii · Founder</h2>
          <button type='button' className='rafii-focus text-muted-foreground w-fit max-w-full truncate rounded text-left text-xs' title={contextLabel} aria-expanded={contextOpen} onClick={() => setContextOpen((open) => !open)}>
            Viewing {contextLabel} <Icons.chevronDown aria-hidden className='inline size-3' />
          </button>
        </div>
        <Button type='button' variant='quiet' size='icon-control' aria-label='Voice' title='Voice (GPT-Live)' aria-expanded={voiceOpen} aria-controls={voiceOpen ? 'founder-voice' : undefined} onClick={() => setVoiceOpen((open) => !open)} className={cn(voiceOpen && 'rafii-glass-selected')}>
          <IconMicrophone className='size-5' />
        </Button>
        <Button type='button' variant='quiet' size='icon-control' aria-label='More Rafii options' aria-expanded={menuOpen} onClick={() => setMenuOpen((open) => !open)}>
          <Icons.dots className='size-5' />
        </Button>
      </div>
      {contextOpen && (
        <section className='rafii-glass mx-4 mb-2 shrink-0 rounded-2xl p-4 text-sm' aria-label='Current page context'>
          <p className='font-medium'>Rafii is looking at {contextLabel}</p>
          <ul className='text-muted-foreground mt-2 flex flex-col gap-0.5 text-xs'>
            {registered?.selectedEntity && <li>Selected {registered.selectedEntity.type}: {registered.selectedEntity.id}</li>}
            {registered?.chart && <li>Chart: {registered.chart.chartId} (view {registered.chart.viewVersion}{registered.chart.queryReceiptId ? `, receipt ${registered.chart.queryReceiptId.slice(0, 8)}…` : ''})</li>}
            {registered?.period && <li>Period: {registered.period}</li>}
            {registered?.incidentId && <li>Incident: {registered.incidentId}</li>}
            {registered?.filters && Object.keys(registered.filters).length > 0 && <li>Filters: {Object.entries(registered.filters).map(([name, value]) => `${name}=${Array.isArray(value) ? value.join(',') : String(value)}`).join(' · ')}</li>}
          </ul>
          <p className='text-muted-foreground mt-2'>Page headings, the selected record’s id and the chart in view are shared as context. Typed fields are not read. Answers cite receipts; totals are never computed by the model.</p>
        </section>
      )}
      {menuOpen && (
        <div className='rafii-glass mx-4 mb-2 flex shrink-0 flex-col gap-1 rounded-2xl p-3' role='group' aria-label='Rafii options'>
          <Button type='button' variant='quiet' className='min-h-11 justify-start' onClick={startOver} disabled={busy}>
            <Icons.add className='size-4' /> New conversation
          </Button>
          <p className='text-muted-foreground px-3 py-1 text-xs'>{conversationId ? `Conversation ${conversationId.slice(0, 8)}… in ${mode === 'demo' ? 'Demo' : 'Live'} · ${environment ?? ''}` : 'No conversation yet in this mode.'}</p>
          <p className='text-muted-foreground px-3 py-1 text-xs'>Voice answers through the same founder tools as typing. Phone calls follow the contact policy in Settings and stay off while live delivery is off.</p>
        </div>
      )}
      <FounderVoice conversationKey={key} conversationId={conversationId} visible={voiceOpen} />
      <div className='rafii-chat-log min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 pb-3' role='log' aria-live='polite' aria-relevant='additions' aria-label='Conversation with Rafii'>
        {empty ? (
          <div className='flex flex-col items-start gap-5 pt-7'>
            <RafiiAvatar size={88} variant='full' className='self-center' />
            <div>
              <h3 className='text-2xl font-semibold tracking-tight'>What would help you decide?</h3>
              <p className='text-muted-foreground mt-2 text-sm leading-relaxed'>Ask about {sectionTitle.toLowerCase()}, a chart, an incident or a customer. Facts come with receipts; drafts and reminders wait for your confirmation.</p>
              {conversationId && <p className='text-muted-foreground mt-2 text-xs'>Continuing an earlier conversation in this mode; its earlier turns stay on the server.</p>}
            </div>
            <div className='flex flex-col items-stretch gap-2 self-stretch' role='group' aria-label='Suggested questions'>
              {suggestions.map((item) => (
                <Button key={item} type='button' variant='glass' className='h-auto min-h-14 justify-between rounded-2xl px-4 py-3 text-left text-sm whitespace-normal' onClick={() => void send(item)} disabled={!sessionReady || busy}>
                  <span>{item}</span>
                  <Icons.arrowRight aria-hidden className='size-4 shrink-0' />
                </Button>
              ))}
            </div>
          </div>
        ) : (
          <ol className='flex flex-col gap-4 pt-2'>
            {thread.map((item) => (
              <ThreadItem key={item.id} item={item} latest={item.id === lastAssistant} busy={!sessionReady || busy} onAsk={(value) => void send(value)} onRetry={(value, retryKey) => void send(value, retryKey)} onNavigate={onNavigate} onStop={() => void stop()} />
            ))}
          </ol>
        )}
        <div ref={end} />
      </div>
      <form onSubmit={onSubmit} className='rafii-chat-form relative shrink-0 px-3 pt-2 pb-[calc(0.75rem+env(safe-area-inset-bottom))]'>
        {!sessionReady && <div id={sessionStatusId} role={sessionStatus === 'loading' ? 'status' : 'alert'} className='text-muted-foreground mb-2 px-2 text-xs'>
          <p>{sessionStatus === 'loading' ? 'Connecting to Founder Rafii…' : sessionError ? describeFounderError(sessionError) : 'The Founder session environment is unavailable.'}</p>
          {sessionStatus !== 'loading' && <Button type='button' variant='quiet' size='sm' onClick={retrySession}>Retry connection</Button>}
        </div>}
        <div className='rafii-composer flex items-end gap-2 rounded-[var(--rafii-radius-composer)] p-2'>
          <textarea
            ref={input}
            value={text}
            onChange={(event) => setText(event.target.value)}
            onKeyDown={onKeyDown}
            onCompositionStart={() => ime.current.onCompositionStart()}
            onCompositionEnd={() => ime.current.onCompositionEnd()}
            rows={2}
            maxLength={4000}
            aria-label='Ask Rafii'
            aria-describedby={!sessionReady ? sessionStatusId : undefined}
            placeholder={`Ask about ${sectionTitle.toLowerCase()}, or anything in the business…`}
            className='placeholder:text-muted-foreground max-h-40 min-h-14 flex-1 resize-none bg-transparent px-2 py-3 text-base leading-snug outline-none field-sizing-content'
          />
          <Button type='submit' variant='action' size='icon-control' aria-label='Send' disabled={!sessionReady || !text.trim() || busy}>
            <Icons.send className='size-4' />
          </Button>
        </div>
      </form>
    </div>
  );
}

function ThreadItem({ item, latest, busy, onAsk, onRetry, onNavigate, onStop }: { item: FounderThreadItem; latest: boolean; busy: boolean; onAsk: (text: string) => void; onRetry: (text: string, key: string) => void; onNavigate?: () => void; onStop: () => void }) {
  if (item.role === 'user') {
    return (
      <li className='flex justify-end'>
        <p className='rafii-glass max-w-[85%] rounded-2xl px-3 py-2 text-sm break-words whitespace-pre-wrap'>{item.text}</p>
      </li>
    );
  }
  if (item.pending) {
    return (
      <li className='flex gap-2.5'>
        <RafiiAvatar size={24} thinking />
        <div className='flex min-w-0 flex-1 flex-col gap-1.5' role='status'>
          <span className='text-muted-foreground text-xs'>
            <ThinkingShimmer>{item.runId ? 'Checking the records' : 'Reading your question'}</ThinkingShimmer>
          </span>
          {item.runId && (
            <Button type='button' variant='quiet' size='xs' className='self-start' onClick={onStop}>
              Stop
            </Button>
          )}
        </div>
      </li>
    );
  }
  if (item.error) {
    return (
      <li role='alert' className='flex gap-2.5'>
        <RafiiAvatar size={24} className='mt-0.5' />
        <div className='flex min-w-0 flex-1 flex-col gap-2'>
          <p className='text-destructive text-sm'>{item.error}</p>
          {item.retryKey && item.retryText && (
            <Button type='button' variant='glass' size='sm' className='self-start' onClick={() => onRetry(item.retryText as string, item.retryKey as string)} disabled={busy}>
              Try again
            </Button>
          )}
        </div>
      </li>
    );
  }
  return (
    <li className='flex gap-2.5'>
      <RafiiAvatar size={24} className='mt-0.5' />
      <article className={cn('min-w-0 flex-1')} aria-label="Rafii's answer">
        {item.response ? <FounderAnswer response={item.response} actions={{ onAsk, onNavigate, latest }} /> : <p className='text-muted-foreground text-sm'>{item.text}</p>}
      </article>
    </li>
  );
}
