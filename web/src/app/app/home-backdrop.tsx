'use client';

import { useEffect, useState } from 'react';
import { ParticleField } from '@/components/motion/particle-field';

const COMPOSER = '[data-tour="composer"]';

/**
 * Home's ambient backdrop: the particle field behind the agent chat. It quiets down while
 * focus is inside the composer (the person is writing) and dims behind the page heading so
 * the title keeps its contrast. It reads no workspace data.
 */
export function HomeBackdrop() {
  const [writing, setWriting] = useState(false);

  useEffect(() => {
    const update = () => setWriting(Boolean(document.activeElement?.closest(COMPOSER)));
    document.addEventListener('focusin', update);
    document.addEventListener('focusout', update);
    return () => {
      document.removeEventListener('focusin', update);
      document.removeEventListener('focusout', update);
    };
  }, []);

  return (
    <ParticleField
      className='absolute inset-x-0 top-0 -z-10 h-[28rem] [mask-image:linear-gradient(to_bottom,black_0%,black_50%,transparent_100%)] md:h-[44rem]'
      density={2}
      max={120}
      radius={170}
      mode='repel'
      link={110}
      alpha={0.34}
      quiet={writing}
      safeArea='main h1'
    />
  );
}
