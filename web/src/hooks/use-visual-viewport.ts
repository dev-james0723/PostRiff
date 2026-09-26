'use client';

import { useEffect, useState } from 'react';

export interface VisualViewportBox {
  /** The visible height: shrinks when the on-screen keyboard opens. */
  height: number;
  /** How far the visible area is scrolled down inside the layout viewport (iOS scrolls it for the keyboard). */
  offsetTop: number;
}

interface ViewportSource {
  height: number;
  offsetTop: number;
  addEventListener(event: 'resize' | 'scroll', listener: () => void): void;
  removeEventListener(event: 'resize' | 'scroll', listener: () => void): void;
}

export function readViewport(
  source: Pick<ViewportSource, 'height' | 'offsetTop'> | null | undefined,
  fallbackHeight: number
): VisualViewportBox {
  return source
    ? { height: source.height, offsetTop: source.offsetTop }
    : { height: fallbackHeight, offsetTop: 0 };
}

/**
 * The visual viewport, so sheets and the `@` list stay above the mobile keyboard (chat-context SPEC §4.9).
 * SSR-safe: renders with `{ height: 0, offsetTop: 0 }` on the server and the real values after mount.
 */
export function useVisualViewport(): VisualViewportBox {
  const [box, setBox] = useState<VisualViewportBox>({ height: 0, offsetTop: 0 });
  useEffect(() => {
    const source = window.visualViewport as ViewportSource | null;
    const update = () => {
      const next = readViewport(source, window.innerHeight);
      setBox((current) =>
        current.height === next.height && current.offsetTop === next.offsetTop ? current : next
      );
    };
    update();
    const target = source ?? window;
    target.addEventListener('resize', update);
    target.addEventListener('scroll', update);
    return () => {
      target.removeEventListener('resize', update);
      target.removeEventListener('scroll', update);
    };
  }, []);
  return box;
}
