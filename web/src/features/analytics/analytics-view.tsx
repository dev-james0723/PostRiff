'use client';

import { motion, useReducedMotion } from 'motion/react';
import PageContainer from '@/components/layout/page-container';
import { Icons } from '@/components/icons';
import { ChannelIcon } from '@/components/channel-icon';
import { AnimatedBadge, type AnimatedBadgeStatus } from '@/components/motion/animated-badge';
import { NumberTicker } from '@/components/motion/number-ticker';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card';
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty';
import { Skeleton } from '@/components/ui/skeleton';
import { useAnalytics } from '@/lib/api/hooks';
import type { Metric } from '@/lib/api/types';
import { EASE_OUT } from '@/lib/ease';
import { formatDateTime } from '@/lib/time';
import { cn } from '@/lib/utils';

const infoContent = {
  title: 'Native numbers, side by side',
  sections: [
    {
      title: 'Each provider keeps its own definitions',
      description: 'A “view” on Threads is not a “view” on LinkedIn. Metrics are shown with their native names and never added across platforms.'
    },
    { title: 'Unavailable is not zero', description: 'When a provider has not reported a metric, PostRiff shows “Unavailable”. A real zero is shown as 0.' },
    { title: 'Rates carry their denominator', description: 'Every rate shows numerator and denominator; fewer than three posts is an insufficient sample.' }
  ]
};

/** Colour for the summary state the API reports (today `limited`); any other state keeps the plain badge. */
function stateStatus(state: string): AnimatedBadgeStatus | null {
  switch (state) {
    case 'ready':
    case 'available':
      return 'success';
    case 'limited':
    case 'partial':
    case 'pending':
      return 'warning';
    case 'unavailable':
      return 'neutral';
    default:
      return null;
  }
}

function StateBadge({ state }: { state: string }) {
  const status = stateStatus(state);
  if (!status) return <Badge variant='outline'>{state}</Badge>;
  return (
    <AnimatedBadge status={status} size='sm'>
      {state}
    </AnimatedBadge>
  );
}

/** A reported whole number rolls in; anything else (Unavailable, a decimal) keeps the API's own text. */
function MetricValue({ metric }: { metric: Metric }) {
  if (metric.availability === 'available' && typeof metric.value === 'number' && Number.isInteger(metric.value)) {
    return <NumberTicker value={metric.value} locale className='flex h-5' />;
  }
  return <>{metric.display}</>;
}

export function AnalyticsView() {
  const analytics = useAnalytics();
  const reduce = useReducedMotion();
  const data = analytics.data;
  return (
    <PageContainer
      pageTitle='Analytics'
      pageDescription='Post performance from providers that report it, with their own definitions.'
      infoContent={infoContent}
      pageHeaderAction={data ? <StateBadge state={data.state} /> : undefined}
    >
      {analytics.isLoading || !data ? (
        <Skeleton className='h-64 w-full' />
      ) : (
        <div className='flex flex-col gap-6'>
          {data.posts.length === 0 ? (
            <Empty>
              <EmptyHeader>
                <EmptyMedia variant='icon'>
                  <Icons.trendingUp />
                </EmptyMedia>
                <EmptyTitle>No post metrics yet</EmptyTitle>
                <EmptyDescription>
                  Metrics appear after a publication is verified on a connection whose analytics capability is Direct.
                </EmptyDescription>
              </EmptyHeader>
              {data.connections.length > 0 && (
                <ul className='text-muted-foreground mt-2 flex flex-col gap-1 text-sm'>
                  {data.connections.map((connection) => (
                    <li key={connection.id}>
                      <span className='text-foreground'>{connection.platform}</span> · {connection.account}: {connection.analytics}
                    </li>
                  ))}
                </ul>
              )}
            </Empty>
          ) : (
            <div className='grid gap-4 md:grid-cols-2 xl:grid-cols-3'>
              {data.posts.map((post, index) => (
                <motion.div
                  key={`${post.provider}-${post.providerPostId}`}
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={reduce ? { duration: 0 } : { duration: 0.28, delay: Math.min(index * 0.05, 0.3), ease: EASE_OUT }}
                >
                  <Card className='h-full'>
                    <CardHeader>
                      <CardTitle className='flex items-center gap-2 text-base'>
                        <ChannelIcon platform={post.platform || post.provider} name={post.platform || post.provider} />
                        {post.platform || post.provider}
                      </CardTitle>
                      <CardDescription>
                        {post.language || '—'} · {post.contentOrigin.replace(/_/g, ' ')} · {post.publishedState}
                      </CardDescription>
                    </CardHeader>
                    <CardContent>
                      <dl className='grid grid-cols-2 gap-x-4 gap-y-2 text-sm'>
                        {Object.entries(post.metrics).map(([key, metric]) => (
                          <div key={key} className='flex flex-col'>
                            <dt className='text-muted-foreground text-xs'>{metric.nativeName}</dt>
                            <dd className={cn('tabular-nums', metric.availability !== 'available' && 'text-muted-foreground italic')}>
                              <MetricValue metric={metric} />
                            </dd>
                          </div>
                        ))}
                      </dl>
                      {Object.keys(post.rates).length > 0 && (
                        <div className='text-muted-foreground mt-3 flex flex-col gap-1 text-xs'>
                          {Object.entries(post.rates).map(([key, rate]) => (
                            <span key={key}>
                              {key.replace(/([A-Z])/g, ' $1').toLowerCase()}: {rate.display}
                            </span>
                          ))}
                        </div>
                      )}
                    </CardContent>
                    <CardFooter className='text-muted-foreground text-xs'>
                      observed {formatDateTime(post.freshness.observedAt)} · definitions {post.definitionVersion}
                    </CardFooter>
                  </Card>
                </motion.div>
              ))}
            </div>
          )}
          <Card>
            <CardHeader>
              <CardTitle className='text-base'>Rules this page follows</CardTitle>
            </CardHeader>
            <CardContent>
              <ul className='flex flex-col gap-2 text-sm'>
                {Object.entries(data.rules).map(([key, value]) => (
                  <li key={key}>
                    <span className='font-medium'>{key.replace(/([A-Z])/g, ' $1')}</span>
                    <span className='text-muted-foreground'> — {value}</span>
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>
        </div>
      )}
    </PageContainer>
  );
}
