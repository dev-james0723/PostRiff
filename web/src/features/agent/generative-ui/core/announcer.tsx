'use client';
/**
 * One concise, deduplicated status announcer per generated message (spec §5: loading/success/error announcements are
 * concise, deduplicated and contain no raw DSL).
 *
 * The chat log is itself an `aria-live` region, so the generated subtree is marked `aria-busy` while it streams and
 * every announcement goes through this single polite `role="status"` region instead. The same text is not repeated
 * within 4 seconds; a changed text replaces the previous one (cleared first so screen readers read it again).
 */
import { type JSX, useCallback, useEffect, useMemo, useRef, useState } from 'react';

const REPEAT_MS = 4000;
const SET_DELAY_MS = 30;

export interface Announcer {
  announce(message: string): void;
}

export function useAnnouncer(): { announcer: Announcer; region: JSX.Element } {
  const [text, setText] = useState('');
  const last = useRef<{ message: string; at: number }>({ message: '', at: 0 });
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );
  const announce = useCallback((message: string) => {
    const clean = message.replace(/\s+/g, ' ').trim().slice(0, 200);
    if (!clean) return;
    const now = Date.now();
    if (last.current.message === clean && now - last.current.at < REPEAT_MS) return;
    last.current = { message: clean, at: now };
    setText('');
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setText(clean), SET_DELAY_MS);
  }, []);
  const announcer = useMemo(() => ({ announce }), [announce]);
  const region = (
    <div role="status" aria-live="polite" aria-atomic="true" className="sr-only" data-rafii-genui-status="">
      {text}
    </div>
  );
  return { announcer, region };
}
