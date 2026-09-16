'use client';

import PageContainer from '@/components/layout/page-container';
import { Icons } from '@/components/icons';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card';
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty';
import { Skeleton } from '@/components/ui/skeleton';
import { useAnalytics } from '@/lib/api/hooks';
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

export function AnalyticsView() {
  const analytics = useAnalytics();
  const data = analytics.data;
  return (
    <PageContainer
      pageTitle='Analytics'
      pageDescription='Post performance from providers that report it, with their own definitions.'
      infoContent={infoContent}
      pageHeaderAction={data ? <Badge variant='outline'>{data.state}</Badge> : undefined}
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
              {data.posts.map((post) => (
                <Card key={`${post.provider}-${post.providerPostId}`}>
                  <CardHeader>
                    <CardTitle className='text-base'>{post.platform || post.provider}</CardTitle>
                    <CardDescription>
                      {post.language || '—'} · {post.contentOrigin.replace(/_/g, ' ')} · {post.publishedState}
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    <dl className='grid grid-cols-2 gap-x-4 gap-y-2 text-sm'>
                      {Object.entries(post.metrics).map(([key, metric]) => (
                        <div key={key} className='flex flex-col'>
                          <dt className='text-muted-foreground text-xs'>{metric.nativeName}</dt>
                          <dd className={cn('tabular-nums', metric.availability !== 'available' && 'text-muted-foreground italic')}>{metric.display}</dd>
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
