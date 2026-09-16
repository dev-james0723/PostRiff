import { cn } from '@/lib/utils';

/**
 * transitions.dev success check: the mark fades, rotates, un-blurs and bobs into
 * place while its stroke draws (`src/styles/transitions.css`). Pass `animate`
 * only for a confirmation that just happened in this view; a state that was
 * already true when the view mounted renders at rest.
 */
function SuccessCheck({ animate = true, className }: { animate?: boolean; className?: string }) {
  return (
    <span
      aria-hidden
      data-state={animate ? 'in' : 'rest'}
      className={cn('t-success-check', className)}
    >
      <svg
        viewBox='0 0 24 24'
        fill='none'
        stroke='currentColor'
        strokeWidth={2.5}
        strokeLinecap='round'
        strokeLinejoin='round'
        className='size-full'
        style={{ '--success-len': 21 } as React.CSSProperties}
      >
        <path d='M5 12.5l4.5 4.5L19 7.5' />
      </svg>
    </span>
  );
}

export { SuccessCheck };
