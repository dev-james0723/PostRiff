import { cn } from '@/lib/utils';

/**
 * transitions.dev "learn more" chevron: put `t-learn` on the link or button that
 * holds it, and on hover or keyboard focus the chevron shifts right while its two
 * arms spread into an arrow (`src/styles/transitions.css`).
 */
function LearnMoreChevron({ className }: { className?: string }) {
  return (
    <span aria-hidden className={cn('t-learn-chevron', className)}>
      <svg
        viewBox='0 0 16 16'
        fill='none'
        stroke='currentColor'
        strokeWidth={1.75}
        strokeLinecap='round'
        className='size-4'
      >
        <path className='t-learn-arm t-learn-arm-top' d='M6 4L10 8' />
        <path className='t-learn-arm t-learn-arm-bot' d='M10 8L6 12' />
      </svg>
    </span>
  );
}

export { LearnMoreChevron };
