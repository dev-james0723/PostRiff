'use client';
import { useState, type ReactNode } from 'react';
import { motion, useReducedMotion } from 'motion/react';
import { IconChevronDown } from '@tabler/icons-react';

/** Native disclosure semantics remain usable before hydration; motion only explains expansion. */
export function Disclosure({
  title,
  children,
  className = '',
  open = false
}: {
  title: ReactNode;
  children: ReactNode;
  className?: string;
  open?: boolean;
}) {
  const [expanded, setExpanded] = useState(open);
  const reduced = useReducedMotion();
  return (
    <details
      className={`trend-disclosure ${className}`}
      open={expanded}
      onToggle={(e) => setExpanded(e.currentTarget.open)}
    >
      <summary className='rafii-focus' aria-expanded={expanded}>
        <span>{title}</span>
        <IconChevronDown
          aria-hidden='true'
          size={17}
          stroke={1.6}
          className='trend-disclosure-chevron'
        />
      </summary>
      <motion.div
        className='trend-disclosure-body'
        initial={false}
        animate={{ opacity: expanded ? 1 : 0, y: expanded ? 0 : -4 }}
        transition={{ duration: reduced ? 0 : 0.2, ease: [0.22, 1, 0.36, 1] }}
      >
        {children}
      </motion.div>
    </details>
  );
}
