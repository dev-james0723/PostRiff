/**
 * Host-side handling of OpenUI action events (React-free; D-A12, D-A13).
 *
 * Generated controls may only do local, safe things: `@Set`/`@Reset` of `$variables`, `@Run(query)` to refresh a read,
 * `@ToAssistant("…")` to ask Rafii a labeled follow-up, and `@OpenUrl("/app/…")` to open an in-app page. Everything
 * else is dropped. Saved data changes only through Rafii's ActionButton and D's action bridge, never through here.
 *   - `sanitizePlan` filters a model-built `Action([...])` plan before it reaches OpenUI's `triggerAction`;
 *   - `createHostActionHandler` is the `<Renderer onAction>`: `continue_conversation` → the existing turn path with the
 *     artifact's ids (model `context` and the form snapshot are never forwarded); `open_url` → same-origin path only.
 */
import type { ActionPlan, ActionStep } from '@openuidev/lang-core';

const SAFE_STEPS = new Set(['set', 'reset', 'continue_conversation', 'open_url']);
export const MAX_FOLLOW_UP_CHARS = 500;

export function sanitizePlan(action: unknown): ActionPlan | null {
  if (!action || typeof action !== 'object' || !Array.isArray((action as ActionPlan).steps)) return null;
  const steps = (action as ActionPlan).steps.filter(
    (step): step is ActionStep =>
      !!step &&
      typeof step === 'object' &&
      (SAFE_STEPS.has(step.type) || (step.type === 'run' && (step as { refType?: string }).refType === 'query')),
  );
  return { steps: steps.slice(0, 12) };
}

/** An in-app path (`/app/…`) or a same-origin absolute URL reduced to its path; anything else is refused. */
export function safeInAppPath(url: unknown, origin?: string | null): string | null {
  if (typeof url !== 'string') return null;
  const value = url.trim();
  if (!value || value.length > 2048) return null;
  for (let i = 0; i < value.length; i++) {
    const code = value.charCodeAt(i);
    if (code < 0x20 || code === 0x7f) return null;
  }
  if (value.includes('\\')) return null;
  if (value.startsWith('/') && !value.startsWith('//')) return value;
  if (!origin) return null;
  try {
    const parsed = new URL(value);
    if (parsed.origin !== origin) return null;
    if (parsed.protocol !== 'https:' && parsed.protocol !== 'http:') return null;
    return `${parsed.pathname}${parsed.search}${parsed.hash}`;
  } catch {
    return null;
  }
}

export interface HostActionEvent {
  type: string;
  params?: Record<string, unknown>;
  humanFriendlyMessage?: string;
}

export interface HostActionOptions {
  /** A labeled follow-up through the existing turn path (the bridge adds the artifact ids). */
  onFollowUp(message: string): void;
  onNavigate(path: string): void;
  onBlocked?(kind: 'link'): void;
  origin?: string | null;
}

export function followUpText(value: unknown): string {
  if (typeof value !== 'string') return '';
  const text = value.replace(/\s+/g, ' ').trim();
  return text.length > MAX_FOLLOW_UP_CHARS ? `${text.slice(0, MAX_FOLLOW_UP_CHARS - 1)}…` : text;
}

export function createHostActionHandler(options: HostActionOptions): (event: HostActionEvent) => void {
  return (event) => {
    if (!event || typeof event !== 'object') return;
    if (event.type === 'continue_conversation') {
      const message = followUpText(event.humanFriendlyMessage);
      if (message) options.onFollowUp(message);
      return;
    }
    if (event.type === 'open_url') {
      const path = safeInAppPath(event.params?.url, options.origin ?? null);
      if (path) options.onNavigate(path);
      else options.onBlocked?.('link');
    }
    // Every other type (custom events built by generated code) is ignored on purpose.
  };
}
