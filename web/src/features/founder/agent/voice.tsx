'use client';

/**
 * Voice in the founder panel (CONTRACTS §8.E, PRD §6.5). The customer Voice Mode controller (`voiceSession`) and its
 * avatar run the call; this component supplies the founder host (`voice-api.ts`) and the honest states around it:
 *
 * - availability comes from `GET /agent/voice/status`: when voice cannot start, the button stays disabled and every
 *   blocker is named with its fixed code (flag off, no founder workspace, no GPT-Live route, …);
 * - a call belongs to one data mode and environment: switching either ends it, and so does closing the panel (the
 *   founder shell has no floating voice indicator, so a live microphone is only ever on while the panel shows it);
 * - each spoken request is an ordinary founder turn (founder tools only, receipts, drafts that wait), and its answer
 *   joins the panel's thread with its receipts. Nothing here computes or invents an answer.
 */
import { useQuery } from '@tanstack/react-query';
import { usePathname } from 'next/navigation';
import { useCallback, useEffect, useMemo, useRef } from 'react';
import { IconMicrophone, IconMicrophoneOff, IconPhoneOff, IconPlayerStop, IconRefresh } from '@tabler/icons-react';
import { Button } from '@/components/ui/button';
import { RafiiLiveAvatar } from '@/features/rafii-voice/rafii-live-avatar';
import { resolveRafiiAvatarMode } from '@/features/rafii-voice/avatar-state';
import { useFounderSession } from '@/features/founder/shell/founder-session';
import { ApiError } from '@/lib/api/client';
import type { AgentApi } from '@/lib/agent-runtime/client';
import type { AgentTurnResponse } from '@/lib/agent-runtime/types';
import { useVoice, voiceSession, type VoiceSnapshot } from '@/lib/agent-runtime/voice-session';
import { founderFetch } from '@/lib/founder/api';
import { isFounderApiError } from '@/lib/founder/errors';
import { currentFounderPageContext } from '@/lib/founder/page-context';
import type { Envelope, FounderAgentTurnResponse } from '@/lib/founder/types';
import type { SiteAgentPageContext } from '@/lib/site-agent/types';
import { useMotionPreference } from '@/lib/rafii/motion';
import { cn } from '@/lib/utils';
import { founderPanelStore } from './store';
import { createFounderVoiceApi, founderVoiceKey, voiceBlockerCopy, voiceBlockers, FounderVoiceRequestError, VOICE_BLOCKER_COPY, type FounderVoiceStatus } from './voice-api';

const EMPTY_SITE_CONTEXT = {} as SiteAgentPageContext;
const ACTIVE = new Set(['connecting', 'live', 'reconnecting', 'ending']);

/** The controller tells refusals from unknown outcomes by `ApiError`: founder errors keep their status, code and fixed copy. */
function asApiError(error: unknown): unknown {
  if (isFounderApiError(error) || error instanceof FounderVoiceRequestError) {
    const code = isFounderApiError(error) ? (error.blocker ?? error.code) : error.code;
    return new ApiError(error.message, error.status, code);
  }
  return error;
}

function statusLine(s: VoiceSnapshot): string {
  if (s.state === 'connecting') return 'Connecting…';
  if (s.state === 'reconnecting') return 'Connection lost';
  if (s.state === 'ending') return 'Ending…';
  if (s.state === 'ended') return 'Voice ended. The conversation continues here.';
  if (s.state === 'error') return s.error?.code && VOICE_BLOCKER_COPY[s.error.code] ? voiceBlockerCopy(s.error.code) : (s.error?.message ?? 'Voice stopped.');
  if (s.state !== 'live') return '';
  if (s.endingAfterReply) return 'Ending the call…';
  const running = s.delegations.some((d) => d.status === 'running' || d.status === 'collecting');
  if (s.speaker === 'rafii') return running ? 'Rafii is speaking · still checking' : 'Rafii is speaking';
  if (s.micMuted) return running ? 'Microphone off · checking your question' : 'Microphone off';
  return running ? 'Listening · checking your question' : 'Listening';
}

export function useFounderVoiceStatus(enabled: boolean) {
  const { mode, environment, sessionStatus } = useFounderSession();
  return useQuery({
    queryKey: ['founder', mode, environment ?? 'unknown', 'voice-status'],
    enabled: enabled && sessionStatus === 'ready',
    staleTime: 60_000,
    retry: false,
    queryFn: async ({ signal }) => (await founderFetch<Envelope<FounderVoiceStatus>>(`/agent/voice/status?mode=${mode}`, { signal })).data
  });
}

/**
 * The voice strip under the panel header: a disabled "Talk to Rafii" with the blocker codes when voice cannot start,
 * the call's controls, transcript and running questions while it can.
 */
