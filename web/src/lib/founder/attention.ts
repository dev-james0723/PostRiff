import type { AttentionAction, AttentionItem, NormalizedAttentionItem } from './types';

/**
 * Attention actions as the Overview renders them (PRD §5.2 C, CONTRACTS §3 `actions:[{id,label,kind,href,incidentId,version}]`).
 * The server sends objects; a bare kind string (the agent tool's Demo attention list still uses them) becomes an
 * object with a fixed label. An `ack` without the incident id and the exact version it would acknowledge is dropped:
 * the page never guesses a version. Nothing here computes a number.
 */
const LABELS: Record<string, string> = { explain: 'Explain', open: 'Open', draft_reminder: 'Draft reminder', ack: 'Acknowledge', acknowledge: 'Acknowledge' };

function labelFor(kind: string): string {
  return LABELS[kind] ?? kind.replaceAll('_', ' ').replace(/^./, (c) => c.toUpperCase());
}

function kindOf(value: string): string {
  return value === 'acknowledge' ? 'ack' : value;
}

export function normalizeAttentionAction(action: AttentionAction | string, item: Pick<AttentionItem, 'href'>): AttentionAction {
  if (typeof action === 'string') {
    const kind = kindOf(action);
    return { id: action, kind, label: labelFor(kind), href: kind === 'open' ? item.href : null };
  }
  const kind = kindOf(String(action.kind ?? action.id ?? 'explain'));
  return { ...action, id: action.id ?? kind, kind, label: action.label ?? labelFor(kind), href: action.href ?? (kind === 'open' ? item.href : null) };
}

/** Whether an ack action names what it would acknowledge; the server owns the version, the page only repeats it. */
export function ackIsBound(action: AttentionAction): boolean {
  return action.kind !== 'ack' || (typeof action.incidentId === 'string' && action.incidentId.length > 0 && typeof action.version === 'number' && Number.isInteger(action.version));
}

export function normalizeAttentionItem(item: AttentionItem): NormalizedAttentionItem {
  const actions = (Array.isArray(item.actions) ? item.actions : []).map((action) => normalizeAttentionAction(action, item)).filter(ackIsBound);
  return { ...item, actions };
}
