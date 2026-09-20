'use client';

import { createContext, useContext } from 'react';

/**
 * What the reader is looking at in a post with several photos or a video: the slide in view and whether video
 * plays. Held by `PostPreview`, so swiping on the phone and the pager under it stay in step.
 */
export interface Playback {
  index: number;
  setIndex: (index: number) => void;
  /** Slides in the template's carousel; 0 when it draws none. */
  slides: number;
  setSlides: (slides: number) => void;
  playing: boolean;
  setPlaying: (playing: boolean) => void;
  /** Videos mounted on the phone, so the play control shows only when there is one. */
  videos: number;
  addVideo: () => () => void;
}

export const PlaybackContext = createContext<Playback | null>(null);

export function usePlayback() {
  return useContext(PlaybackContext);
}

/** Whether the media around it is the slide in view; true outside a carousel. */
export const SlideContext = createContext(true);

/** The slide in view for a carousel of `count`, kept in range when the post has fewer items than before. */
export function useSlideIndex(count: number) {
  const index = useContext(PlaybackContext)?.index ?? 0;
  return count > 0 ? Math.min(Math.max(index, 0), count - 1) : 0;
}