export function FounderVoice({ conversationKey, conversationId, visible }: { conversationKey: string; conversationId: string | null; visible: boolean }) {
  const { mode, environment } = useFounderSession();
  const { reduced } = useMotionPreference();
  const pathname = usePathname() ?? '/founder';
  const path = useRef(pathname);
  path.current = pathname;
  const shared = useVoice((s) => s);
  // The customer app's Voice Mode shares this controller: a call it started is not this panel's to show or end.
  const foreign = Boolean(shared.workspaceId && !shared.workspaceId.startsWith('founder:'));
  const foreignActive = foreign && ACTIVE.has(shared.state);
  const snapshot = foreign ? { ...shared, state: 'idle' as const } : shared;
  const state = snapshot.state;
  const active = ACTIVE.has(state);
  const status = useFounderVoiceStatus(visible || state !== 'idle');
  const callKey = founderVoiceKey(mode, environment);
  const threadKey = useRef(conversationKey);
  threadKey.current = conversationKey;

  const api = useMemo(
    () => createFounderVoiceApi({ fetch: founderFetch, mode, pageContext: () => currentFounderPageContext(path.current, mode, environment), toError: asApiError }),
    [mode, environment]
  );

  // A call belongs to one data mode and environment: a switch ends it rather than answering from the other.
  useEffect(() => {
    const current = voiceSession.get();
    if (ACTIVE.has(current.state) && current.workspaceId && current.workspaceId.startsWith('founder:') && current.workspaceId !== callKey) void voiceSession.end();
  }, [callKey]);
  // No floating indicator in the founder shell: closing the panel ends the call and releases the microphone.
  useEffect(
    () => () => {
      const current = voiceSession.get();
      if (!current.workspaceId?.startsWith('founder:')) return;
      if (ACTIVE.has(current.state)) void voiceSession.end();
      else if (current.state === 'ended' || current.state === 'error') voiceSession.reset();
    },
    []
  );
  // A refused start (flag switched off, workspace removed) is re-read so the strip shows the current blockers.
  const refetchStatus = status.refetch;
  useEffect(() => {
    if (state === 'error') void refetchStatus();
  }, [state, refetchStatus]);
  // The panel's conversation is the call's: a new conversation during the call takes the next spoken questions.
  useEffect(() => {
    if (active) voiceSession.followConversation(conversationId);
  }, [conversationId, active]);

  const onConversation = useCallback((id: string) => founderPanelStore.setConversation(threadKey.current, id), []);
  const onAnswer = useCallback((response: AgentTurnResponse) => {
    const key = threadKey.current;
    const named = (response as { delegationId?: unknown }).delegationId;
    const asked = voiceSession.get().delegations.find((d) => d.id === named)?.request?.trim();
    const at = Date.now();
    const id = response.runId ?? `${at}`;
    if (asked) founderPanelStore.append(key, { id: `vu-${id}`, role: 'user', text: `Spoken: ${asked}`, at });
    founderPanelStore.append(key, { id: `va-${id}`, role: 'assistant', text: response.result?.answerText ?? '', at, response: response as unknown as FounderAgentTurnResponse, runId: response.runId });
  }, []);

  const start = useCallback(() => {
    void voiceSession.start({
      api: api as AgentApi,
      workspaceId: callKey,
      conversationId,
      timeZone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      pageContext: () => EMPTY_SITE_CONTEXT,
      onConversation,
      onAnswer
    });
  }, [api, callKey, conversationId, onConversation, onAnswer]);

  if (!visible && !active && state !== 'error' && state !== 'ended') return null;

  const blockers = status.isPending ? [] : voiceBlockers(status.isError ? null : status.data);
  const available = !status.isPending && blockers.length === 0 && !foreignActive;
  const running = snapshot.delegations.filter((d) => d.status === 'running' || d.status === 'collecting');
  const transcript = snapshot.transcript.slice(-6);
  const mine = !snapshot.workspaceId || snapshot.workspaceId === callKey;

  if (!active && state !== 'error' && state !== 'ended') {
    return (
      <section id='founder-voice' className='mx-4 mb-2 flex shrink-0 flex-col gap-2 rounded-[var(--rafii-radius-control)] border border-[color-mix(in_oklch,var(--foreground)_10%,transparent)] p-2.5' aria-label='Voice' data-founder-voice='idle'>
        <div className='flex flex-wrap items-center gap-2'>
          <Button type='button' variant='glass' size='sm' className='min-h-9 gap-1.5' onClick={start} disabled={!available} aria-describedby='founder-voice-note'>
            <IconMicrophone className='size-4' aria-hidden />
            Talk to Rafii
          </Button>
          <span className='text-muted-foreground text-xs'>{mode === 'demo' ? 'Demo data' : 'Live data'}</span>
        </div>
        <div id='founder-voice-note' className='text-muted-foreground text-[11px] leading-snug'>
          {status.isPending ? (
            <p>Checking whether voice can start here…</p>
          ) : foreignActive && blockers.length === 0 ? (
            <p>A Rafii voice call from the app is still on. End it there to talk here.</p>
          ) : available ? (
            <p>Voice uses OpenAI GPT-Live through Rafii’s server. Each question you ask is a founder turn with receipts; a text transcript is kept, not the audio. Founder usage settles to the founder workspace.</p>
          ) : (
            <>
              <p className='text-foreground font-medium'>Voice is unavailable here:</p>
              <ul className='mt-1 flex flex-col gap-0.5'>
                {blockers.map((code) => (
                  <li key={code}>
                    <code className='font-mono'>{code}</code> — {voiceBlockerCopy(code)}
                  </li>
                ))}
              </ul>
              <p className='mt-1'>Typing still works.</p>
            </>
          )}
        </div>
      </section>
    );
  }

  const muted = snapshot.micMuted;
  const avatarMode = resolveRafiiAvatarMode({ state, speaker: snapshot.speaker, outputMuted: snapshot.outputMuted, hasRunningDelegation: running.length > 0 });
  return (
    <section id='founder-voice' className='mx-4 mb-2 flex shrink-0 flex-col gap-2 overflow-hidden rounded-[var(--rafii-radius-control)] border border-[color-mix(in_oklch,var(--foreground)_10%,transparent)] p-2.5' aria-label='Voice' data-founder-voice={state}>
      {active && mine && <RafiiLiveAvatar mode={avatarMode} level={snapshot.level} outputMuted={snapshot.outputMuted} reducedMotion={reduced} />}
      <div className='flex min-w-0 items-center gap-2'>
        <span aria-hidden className={cn('inline-block size-2.5 shrink-0 rounded-full', muted && active ? 'bg-destructive' : state === 'live' ? 'bg-emerald-500' : state === 'error' || state === 'reconnecting' ? 'bg-amber-500' : 'bg-muted-foreground/50')} />
        <p className={cn('min-w-0 flex-1 text-sm font-medium', state === 'error' ? 'break-words' : 'truncate')} role='status' aria-live='polite'>
          {statusLine(snapshot)}
        </p>
      </div>
      {state === 'error' && snapshot.error?.code && (
        <p className='text-muted-foreground text-xs'>
          Code <code className='font-mono'>{snapshot.error.code}</code>
        </p>
      )}
      {state === 'connecting' && (
        <Button type='button' variant='quiet' size='sm' className='min-h-9 gap-1 self-start' onClick={() => void voiceSession.end()}>
          <IconPhoneOff className='size-4' aria-hidden />
          Cancel
        </Button>
      )}
      {(state === 'live' || state === 'reconnecting') && (
        <div className='flex flex-wrap items-center gap-1.5'>
          <Button type='button' variant={muted ? 'destructive' : 'quiet'} size='sm' className='min-h-9 gap-1' aria-pressed={muted} onClick={() => voiceSession.setMicMuted(!muted)}>
            {muted ? <IconMicrophoneOff className='size-4' aria-hidden /> : <IconMicrophone className='size-4' aria-hidden />}
            {muted ? 'Unmute' : 'Mute'}
          </Button>
          {state === 'live' && (
            <Button type='button' variant='quiet' size='sm' className='min-h-9 gap-1' onClick={() => voiceSession.stopSpeaking()}>
              <IconPlayerStop className='size-4' aria-hidden />
              Stop talking
            </Button>
          )}
          <Button type='button' variant='quiet' size='sm' className='min-h-9 gap-1' onClick={() => void voiceSession.end()}>
            <IconPhoneOff className='size-4' aria-hidden />
            End voice
          </Button>
        </div>
      )}
      {(state === 'reconnecting' || state === 'error') && (
        <div className='flex flex-wrap items-center gap-1.5' role='alert'>
          <Button type='button' variant='glass' size='sm' className='min-h-9 gap-1' onClick={() => void (state === 'reconnecting' ? voiceSession.reconnect() : start())} disabled={state === 'error' && !available}>
            <IconRefresh className='size-4' aria-hidden />
            {state === 'reconnecting' ? 'Reconnect' : 'Try voice again'}
          </Button>
          <span className='text-muted-foreground text-xs'>Typing still works. Answers already given stay in the conversation.</span>
        </div>
      )}
      {(state === 'ended' || state === 'error') && (
        <Button type='button' variant='quiet' size='sm' className='min-h-9 self-start' onClick={() => voiceSession.reset()}>
          Close
        </Button>
      )}
      {running.length > 0 && (
        <ul className='flex flex-col gap-1' aria-label='What Rafii is checking'>
          {running.map((d) => (
            <li key={d.id} className='text-muted-foreground truncate text-xs'>
              Checking: {d.request || 'listening for your question…'}
            </li>
          ))}
        </ul>
      )}
      {transcript.length > 0 && (
        <details className='text-xs' open={state === 'live'}>
          <summary className='rafii-focus text-muted-foreground cursor-pointer'>Transcript</summary>
          <ol className='mt-1 flex flex-col gap-0.5 break-words' aria-label='Voice transcript'>
            {transcript.map((line) => (
              <li key={line.id}>
                <span className='font-medium'>{line.role === 'user' ? 'You' : 'Rafii'}: </span>
                {line.text}
                {line.stopped && <span className='text-muted-foreground'> (stopped)</span>}
              </li>
            ))}
          </ol>
        </details>
      )}
    </section>
  );
}
