'use client';

import { useQuery } from '@tanstack/react-query';
import { founderFetch } from '@/lib/founder/api';
import { useFounderScope } from '../customers/kit/api';
import { periodInterval, resolvedTimeZone, type PeriodKey } from '../customers/kit/period';
import type { Envelope, MetricQuery, MetricResult } from '../customers/kit/types';
import { routeSearch } from './rows';
import type { InvoiceStatus, InvoicesData, Movement, MovementsData } from './types';

/**
 * The revenue slice's own reads. Keys follow `['founder', mode, environment, …]` (useFounderScope) so a mode or
 * environment switch never shares cache. Responses are used as sent; a missing field is shown as not recorded.
 */

/** The customers behind one bridge segment (`GET /revenue/movements`), fetched only once a segment is chosen. */
export function useRevenueMovements(period: PeriodKey, movement: Movement | null) {
  const scope = useFounderScope();
  return useQuery({
    queryKey: scope.key('revenue-movements', period, movement),
    enabled: scope.ready && movement !== null,
    staleTime: 60_000,
    queryFn: ({ signal }) => founderFetch<Envelope<MovementsData>>(`/revenue/movements${routeSearch(scope.mode, period, periodInterval(period), { movement })}`, { signal })
  });
}

/** Invoice records for the invoices and dunning tables (`GET /revenue/invoices`), optionally one status. */
export function useRevenueInvoices(period: PeriodKey, status: InvoiceStatus | null = null) {
  const scope = useFounderScope();
  return useQuery({
    queryKey: scope.key('revenue-invoices', period, status),
    enabled: scope.ready,
    staleTime: 60_000,
    queryFn: ({ signal }) => founderFetch<Envelope<InvoicesData>>(`/revenue/invoices${routeSearch(scope.mode, period, periodInterval(period), { status })}`, { signal })
  });
}

/** The next `days` days from now: the scenario window the forecast is drawn over (the kit's periods all end now). */
export function futureInterval(days: number, now: Date = new Date(), timeZone: string = resolvedTimeZone()): MetricQuery['interval'] {
  const end = new Date(now.getTime() + days * 86_400_000);
  return { start: now.toISOString(), end: end.toISOString(), timeZone };
}

/** `mrr_forecast` by currency and day over the next `days` days, through the receipt path like every metric. */
export function useMrrForecast(days = 30) {
  const scope = useFounderScope();
  return useQuery({
    queryKey: scope.key('metric', 'mrr_forecast', `next-${days}d`, 'currency|window'),
    enabled: scope.ready,
    staleTime: 60_000,
    queryFn: ({ signal }): Promise<MetricResult> =>
      scope.api.metricsQuery({ metricIds: ['mrr_forecast'], interval: futureInterval(days), groupBy: ['currency', 'window'], filters: [], comparison: 'none', limit: 1000 }, scope.mode, { signal })
  });
}
