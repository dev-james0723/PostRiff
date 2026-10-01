/**
 * Payloads of the revenue slice's own routes (`src/rafii_control/founder_metrics_revenue.py`, CONTRACTS §8.A). They are
 * read exactly as sent; amounts stay in native minor units with their currency, and nothing here is summed or derived.
 */
import type { DataState, Timestamp } from '../customers/kit/types';

export const MOVEMENTS = ['new', 'expansion', 'reactivation', 'contraction', 'churn'] as const;
export type Movement = (typeof MOVEMENTS)[number];

/** The rows `mrr_movements` returns per currency when grouped by movement, in waterfall order. */
export const BRIDGE_STEPS = ['opening', ...MOVEMENTS, 'closing'] as const;
export type BridgeStep = (typeof BRIDGE_STEPS)[number];

export interface RouteInterval {
  start: string;
  end: string;
  timeZone: string;
}

/** One billing event inside the interval for a customer behind a bridge segment (ids, enums and amounts only). */
export interface MovementEvent {
  id: string;
  eventId?: string | null;
  type?: string | null;
  at?: Timestamp | null;
  applied?: boolean | null;
  priorStatus?: string | null;
  newStatus?: string | null;
  plan?: string | null;
  unitAmountMinor?: number | null;
  quantity?: number | null;
  interval?: string | null;
  intervalCount?: number | null;
  currency?: string | null;
  discountMinor?: number | null;
}

/** `GET /revenue/movements`: one customer (workspace, else subscription) behind one bridge segment. */
export interface MovementRow {
  customer: string;
  workspaceId: string | null;
  /** The workspace owner, which is the Customers page's record id (Customer 360). */
  customerId: string | null;
  subscriptionIds: string[];
  plan: string | null;
  currency: string | null;
  movement: Movement | 'unchanged' | 'unknown';
  statusChange: { opening: string | null; closing: string | null };
  openingMrrMinor: number;
  closingMrrMinor: number;
  deltaMinor: number;
  events: MovementEvent[];
  eventsTruncated: boolean;
  href: string | null;
}

export interface MovementsData {
  mode: 'live' | 'demo';
  interval: RouteInterval;
  movement: Movement | null;
  limit: number;
  definition?: string;
  rows: MovementRow[];
  truncated: boolean;
  /** Why there are no rows: not_instrumented, insufficient_history, source_not_configured or demo_not_simulated. */
  reason?: string;
  collectingSince?: string | null;
  history?: { availableDays: number; requiredDays: number } | null;
  catalogLabel?: string;
}

export const INVOICE_STATUSES = ['draft', 'open', 'paid', 'uncollectible', 'void'] as const;
export type InvoiceStatus = (typeof INVOICE_STATUSES)[number];

/** `GET /revenue/invoices`: one invoice record (every plan), newest first. */
export interface InvoiceRow {
  invoiceId: string;
  workspaceId: string | null;
  customerId: string | null;
  subscriptionId: string | null;
  billingReason: string | null;
  periodStart: Timestamp | null;
  periodEnd: Timestamp | null;
  amountDueMinor: number | null;
  amountPaidMinor: number | null;
  currency: string | null;
  status: InvoiceStatus | string;
  livemode: boolean | null;
  eventAt: Timestamp | null;
  href: string | null;
}

export interface InvoicesData {
  mode: 'live' | 'demo';
  interval: RouteInterval;
  status: InvoiceStatus | null;
  limit: number;
  rows: InvoiceRow[];
  truncated: boolean;
  reason?: string;
  collectingSince?: string | null;
  catalogLabel?: string;
}

/** A waterfall step: the server's value and state, plus the bar geometry drawn from it. */
export interface BridgeBar {
  step: BridgeStep;
  label: string;
  short: string;
  value: number | null;
  dataState: DataState;
  customers: number | null;
  /** Geometry only: where the floating bar starts and how tall it is. Labels always show `value`. */
  base: number;
  size: number;
  direction: 'total' | 'up' | 'down';
}
