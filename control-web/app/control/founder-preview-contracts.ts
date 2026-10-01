export type Row = Record<string, unknown> & { id: string };
export type Mode = 'live' | 'demo';
export type Envelope<T> = { requestId: string; environment: string; asOf: string; data: T };
export type Session = { csrfToken: string; capabilities: string[] };
export type ListData = { mode: Mode; rows: Row[]; workspaces: Row[]; total: number; page: number; pageSize: number; statuses: string[]; linkedRecords?: Record<string, Row[]> };
export type Intelligence = Record<string, unknown> & { incident?: Row | null; notifications?: Row[]; followUps?: Row[]; conversation?: Row[]; messages?: Row[]; reports?: Row[]; voiceReadiness?: Record<string, unknown> };
export type WorkspaceData = {
 mode: Mode; revision: number; customers: Row[]; workspaces: Row[]; subscriptions: Row[]; payments: Row[]; usage: Row[]; tickets: Row[]; activity: Row[];
 connections: { id: string; label: string; state: string; required: boolean; detail: string }[];
 summary: { customers: number; workspaces: number; activeSubscriptions: number; openRequests: number; billingReviews?: number; [key: string]: unknown };
 limits: { pageSize: number; truncated: boolean }; paymentState: string; supportState: string; usageState: string;
 catalog?: Record<string, unknown> & { plans?: Row[] }; manifest?: Record<string, unknown>; analytics?: Record<string, unknown>; scenario?: string | Record<string, unknown>; receipt?: Record<string, unknown>; intelligence?: Intelligence;
};
export function scenarioKey(data?: WorkspaceData) { return typeof data?.scenario === 'string' ? data.scenario : String(data?.scenario?.id || data?.scenario?.key || 'normal'); }
export function state(value: unknown) { return String(value || 'Not recorded').replaceAll('_', ' '); }
export function label(row: Row) { return String(row.name || row.title || row.plan || row.label || (row.dimension ? state(row.dimension) : row.id)); }
export function money(amount: unknown, currency: unknown = 'USD') { return typeof amount === 'number' || typeof amount === 'string' ? new Intl.NumberFormat('en', { style: 'currency', currency: String(currency || 'USD'), maximumFractionDigits: 0 }).format(Number(amount) / 100) : 'Not available'; }
export function href(section: string, mode: Mode, record?: string) { return '/control/' + section + '?mode=' + mode + (record ? '&record=' + encodeURIComponent(record) : ''); }
export const scenarios = [['normal', 'Normal operation'], ['payment_failure', 'Payment failure'], ['outage', 'Bug / outage'], ['stale_data', 'Stale data'], ['notification_failure', 'Notification failure'], ['recovery', 'Recovery']] as const;
