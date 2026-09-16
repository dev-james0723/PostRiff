'use client';

import { useEffect, useState } from 'react';
import { cn } from '@/lib/utils';

/** Per-word offset inside one arriving chunk (`--stream-gap`). */
const STREAM_GAP_MS = 60;
/** transitions-polish: keep a stagger's total under ~300ms, so long chunks never read as lag. */
const MAX_CHUNK_STAGGER_MS = 300;

/**
 * transitions.dev streaming text for live output: every word that arrives resolves
 * through a soft cross-blur, one gap after the previous word of the same chunk,
 * while words already on screen stay put. It renders only the text it is given;
 * nothing is simulated. Whitespace and line breaks are preserved.
 */
function StreamingText({ text, className }: { text: string; className?: string }) {
  const tokens = text.split(/(\s+)/);
  const count = tokens.length;
  // The words resolved so far, and where the latest chunk started.
  const [chunk, setChunk] = useState({ start: 0, end: 0 });

  useEffect(() => {
    if (count === chunk.end) return;
    if (count < chunk.end) {
      setChunk({ start: count, end: count });
      return;
    }
    // One frame so the new words paint at their starting style before they resolve.
    const frame = requestAnimationFrame(() => setChunk({ start: chunk.end, end: count }));
    return () => cancelAnimationFrame(frame);
  }, [count, chunk.end]);

  return (
    <span className={cn('whitespace-pre-wrap', className)}>
      {tokens.map((token, index) => {
        if (token === '' || /^\s+$/.test(token)) return token;
        const inChunk = index >= chunk.start && index < chunk.end;
        const delay = Math.min(((index - chunk.start) / 2) * STREAM_GAP_MS, MAX_CHUNK_STAGGER_MS);
        return (
          <span
            // A streamed word keeps its slot as the text grows, so its position is its identity.
            key={index}
            className={cn('t-stream-w', index < chunk.end && 'is-in')}
            style={inChunk ? { transitionDelay: `${delay}ms` } : undefined}
          >
            {token}
          </span>
        );
      })}
    </span>
  );
}

export { StreamingText };
