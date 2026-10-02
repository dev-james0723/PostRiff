'use client';

import { useEffect, useRef, useState, type ReactNode } from 'react';
import { motion } from 'motion/react';
import { Button } from '@/components/ui/button';
import { useMotionPreference } from '@/lib/rafii/motion';
import { cn } from '@/lib/utils';

/** The original card stays mounted while expanding into a keyboard-safe focus surface. */
export function FounderBentoFocus({ children, className }: { children: ReactNode; className?: string }) {
  const [focused, setFocused] = useState(false);
  const { reduced } = useMotionPreference();
  const card = useRef<HTMLDivElement>(null);
  const previous = useRef<{ element: HTMLElement | null; scrollY: number; height: number } | null>(null);
  function focusCard() {
    previous.current = {
      element: document.activeElement instanceof HTMLElement ? document.activeElement : null,
      scrollY: window.scrollY,
      height: card.current?.getBoundingClientRect().height ?? 0
    };
    setFocused(true);
  }
  useEffect(() => {
    if (!focused || !card.current) return;
    const element = card.current;
    const overflow = document.body.style.overflow;
    const inset = element.closest<HTMLElement>('#main-content');
    const insetZ = inset?.style.zIndex ?? '';
    if (inset) inset.style.zIndex = '80';
    const siblings: Array<[HTMLElement, boolean]> = [];
    let ancestor: HTMLElement = element;
    while (ancestor.parentElement) {
      for (const sibling of Array.from(ancestor.parentElement.children)) {
        if (sibling !== ancestor && sibling instanceof HTMLElement && !['SCRIPT', 'STYLE', 'LINK'].includes(sibling.tagName)) {
          siblings.push([sibling, sibling.inert]);
          sibling.inert = true;
        }
      }
      ancestor = ancestor.parentElement;
      if (ancestor === document.body) break;
    }
    document.body.style.overflow = 'hidden';
    element.focus({ preventScroll: true });
    const focusables = () => Array.from(element.querySelectorAll<HTMLElement>('button:not([disabled]),a[href],input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])')).filter(node => node.getClientRects().length > 0 && !node.closest('[inert]'));
    const keydown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        setFocused(false);
      }
      if (event.key !== 'Tab') return;
      const nodes = focusables();
      const first = nodes[0];
      const last = nodes.at(-1);
      if (!first || !last) { event.preventDefault(); element.focus(); return; }
      if (event.shiftKey && (document.activeElement === first || document.activeElement === element)) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    document.addEventListener('keydown', keydown);
    return () => {
      document.removeEventListener('keydown', keydown);
      document.body.style.overflow = overflow;
      if (inset) inset.style.zIndex = insetZ;
      for (const [sibling, inert] of siblings) sibling.inert = inert;
      requestAnimationFrame(() => {
        if (!previous.current?.element?.isConnected) return;
        previous.current.element.focus({ preventScroll: true });
        if (previous.current) window.scrollTo({ top: previous.current.scrollY, behavior: 'instant' });
      });
    };
  }, [focused]);
  return (
    <div className={cn('min-w-0', className)} style={focused ? { minHeight: previous.current?.height } : undefined}>
      <motion.div ref={card} tabIndex={-1} layout transition={reduced ? { duration: 0 } : { duration: 0.24 }} role={focused ? 'dialog' : undefined} aria-modal={focused || undefined} aria-label={focused ? 'Focused dashboard card' : undefined} className='group/bento relative min-w-0 outline-none' data-founder-motion='22' data-focused={focused ? 'true' : 'false'}>
        <div className='flex justify-end pb-1'>
          <Button type='button' variant='quiet' size='xs' data-founder-focus='' aria-expanded={focused} onClick={() => focused ? setFocused(false) : focusCard()}>
            {focused ? 'Restore' : 'Focus'}
          </Button>
        </div>
        {children}
      </motion.div>
    </div>
  );
}