'use client';

/**
 * Voice Mode inside the Rafii panel (spec §6.2, §27, §28). Start/end, mute, "stop talking", the live transcript, what
 * Rafii is working on, reconnect and a plain privacy note. Everything shown comes from the voice session's real
 * events. Reduced motion keeps the state text and drops the level animation. The call keeps running while the person
 * moves between pages; the panel frame can change without ending it.
 *
 * How Rafii talks comes from the person's style (`useAgentStyle`): the call's language defaults to it and the voice is
 * sent with it. The first call offers the presets before it starts. While muted, the Mute button and the status dot
 * turn red, so a closed microphone is never missed.
 */
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { usePathname } from 'next/navigation';
import { IconKeyboard, IconMicrophone, IconMicrophoneOff, IconPhoneOff, IconPlayerStop, IconRefresh, IconVolume } from '@tabler/icons-react';
import { Button } from '@/components/ui/button';
import { useMotionPreference } from '@/lib/rafii/motion';
import manifestJson from '@/lib/site-agent/route-manifest.json';
import { matchRoute, type RouteManifest } from '@/lib/site-agent/routes';
import type { SiteAgentPageContext } from '@/lib/site-agent/types';
import { registerPanelActions } from '@/lib/agent-runtime/panel-actions';
import { LANGUAGE_LABELS, LANGUAGES, type Language } from '@/lib/agent-runtime/style';
import type { AgentTurnResponse } from '@/lib/agent-runtime/types';
import { useAgent } from '@/lib/agent-runtime/use-agent';
import { useAgentStyle } from '@/lib/agent-runtime/use-agent-style';
import { useVoice, voiceSession, type VoiceSnapshot } from '@/lib/agent-runtime/voice-session';
import { cn } from '@/lib/utils';
import { resolveRafiiAvatarMode } from './avatar-state';
import { RafiiLiveAvatar } from './rafii-live-avatar';
import { StyleButton, StyleSheet } from './style-sheet';

const MANIFEST = manifestJson as RouteManifest;

function statusLine(s: VoiceSnapshot): string {
  if (s.state === 'connecting') return 'Connecting…';
  if (s.state === 'reconnecting') return 'Connection lost';
  if (s.state === 'ending') return 'Ending…';
  if (s.state === 'ended') return 'Voice ended. The conversation continues here.';
  if (s.state === 'error') return s.error?.message ?? 'Voice Mode stopped.';
  if (s.state !== 'live') return '';
  if (s.endingAfterReply) return 'Ending the call…';
  const running = s.delegations.filter((d) => d.status === 'running' || d.status === 'collecting').length;
  if (s.speaker === 'rafii') return running ? 'Rafii is speaking · still working on your request' : 'Rafii is speaking';
  if (s.micMuted) return running ? 'Microphone off · working on your request' : 'Microphone off';
  if (running) return 'Listening · working on your request';
  return 'Listening';
}

function dotColor(s: VoiceSnapshot): string {
  if (s.micMuted && (s.state === 'live' || s.state === 'reconnecting')) return 'bg-destructive';
  if (s.state === 'live') return 'bg-emerald-500';
  if (s.state === 'error' || s.state === 'reconnecting') return 'bg-amber-500';
  return 'bg-muted-foreground/50';
}

