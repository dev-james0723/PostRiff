'use client';

/**
 * While Voice Mode is on and the panel is closed, the person still sees that the microphone is live, with one tap to
 * open Rafii or end voice (spec §27: "Page navigation must not tear down the voice session"; privacy: a live mic is
 * always visible). Mounted once in the app shell, beside the panel's hotkeys.
 */
import { useEffect } from 'react';
import { IconMicrophone, IconPhoneOff } from '@tabler/icons-react';
import { panelStore, usePanel } from '@/features/site-agent/store';
import { useVoice, voiceSession } from '@/lib/agent-runtime/voice-session';
import { useWorkspaceApi } from '@/lib/workspace/provider';

const inCall = () => ['connecting', 'live', 'reconnecting'].includes(voiceSession.get().state);

export function VoiceIndicator() {
  const { workspaceId } = useWorkspaceApi();
  // A call belongs to one workspace: switching workspace ends it (spoken requests would otherwise act on the old one).
  useEffect(() => {
    const callWorkspace = voiceSession.get().workspaceId;
    if (inCall() && workspaceId && callWorkspace && callWorkspace !== workspaceId) void voiceSession.end();
  }, [workspaceId]);
  // Mounted once in the signed-in app shell: leaving it (signing out, leaving the app) ends the call and releases the microphone.
  useEffect(
    () => () => {
      if (inCall()) void voiceSession.end();
    },
    []
  );
  const state = useVoice((s) => s.state);
  const speaker = useVoice((s) => s.speaker);
  const open = usePanel((s) => s.open || s.above);
  if (open || (state !== 'live' && state !== 'reconnecting')) return null;
  const label = state === 'reconnecting' ? 'Voice connection lost' : speaker === 'rafii' ? 'Rafii is speaking' : 'Voice is on';
  return (
    <div
      role='region'
      aria-label='Rafii Voice Mode'
      className='rafii-glass fixed right-4 bottom-[calc(1rem+env(safe-area-inset-bottom))] z-40 flex items-center gap-1 rounded-full p-1 pl-3 text-sm shadow-lg'
      data-rafii-voice-indicator={state}
    >
      <IconMicrophone className='size-4' aria-hidden />
      <button type='button' className='rafii-focus rounded-full px-2 py-1.5 font-medium' onClick={() => panelStore.setOpen(true)}>
        {label} · Open Rafii
      </button>
      <button type='button' className='rafii-focus text-muted-foreground hover:text-foreground inline-flex size-8 items-center justify-center rounded-full' aria-label='End voice' onClick={() => void voiceSession.end()}>
        <IconPhoneOff className='size-4' aria-hidden />
      </button>
    </div>
  );
}
