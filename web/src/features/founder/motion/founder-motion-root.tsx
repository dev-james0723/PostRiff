'use client';

import { createContext, useCallback, useContext, useEffect, useId, useMemo, useRef, useState, type ReactNode } from 'react';
import { LayoutGroup, MotionConfig } from 'motion/react';
import { useMotionPreference } from '@/lib/rafii/motion';
import './founder-motion.css';

const FounderActivity = createContext<{ count: number; publish: (id: string, busy: boolean) => void } | null>(null);

/** One app-aware motion policy, also inherited by Founder portal surfaces. */
export function FounderMotionRoot({ children }: { children: ReactNode }) {
  const { reduced } = useMotionPreference();
  const id = useId();
  const [active, setActive] = useState<Set<string>>(() => new Set());
  const publish = useCallback((key: string, busy: boolean) => setActive(previous => {
    if (previous.has(key) === busy) return previous;
    const next = new Set(previous);
    if (busy) next.add(key); else next.delete(key);
    return next;
  }), []);
  const activity = useMemo(() => ({ count: active.size, publish }), [active.size, publish]);
  return (
    <FounderActivity.Provider value={activity}>
    <MotionConfig reducedMotion={reduced ? 'always' : 'never'} transition={reduced ? { duration: 0 } : { duration: 0.2 }}>
      <LayoutGroup id={`founder-motion-${id}`}>{children}</LayoutGroup>
    </MotionConfig>
    </FounderActivity.Provider>
  );
}

/** Decorative busy motion runs only while its real status is visible. */
export function useVisibleFounderMotion<T extends HTMLElement>() {
  const { reduced } = useMotionPreference();
  const ref = useRef<T>(null);
  const [visible, setVisible] = useState(false);
  const [inView, setInView] = useState(false);
  useEffect(() => {
    const visibility = () => setVisible(document.visibilityState === 'visible');
    visibility();
    document.addEventListener('visibilitychange', visibility);
    const element = ref.current;
    const observer = typeof IntersectionObserver === 'undefined' ? null : new IntersectionObserver(([entry]) => setInView(Boolean(entry?.isIntersecting)));
    if (element && observer) observer.observe(element);
    else setInView(true);
    return () => {
      document.removeEventListener('visibilitychange', visibility);
      observer?.disconnect();
    };
  }, []);
  return { ref, enabled: !reduced && visible && inView };
}

/** Reports real local action state without starting requests or changing action permissions. */
export function useFounderActionBusy(busy: boolean) {
  const id = useId();
  const publish = useContext(FounderActivity)?.publish;
  useEffect(() => {
    publish?.(id, busy);
    return () => publish?.(id, false);
  }, [id, busy, publish]);
}

export function useFounderPendingActions() {
  return useContext(FounderActivity)?.count ?? 0;
}