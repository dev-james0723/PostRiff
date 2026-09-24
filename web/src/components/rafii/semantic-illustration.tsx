'use client';

import { useId, useMemo, useRef, type CSSProperties } from 'react';
import { Icons } from '@/components/icons';
import { LEGACY_FALLBACK, TAXONOMY, artworkFor, artworkMarkup, prepareArtwork, type ArtworkSize } from '@/lib/content-library';
import { cn } from '@/lib/utils';
import { useArtworkPlaying } from './illustrations/artwork-motion';

/**
 * Decorative loops (DNA v8 §14.5, §18.2): glyph breathing 4.8s, paper 6s, accent opacity 4.8s; at most
 * 1.2px of travel and 0.3° of rotation. Loops run only while the wrapper says `data-art-playing`, and the
 * shared `.rafii-decorative-motion` rules in styles/rafii.css cancel them under reduced motion. React 19
 * hoists this `<style href precedence>` into <head> once, however many illustrations are mounted.
 */
const MOTION_CSS = [
  '.rafii-art .rafii-art-motif,.rafii-art .rafii-art-accent,.rafii-art .glyph-motion{transform-box:fill-box;transform-origin:center;animation-timing-function:ease-in-out;animation-iteration-count:infinite;animation-play-state:paused;animation-delay:var(--art-delay,0s)}',
  '.rafii-art .rafii-art-motif{animation-name:rafii-paper-breathe;animation-duration:6s}',
  '.rafii-art .rafii-art-accent{animation-name:rafii-accent-breathe;animation-duration:4.8s}',
  '.rafii-art .glyph-motion{animation-name:rafii-glyph-breathe;animation-duration:4.8s}',
  '.rafii-art[data-art-playing] .rafii-art-motif,.rafii-art[data-art-playing] .rafii-art-accent,.rafii-art[data-art-playing] .glyph-motion{animation-play-state:running}',
  '@keyframes rafii-glyph-breathe{0%,100%{transform:translateY(0);opacity:1}50%{transform:translateY(-.9px);opacity:.7}}',
  '@keyframes rafii-paper-breathe{0%,100%{transform:translateY(0) rotate(0deg)}50%{transform:translateY(-1.2px) rotate(.3deg)}}',
  '@keyframes rafii-accent-breathe{0%,100%{opacity:1}50%{opacity:.65}}'
].join('\n');

export interface SemanticIllustrationProps {
  /** Taxonomy item id. An id the library does not carry renders the legacy fallback (large) or a neutral mark (compact). */
  id: string;
  size?: ArtworkSize;
  /** Accessible name; defaults to the asset's recorded alt text. */
  alt?: string;
  /** Hide from assistive technology when the title is read right next to it (cards, rows, chips). */
  decorative?: boolean;
  /** False when the person paused artwork. Offscreen, background-tab and reduced-motion pauses are automatic. */
  motion?: boolean;
  className?: string;
  /** Staggers the loop start so neighbours breathe out of phase; defaults to the item's position in the taxonomy. */
  delayIndex?: number;
}

/**
 * One taxonomy item's semantic artwork at either scale (DNA v8 §14.1): the large 8:5 illustration
 * explains, the compact 1:1 glyph helps scanning. Renders the archive SVG inline on a paper field with
 * per-instance ids (§14.4), so the same asset can appear in a card, a route and the footer at once.
 */
export function SemanticIllustration({ id, size = 'large', alt, decorative = false, motion = true, className, delayIndex }: SemanticIllustrationProps) {
  const uid = useId();
  const ref = useRef<HTMLSpanElement>(null);
  const meta = artworkFor(id);
  const legacy = !meta;
  const record = meta ? meta[size] : size === 'large' ? LEGACY_FALLBACK : null;
  const source = artworkMarkup(id, size);
  const html = useMemo(() => (source ? prepareArtwork(source, { prefix: `art-${uid}`, size }) : ''), [source, uid, size]);
  const playing = useArtworkPlaying(ref, motion && !legacy);
  const index = delayIndex ?? Math.max(0, TAXONOMY.findIndex((item) => item.id === id));
  const label = alt ?? record?.alt_text ?? 'Legacy item: choose a current content type.';
  const semantics = decorative ? { 'aria-hidden': true as const } : { role: 'img' as const, 'aria-label': label };
  const shape = size === 'large' ? 'aspect-[8/5] w-full [&>svg]:block [&>svg]:h-auto [&>svg]:w-full' : 'grid place-items-center [&>svg]:block [&>svg]:size-3/4 [&>svg]:overflow-visible';

  if (!html) {
    return (
      <span ref={ref} {...semantics} data-art-id={id} data-art-size={size} data-art-legacy='' className={cn('rafii-art rafii-paper text-muted-foreground grid place-items-center overflow-hidden', shape, className)}>
        <Icons.circleDashed className='size-1/2' aria-hidden />
      </span>
    );
  }
  return (
    <>
      <style href='rafii-artwork-motion' precedence='rafii'>
        {MOTION_CSS}
      </style>
      <span
        ref={ref}
        {...semantics}
        data-art-id={id}
        data-art-size={size}
        data-art-playing={playing ? '' : undefined}
        data-art-legacy={legacy ? '' : undefined}
        className={cn('rafii-art rafii-decorative-motion rafii-paper block overflow-hidden', shape, className)}
        style={{ '--art-delay': `-${(index % 7) * 0.6}s` } as CSSProperties}
        dangerouslySetInnerHTML={{ __html: html }}
      />
    </>
  );
}
