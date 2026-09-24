'use client';

import { useEffect, useRef, useState } from 'react';
import { useTheme } from 'next-themes';
import { useReducedMotion } from 'motion/react';
import { cn } from '@/lib/utils';

/**
 * The Welcome dialog's illustration: an eight-second loop rendered with HyperFrames
 * (source in `motion/onboarding-welcome/`) showing the product's loop in neutral shapes:
 * a sentence becomes one draft per channel, two are approved, they land in the week.
 * It carries no numbers, names or accounts, so it never reads as the person's data.
 *
 * Light and dark are separate renders chosen from the resolved theme. With reduced motion
 * (or when the connection asks to save data) only the still poster shows. If a file fails
 * to load the illustration steps aside instead of leaving a broken box.
 */
export function WelcomeClip({ className }: { className?: string }) {
  const { resolvedTheme } = useTheme();
  const reduce = useReducedMotion();
  const [failed, setFailed] = useState(false);
  const [saveData, setSaveData] = useState(false);
  const video = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    const connection = (navigator as Navigator & { connection?: { saveData?: boolean } }).connection;
    setSaveData(Boolean(connection?.saveData));
  }, []);

  const variant = resolvedTheme === 'dark' ? 'dark' : 'light';
  const base = `/onboarding/welcome-loop-${variant}`;
  const still = reduce || saveData;

  useEffect(() => {
    // A theme switch swaps the sources; the element has to reload them.
    video.current?.load();
  }, [variant]);

  if (failed) return null;

  return (
    <div
      aria-hidden
      className={cn('rafii-quiet relative aspect-[16/10] w-full max-w-full overflow-hidden rounded-[var(--rafii-radius-card)]', className)}
    >
      {still ? (
        // eslint-disable-next-line @next/next/no-img-element -- a static poster from /public; no optimisation needed
        <img src={`${base}.jpg`} alt='' className='size-full object-cover' onError={() => setFailed(true)} />
      ) : (
        <video
          ref={video}
          aria-label='Illustration: a sentence becomes one draft per channel, two are approved and land in the week'
          className='size-full object-cover'
          autoPlay
          muted
          loop
          playsInline
          preload='auto'
          poster={`${base}.jpg`}
          onError={() => setFailed(true)}
        >
          <source src={`${base}.webm`} type='video/webm' />
          <source src={`${base}.mp4`} type='video/mp4' onError={() => setFailed(true)} />
        </video>
      )}
    </div>
  );
}
