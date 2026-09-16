import type { ReactNode } from 'react';
import { Badge } from '@/components/ui/badge';
import { Card, CardAction, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';

interface StatCardProps {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  badge?: ReactNode;
  footer?: ReactNode;
  loading?: boolean;
}

/** Overview stat tile in the template's card grammar (description → big number → footer). */
export function StatCard({ label, value, hint, badge, footer, loading }: StatCardProps) {
  return (
    <Card className='@container/card'>
      <CardHeader>
        <CardDescription>{label}</CardDescription>
        <CardTitle className='text-2xl font-semibold tabular-nums @[250px]/card:text-3xl'>
          {loading ? <Skeleton className='h-8 w-20' /> : value}
        </CardTitle>
        {badge && (
          <CardAction>
            <Badge variant='outline'>{badge}</Badge>
          </CardAction>
        )}
      </CardHeader>
      {(hint || footer) && (
        <CardFooter className='flex-col items-start gap-1.5 text-sm'>
          {hint && <div className='line-clamp-1 flex gap-2 font-medium'>{hint}</div>}
          {footer && <div className='text-muted-foreground'>{footer}</div>}
        </CardFooter>
      )}
    </Card>
  );
}
