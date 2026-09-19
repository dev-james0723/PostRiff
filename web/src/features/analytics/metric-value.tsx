'use client';

import { NumberTicker } from '@/components/motion/number-ticker';
import type { Metric } from '@/lib/api/types';
import { cn } from '@/lib/utils';

export function isUnavailable(metric: Metric) {
  return metric.availability !== 'available';
}

/** A reported whole number rolls in; anything else (Unavailable, a decimal) keeps the API's own text. */
export function MetricValue({ metric }: { metric: Metric }) {
  if (
    metric.availability === 'available' &&
    typeof metric.value === 'number' &&
    Number.isInteger(metric.value)
  ) {
    return <NumberTicker value={metric.value} locale className='flex h-5' />;
  }
  return <>{metric.display}</>;
}

/** The value with the muted, italic treatment an unreported metric gets; "Unavailable" stays a word, never 0. */
export function MetricCell({
  metric,
  className,
  ...props
}: { metric: Metric } & React.ComponentProps<'span'>) {
  return (
    <span
      className={cn(
        'tabular-nums',
        isUnavailable(metric) && 'text-muted-foreground italic',
        className
      )}
      {...props}
    >
      <MetricValue metric={metric} />
    </span>
  );
}
