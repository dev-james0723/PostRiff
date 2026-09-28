'use client';
import type { RefObject } from 'react';
import { gsap } from 'gsap';
import { useGSAP } from '@gsap/react';
import { motionAllowed, useMotionPreference } from '@/lib/rafii/motion';

gsap.registerPlugin(useGSAP);

/** Presentation only: reveal existing paths; never tween measurements or bridge gaps. */
export function useDiagramMotion(
  ref: RefObject<SVGSVGElement | null>,
  revision: string,
  replay: number
) {
  const { reduced } = useMotionPreference();
  useGSAP(
    (_, contextSafe) => {
      const root = ref.current;
      if (!root || !contextSafe) return;
      root.dataset.motionPhase = reduced || !motionAllowed() ? 'reduced' : 'waiting';
      if (reduced || !motionAllowed()) return;
      let disposed = false;
      const reveal = contextSafe(() => {
        if (disposed) return;
        root.dataset.motionPhase = 'animating';
        const nodes = root.querySelectorAll('[data-diagram-node]');
        if (!nodes.length) {
          root.dataset.motionPhase = 'complete';
          return;
        }
        const timeline = gsap.timeline({
          defaults: { ease: 'power2.out' },
          onComplete: () => {
            root.dataset.motionPhase = 'complete';
          }
        });
        const paths = root.querySelectorAll<SVGPathElement>('[data-diagram-path]');
        paths.forEach((path, i) => {
          const length = path.getTotalLength();
          if (length > 0)
            timeline.fromTo(
              path,
              { strokeDasharray: length, strokeDashoffset: length, opacity: 0.25 },
              {
                strokeDashoffset: 0,
                opacity: 1,
                duration: 0.65,
                clearProps: 'strokeDasharray,strokeDashoffset,opacity'
              },
              Math.min(i * 0.055, 0.28)
            );
        });
        timeline.fromTo(
          nodes,
          { opacity: 0.3, scale: 0.72, transformOrigin: '50% 50%' },
          {
            opacity: 1,
            scale: 1,
            duration: 0.42,
            stagger: { amount: 0.28 },
            clearProps: 'opacity,transform,transformOrigin'
          },
          0.18
        );
      });
      if (replay > 0 || typeof IntersectionObserver === 'undefined') {
        reveal();
        return () => {
          disposed = true;
        };
      }
      const observer = new IntersectionObserver(
        (entries) => {
          if (entries.some((entry) => entry.isIntersecting)) {
            observer.disconnect();
            reveal();
          }
        },
        { threshold: 0.15 }
      );
      observer.observe(root);
      return () => {
        disposed = true;
        observer.disconnect();
      };
    },
    { scope: ref, dependencies: [revision, replay, reduced], revertOnUpdate: true }
  );
  return { reduced };
}
