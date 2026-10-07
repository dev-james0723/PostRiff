import { create } from 'zustand';

export interface RafiiTrack {
  kind?: 'video' | 'audio';
  workspaceId: string;
  conversationId?: string | null;
  assetId: string;
  title: string;
  url: string;
  startAt?: number;
}

interface NowPlayingState {
  track: RafiiTrack | null;
  playing: boolean;
  seconds: number;
  duration: number | null;
  expanded: boolean;
  open: (track: RafiiTrack) => void;
  setPlaying: (playing: boolean) => void;
  setPosition: (seconds: number, duration?: number | null) => void;
  setExpanded: (expanded: boolean) => void;
  close: () => void;
}

export const useNowPlaying = create<NowPlayingState>((set) => ({
  track: null, playing: false, seconds: 0, duration: null, expanded: false,
  open: (track) => set({ track, playing: true, seconds: track.startAt ?? 0, duration: null }),
  setPlaying: (playing) => set({ playing }),
  setPosition: (seconds, duration) => set((state) => ({ seconds, duration: duration === undefined ? state.duration : duration })),
  setExpanded: (expanded) => set({ expanded }),
  close: () => set({ track: null, playing: false, seconds: 0, duration: null, expanded: false })
}));

export function formatMediaTime(seconds: number): string {
  const total = Math.max(0, Math.floor(Number.isFinite(seconds) ? seconds : 0));
  const minutes = Math.floor(total / 60);
  const prefix = total >= 3600 ? `${Math.floor(minutes / 60)}:` : '';
  return `${prefix}${String(minutes % 60).padStart(prefix ? 2 : 1, '0')}:${String(total % 60).padStart(2, '0')}`;
}

export function attachMediaSession(media: MediaSession | undefined, video: HTMLVideoElement, title: string): () => void {
  if (!media) return () => {};
  try { media.metadata = new MediaMetadata({ title, artist: 'Rafii' }); } catch { /* unsupported metadata */ }
  const handlers: Partial<Record<MediaSessionAction, (details: MediaSessionActionDetails) => void>> = {
    play: () => { void video.play(); },
    pause: () => video.pause(),
    seekbackward: (event) => { video.currentTime = Math.max(0, video.currentTime - (event.seekOffset ?? 10)); },
    seekforward: (event) => { video.currentTime = Math.min(video.duration || Infinity, video.currentTime + (event.seekOffset ?? 10)); },
    seekto: (event) => { if (event.seekTime !== undefined && Number.isFinite(event.seekTime)) video.currentTime = event.seekTime; }
  };
  for (const [action, handler] of Object.entries(handlers)) {
    try { media.setActionHandler(action as MediaSessionAction, handler); } catch { /* action unsupported */ }
  }
  return () => {
    for (const action of Object.keys(handlers)) {
      try { media.setActionHandler(action as MediaSessionAction, null); } catch { /* unsupported */ }
    }
    try { media.metadata = null; } catch { /* unsupported */ }
  };
}

export function updateMediaPosition(media: MediaSession | undefined, video: HTMLVideoElement): void {
  if (!media?.setPositionState || !Number.isFinite(video.duration) || video.duration <= 0 || !Number.isFinite(video.currentTime)) return;
  try { media.setPositionState({ duration: video.duration, position: Math.min(video.duration, Math.max(0, video.currentTime)), playbackRate: video.playbackRate }); }
  catch { /* browser does not support position state */ }
}
