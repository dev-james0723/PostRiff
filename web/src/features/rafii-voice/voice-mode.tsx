'use client';

/**
 * Voice Mode inside the Rafii panel (spec §6.2, §27, §28). Start/end, mute, "stop talking", the live transcript, what
 * Rafii is working on, reconnect and a plain privacy note. Everything shown comes from the voice session's real
 * events. Reduced motion keeps the state text and drops the level animation. The call keeps running while the person
 * moves between pages; the panel frame can change without ending it.
 */
import { useCallback, useEffect, useRef } from 'react';
import { usePathname } from 'next/navigation';
import { IconMicrophone, IconMicrophoneOff, IconPhoneOff, IconPlayerStop, IconRefresh } from '@tabler/icons-react';
import { Button } from '@/components/ui/button';
import { useMotionPreference } from '@/lib/rafii/motion';
import manifestJson from '@/lib/site-agent/route-manifest.json';
import { matchRoute, type RouteManifest } from '@/lib/site-agent/routes';
import type { SiteAgentPageContext } from '@/lib/site-agent/types';
import type { AgentTurnResponse } from '@/lib/agent-runtime/types';
import { useAgent } from '@/lib/agent-runtime/use-agent';
import { useVoice, voiceSession, type VoiceSnapshot } from '@/lib/agent-runtime/voice-session';
import { cn } from '@/lib/utils';

const MANIFEST = manifestJson as RouteManifest;
const LOCALES: { id: string; label: string }[] = [
  { id: 'auto', label: 'Match my language' },
  { id: 'en', label: 'English' },
  { id: 'yue', label: '廣東話' },
  { id: 'cmn', label: '普通话' }
];

function statusLine(s: VoiceSnapshot): string {
  if (s.state === 'connecting') return 'Connecting…';
  if (s.state === 'reconnecting') return 'Connection lost';
  if (s.state === 'ending') return 'Ending…';
  if (s.state === 'ended') return 'Voice ended. The conversation continues here.';
  if (s.state === 'error') return s.error?.message ?? 'Voice Mode stopped.';
  if (s.state !== 'live') return '';
  const running = s.delegations.filter((d) => d.status === 'running' || d.status === 'collecting').length;
  if (s.speaker === 'rafii') return running ? 'Rafii is speaking · still working on your request' : 'Rafii is speaking';
  if (s.micMuted) return running ? 'Microphone off · working on your request' : 'Microphone off';
  if (running) return 'Listening · working on your request';
  return 'Listening';
}