export function VoiceMode({
  conversationId,
  pageContext,
  onConversation,
  onAnswer,
  timeZone,
  model,
  immersive = false,
  onKeyboard,
  contextLabel
}: {
  conversationId: string | null;
  pageContext: () => SiteAgentPageContext;
  onConversation: (conversationId: string) => void;
  onAnswer: (response: AgentTurnResponse) => void;
  timeZone?: string;
  model?: string;
  immersive?: boolean;
  onKeyboard?: () => void;
  contextLabel?: string;
}) {
  const { api, workspaceId, status } = useAgent();
  const { reduced } = useMotionPreference();
  const { style, loading: styleLoading } = useAgentStyle();
  const state = useVoice((s) => s.state);
  const snapshot = useVoice((s) => s);
  // The language follows the person's style until they pick one here for this call.
  const [picked, setPicked] = useState<Language | null>(null);
  const [firstRun, setFirstRun] = useState(false);
  const pathname = usePathname() ?? '/app';
  const available = Boolean(status?.voice.available);
  const active = state === 'connecting' || state === 'live' || state === 'reconnecting' || state === 'ending';
  const locale = picked ?? style.language;

  // Moving between pages keeps the call; GPT-Live is told quietly where the person is now.
  useEffect(() => {
    voiceSession.pageChanged(matchRoute(MANIFEST, pathname)?.route.title ?? null);
  }, [pathname]);
  // The panel's conversation is the call's: a new or different conversation during the call takes the next requests.
  useEffect(() => {
    if (active) voiceSession.followConversation(conversationId);
    else voiceSession.setConversation(conversationId);
  }, [conversationId, active]);

  // Read when the call starts, so a call started from the first-run picker uses what was just chosen. Until the style
  // has loaded, the server applies the saved one (an explicit value here would override it).
  const settings = useRef<{ locale?: string; voice?: string }>({});
  useLayoutEffect(() => {
    settings.current = styleLoading ? { locale: picked ?? undefined } : { locale, voice: style.voice };
  });

  const start = useCallback(() => {
    if (!workspaceId) return;
    const { locale: callLocale, voice } = settings.current;
    void voiceSession.start({ api, workspaceId, conversationId, locale: callLocale, voice, timeZone, model, pageContext, onConversation, onAnswer });
  }, [api, workspaceId, conversationId, timeZone, model, pageContext, onConversation, onAnswer]);

  // The first call offers the presets first; picking one saves it, then the call starts (a user gesture either way).
  const talk = useCallback(() => {
    if (styleLoading) return;
    if (!style.chosen) setFirstRun(true);
    else start();
  }, [start, style.chosen, styleLoading]);

  // `/voice` and other panel actions start the call the same way the button does.
  const talkRef = useRef(talk);
  useLayoutEffect(() => {
    talkRef.current = talk;
  });
  useEffect(() => (available && workspaceId ? registerPanelActions({ startVoice: () => talkRef.current() }) : undefined), [available, workspaceId]);

  const line = statusLine(snapshot);
  const running = snapshot.delegations.filter((d) => d.status === 'running' || d.status === 'collecting');
  const transcript = snapshot.transcript.slice(-6);
  const avatarMode = resolveRafiiAvatarMode({
    state: snapshot.state,
    speaker: snapshot.speaker,
    outputMuted: snapshot.outputMuted,
    hasRunningDelegation: running.length > 0
  });
  const sheet = firstRun ? (
    <StyleSheet
      firstRun
      open
      onOpenChange={(open) => {
        if (!open) setFirstRun(false);
      }}
      onChosen={() => {
        setFirstRun(false);
        start();
      }}
    />
  ) : null;

  if (immersive) {
    const stateLabel = snapshot.state === 'live'
      ? snapshot.speaker === 'rafii' ? 'Rafii is speaking' : running.length ? 'Rafii is thinking' : snapshot.micMuted ? 'Microphone off' : snapshot.speaker === 'user' ? 'Listening to you' : 'Listening'
      : statusLine(snapshot) || 'Ready to connect';
    return (
      <section className='rafii-live flex min-h-0 flex-1 flex-col px-5 pb-[calc(1rem+env(safe-area-inset-bottom))]' aria-label='Rafii Live' data-rafii-voice={snapshot.state} data-rafii-live-state={snapshot.state}>
        <p className='text-muted-foreground mt-2 text-center text-xs'>Current context: {contextLabel ?? 'this workspace'}</p>
        <div className='flex min-h-0 flex-1 flex-col items-center justify-center gap-4 py-5'>
          <div className='rafii-live-stage w-full max-w-[18rem]' data-rafii-avatar-slot>
            <RafiiLiveAvatar mode={avatarMode} level={snapshot.level} outputMuted={snapshot.outputMuted} reducedMotion={reduced} />
          </div>
          <p role='status' aria-live='polite' className='text-center text-2xl font-medium' data-rafii-voice-status>{stateLabel}</p>
          {active && <p className='text-muted-foreground text-center text-sm'>{snapshot.state === 'live' ? 'Speak naturally. Rafii keeps your place in this conversation.' : line}</p>}
          {!active && snapshot.state !== 'error' && <Button type='button' variant='action' className='min-h-14 rounded-full px-7 text-base' disabled={!available || styleLoading} onClick={talk}><IconMicrophone className='size-5' /> Start live conversation</Button>}
          {!available && <p className='text-muted-foreground max-w-sm text-center text-sm'>{status?.voice.blocker ?? 'Live voice is unavailable here. You can keep typing.'}</p>}
          {(snapshot.state === 'error' || snapshot.state === 'reconnecting') && <div className='flex flex-col items-center gap-2' role='alert'><p className='text-sm'>{snapshot.error?.message ?? 'Connection interrupted.'}</p><Button type='button' variant='glass' className='min-h-11' disabled={!available} onClick={() => void (snapshot.state === 'reconnecting' ? voiceSession.reconnect() : start())}><IconRefresh className='size-4' /> Reconnect</Button></div>}
        </div>
        {transcript.length > 0 && <div className='rafii-glass max-h-[25dvh] shrink-0 overflow-y-auto rounded-2xl p-4' aria-label='Live transcript'><p className='text-muted-foreground mb-2 text-xs'>Transcript</p><ol className='flex flex-col gap-2 text-sm' data-rafii-voice-transcript>{transcript.map((entry) => <li key={entry.id} data-role={entry.role} data-stopped={entry.stopped ? '' : undefined}><span className='font-semibold'>{entry.role === 'user' ? 'You' : 'Rafii'}: </span>{entry.text}{entry.stopped ? ' (stopped)' : ''}</li>)}</ol></div>}
        {running.length > 0 && <p className='text-muted-foreground mt-2 text-center text-xs'>{running.length} request{running.length === 1 ? '' : 's'} in progress</p>}
        <div className='mt-4 flex shrink-0 items-center justify-around gap-3' role='group' aria-label='Live controls'>
          <Button type='button' variant='glass' size='icon-control' className='size-12 rounded-full' aria-label='Stop Rafii speaking' disabled={snapshot.state !== 'live'} onClick={() => voiceSession.stopSpeaking()}><IconVolume className='size-5' /></Button>
          <Button type='button' variant='destructive' size='icon-control' className='size-14 rounded-full' aria-label='End live conversation' disabled={!active || snapshot.state === 'ending'} onClick={() => void voiceSession.end()}><IconPhoneOff className='size-6' /></Button>
          <Button type='button' variant='glass' size='icon-control' className='size-12 rounded-full' aria-label='Return to keyboard' onClick={onKeyboard}><IconKeyboard className='size-5' /></Button>
        </div>
        <details className='text-muted-foreground mt-3 text-center text-xs'><summary className='rafii-focus inline-flex min-h-11 cursor-pointer items-center rounded-lg px-3'>Live options</summary><div className='flex flex-wrap items-center justify-center gap-2 py-2'><Button type='button' variant={snapshot.micMuted ? 'destructive' : 'quiet'} className='min-h-11' aria-pressed={snapshot.micMuted} data-rafii-voice-mute={snapshot.micMuted ? 'on' : 'off'} disabled={snapshot.state !== 'live'} onClick={() => voiceSession.setMicMuted(!snapshot.micMuted)}>{snapshot.micMuted ? <IconMicrophoneOff className='size-4' /> : <IconMicrophone className='size-4' />}{snapshot.micMuted ? 'Unmute' : 'Mute'}</Button><StyleButton /></div></details>
        <p className='text-muted-foreground text-center text-xs'>Live uses GPT Live. A text transcript is kept; audio is not saved here.</p>
        {sheet}
      </section>
    );
  }

  if (!active && state !== 'error' && state !== 'ended') {
    return (
      <div className='flex flex-wrap items-center gap-2 px-4 pb-2' data-rafii-voice='idle'>
        <Button type='button' variant='glass' size='sm' className='min-h-9 gap-1.5' onClick={talk} disabled={!available} aria-describedby='rafii-voice-note'>
          <IconMicrophone className='size-4' aria-hidden />
          Talk to Rafii
        </Button>
        <label className='text-muted-foreground flex items-center gap-1 text-xs'>
          <span className='sr-only'>Voice language</span>
          <select className='rafii-focus bg-transparent text-xs' value={locale} onChange={(event) => setPicked(event.target.value as Language)} aria-label='Voice language'>
            {LANGUAGES.map((id) => (
              <option key={id} value={id}>
                {LANGUAGE_LABELS[id]}
              </option>
            ))}
          </select>
        </label>
        <StyleButton />
        <p id='rafii-voice-note' className='text-muted-foreground w-full text-[11px] leading-snug'>
          {available
            ? 'Voice uses OpenAI GPT-Live. Rafii keeps a text transcript, not the audio, and asks before changing anything.'
            : (status?.voice.blocker ?? 'Voice Mode isn’t available here. You can keep typing.')}
        </p>
        {sheet}
      </div>
    );
  }

  const muted = snapshot.micMuted;
  return (
    <section className='mx-4 mb-2 flex min-w-0 flex-col gap-2 overflow-hidden rounded-[var(--rafii-radius-control)] border border-[color-mix(in_oklch,var(--foreground)_10%,transparent)] p-2.5' aria-label='Voice Mode' data-rafii-voice={state}>
      {active && (
        <RafiiLiveAvatar mode={avatarMode} level={snapshot.level} outputMuted={snapshot.outputMuted} reducedMotion={reduced} />
      )}
      <div className='flex min-w-0 items-center gap-2'>
        <span aria-hidden className={cn('inline-block size-2.5 shrink-0 rounded-full', dotColor(snapshot))} data-rafii-voice-dot={muted ? 'muted' : state} />
        <p className='min-w-0 flex-1 truncate text-sm font-medium' role='status' aria-live='polite' data-rafii-voice-status>
          {line}
        </p>
        {!reduced && state === 'live' && (
          <span aria-hidden className='bg-foreground/15 relative h-1.5 w-14 overflow-hidden rounded-full' data-rafii-voice-level>
            <span className='bg-foreground/60 absolute inset-y-0 left-0 rounded-full transition-[width] duration-100' style={{ width: `${Math.round(snapshot.level * 100)}%` }} />
          </span>
        )}
      </div>
      {state === 'connecting' && (
        <Button type='button' variant='quiet' size='sm' className='min-h-9 gap-1 self-start' onClick={() => void voiceSession.end()}>
          <IconPhoneOff className='size-4' aria-hidden />
          Cancel
        </Button>
      )}
      {(state === 'live' || state === 'reconnecting') && (
        <div className='flex flex-wrap items-center gap-1.5'>
          <Button
            type='button'
            // A solid red fill keeps muted visible while its paired foreground keeps the label readable.
            variant={muted ? 'destructive' : 'quiet'}
            size='sm'
            className={cn('min-h-9 gap-1', muted && 'bg-destructive text-destructive-foreground hover:bg-destructive dark:bg-destructive dark:hover:bg-destructive border-destructive rounded-[var(--rafii-radius-control)]')}
            aria-pressed={muted}
            data-rafii-voice-mute={muted ? 'on' : 'off'}
            onClick={() => voiceSession.setMicMuted(!muted)}
          >
            {muted ? <IconMicrophoneOff className='size-4' aria-hidden /> : <IconMicrophone className='size-4' aria-hidden />}
            {muted ? 'Unmute' : 'Mute'}
          </Button>
          {state === 'live' && (
            // Always available during the call (it only yields Rafii's turn), so focus never lands on a disabled control.
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
      {state === 'live' && snapshot.error && (
        <p className='text-muted-foreground text-xs' role='status' data-rafii-voice-error>
          The voice service reported a problem: {snapshot.error.message}
        </p>
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
          <ol className='mt-1 flex max-h-28 flex-col gap-0.5 overflow-y-auto overscroll-contain' aria-label='Voice transcript' data-rafii-voice-transcript>
            {transcript.map((l) => (
              <li key={l.id} data-role={l.role} data-stopped={l.stopped ? '' : undefined}>
                <span className='font-medium'>{l.role === 'user' ? 'You' : 'Rafii'}: </span>
                {l.text}
                {l.stopped && <span className='text-muted-foreground'> (stopped)</span>}
              </li>
            ))}
          </ol>
        </details>
      )}
      {sheet}
    </section>
  );
}