export function VoiceMode({
  conversationId,
  pageContext,
  onConversation,
  onAnswer,
  timeZone,
  model
}: {
  conversationId: string | null;
  pageContext: () => SiteAgentPageContext;
  onConversation: (conversationId: string) => void;
  onAnswer: (response: AgentTurnResponse) => void;
  timeZone?: string;
  model?: string;
}) {
  const { api, workspaceId, status } = useAgent();
  const { reduced } = useMotionPreference();
  const state = useVoice((s) => s.state);
  const snapshot = useVoice((s) => s);
  const locale = useRef('auto');
  const pathname = usePathname() ?? '/app';
  const available = Boolean(status?.voice.available);
  const active = state === 'connecting' || state === 'live' || state === 'reconnecting' || state === 'ending';

  // Moving between pages keeps the call; GPT-Live is told quietly where the person is now.
  useEffect(() => {
    voiceSession.pageChanged(matchRoute(MANIFEST, pathname)?.route.title ?? null);
  }, [pathname]);
  useEffect(() => {
    if (!active) voiceSession.setConversation(conversationId);
  }, [conversationId, active]);

  const start = useCallback(() => {
    if (!workspaceId) return;
    void voiceSession.start({ api, workspaceId, conversationId, locale: locale.current, timeZone, model, pageContext, onConversation, onAnswer });
  }, [api, workspaceId, conversationId, timeZone, model, pageContext, onConversation, onAnswer]);

  const line = statusLine(snapshot);
  const running = snapshot.delegations.filter((d) => d.status === 'running' || d.status === 'collecting');
  const transcript = snapshot.transcript.slice(-6);

  if (!active && state !== 'error' && state !== 'ended') {
    return (
      <div className='flex flex-wrap items-center gap-2 px-4 pb-2' data-rafii-voice='idle'>
        <Button type='button' variant='glass' size='sm' className='min-h-9 gap-1.5' onClick={start} disabled={!available} aria-describedby='rafii-voice-note'>
          <IconMicrophone className='size-4' aria-hidden />
          Talk to Rafii
        </Button>
        <label className='text-muted-foreground flex items-center gap-1 text-xs'>
          <span className='sr-only'>Voice language</span>
          <select
            className='rafii-focus bg-transparent text-xs'
            defaultValue='auto'
            onChange={(event) => (locale.current = event.target.value)}
            aria-label='Voice language'
          >
            {LOCALES.map((item) => (
              <option key={item.id} value={item.id}>
                {item.label}
              </option>
            ))}
          </select>
        </label>
        <p id='rafii-voice-note' className='text-muted-foreground w-full text-[11px] leading-snug'>
          {available
            ? 'Voice uses OpenAI GPT-Live. Rafii keeps a text transcript, not the audio, and asks before changing anything.'
            : (status?.voice.blocker ?? 'Voice Mode isn’t available here. You can keep typing.')}
        </p>
      </div>
    );
  }

  return (
    <section className='mx-4 mb-2 flex flex-col gap-2 rounded-[var(--rafii-radius-control)] border border-[color-mix(in_oklch,var(--foreground)_10%,transparent)] p-2.5' aria-label='Voice Mode' data-rafii-voice={state}>
      <div className='flex items-center gap-2'>
        <span
          aria-hidden
          className={cn('inline-block size-2.5 shrink-0 rounded-full', state === 'live' ? 'bg-emerald-500' : state === 'error' || state === 'reconnecting' ? 'bg-amber-500' : 'bg-muted-foreground/50')}
        />
        <p className='min-w-0 flex-1 truncate text-sm font-medium' role='status' aria-live='polite' data-rafii-voice-status>
          {line}
        </p>
        {!reduced && state === 'live' && (
          <span aria-hidden className='bg-foreground/15 relative h-1.5 w-14 overflow-hidden rounded-full' data-rafii-voice-level>
            <span className='bg-foreground/60 absolute inset-y-0 left-0 rounded-full transition-[width] duration-100' style={{ width: `${Math.round(snapshot.level * 100)}%` }} />
          </span>
        )}
      </div>
      {state === 'live' && (
        <div className='flex flex-wrap items-center gap-1.5'>
          <Button
            type='button'
            variant='quiet'
            size='sm'
            className='min-h-9 gap-1'
            aria-pressed={snapshot.micMuted}
            onClick={() => voiceSession.setMicMuted(!snapshot.micMuted)}
          >
            {snapshot.micMuted ? <IconMicrophoneOff className='size-4' aria-hidden /> : <IconMicrophone className='size-4' aria-hidden />}
            {snapshot.micMuted ? 'Unmute' : 'Mute'}
          </Button>
          <Button type='button' variant='quiet' size='sm' className='min-h-9 gap-1' onClick={() => voiceSession.stopSpeaking()} disabled={snapshot.speaker !== 'rafii'}>
            <IconPlayerStop className='size-4' aria-hidden />
            Stop talking
          </Button>
          <Button type='button' variant='quiet' size='sm' className='min-h-9 gap-1' onClick={() => void voiceSession.end()}>
            <IconPhoneOff className='size-4' aria-hidden />
            End voice
          </Button>
        </div>
      )}
      {(state === 'reconnecting' || state === 'error') && (
        <div className='flex flex-wrap items-center gap-1.5' role='alert'>
          <Button type='button' variant='glass' size='sm' className='min-h-9 gap-1' onClick={() => void (state === 'reconnecting' ? voiceSession.reconnect() : start())} disabled={!available}>
            <IconRefresh className='size-4' aria-hidden />
            {state === 'reconnecting' ? 'Reconnect' : 'Try voice again'}
          </Button>
          <span className='text-muted-foreground text-xs'>Typing still works; nothing waiting for approval was lost.</span>
        </div>
      )}
      {state === 'ended' && (
        <Button type='button' variant='quiet' size='sm' className='min-h-9 self-start' onClick={() => voiceSession.reset()}>
          Close
        </Button>
      )}
      {running.length > 0 && (
        <ul className='flex flex-col gap-1' aria-label='What Rafii is working on'>
          {running.map((d) => (
            <li key={d.id} className='text-muted-foreground truncate text-xs' data-rafii-voice-delegation={d.status}>
              Working on: {d.request || 'listening for your request…'}
            </li>
          ))}
        </ul>
      )}
      {transcript.length > 0 && (
        <details className='text-xs' open={state === 'live'}>
          <summary className='rafii-focus text-muted-foreground cursor-pointer'>Transcript</summary>
          <ol className='mt-1 flex flex-col gap-0.5' aria-label='Voice transcript' data-rafii-voice-transcript>
            {transcript.map((l) => (
              <li key={l.id} data-role={l.role}>
                <span className='font-medium'>{l.role === 'user' ? 'You' : 'Rafii'}: </span>
                {l.text}
              </li>
            ))}
          </ol>
        </details>
      )}
    </section>
  );
}
