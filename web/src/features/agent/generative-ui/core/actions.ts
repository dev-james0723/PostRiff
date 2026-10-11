/**
 * Host-side handling of OpenUI action events (React-free; D-A12, D-A13).
 *
 * Generated controls may only do local, safe things: `@Set`/`@Reset` of `$variables`, `@Run(query)` to refresh a read,
 * `@ToAssistant("…")` to ask Rafii a labeled follow-up, and `@OpenUrl("/app/…")` to open an in-app page. Everything
 * else is dropped. Saved data changes only through Rafii's ActionButton and D's action bridge, never through here.
 *   - `sanitizePlan` filters a model-built `Action([...])` plan before it reaches OpenUI's `triggerAction`;
 *   - `createHostActionHandler` is the `<Renderer onAction>`: `continue_conversation` → the existing turn path with the
 *     artifact's ids (model `context` and the form snapshot are never forwarded); `open_url` → `safeOpenUrl`, i.e. a
 *     same-origin path the site agent's route manifest allows (`safeHref`), never a script/data/blob or other-host URL.
 */
import type { ActionPlan, ActionStep } from '@openuidev/lang-core';
import routeManifestJson from '@/lib/site-agent/route-manifest.json';
import { safeHref, type RouteManifest } from '@/lib/site-agent/routes';

const ROUTES = routeManifestJson as RouteManifest;

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
    if (parsed.username || parsed.password) return null;
    return `${parsed.pathname}${parsed.search}${parsed.hash}`;
  } catch {
    return null;
  }
}

/**
 * Whitespace or a control character anywhere (C0, space, DEL, C1, NBSP, BOM, line separators): browsers strip or ignore
 * some of these, so `\tjavascript:` or `java\nscript:` could otherwise reach a scheme. No allowed in-app href contains one.
 */
function hasUnsafeChar(value: string): boolean {
  for (let i = 0; i < value.length; i++) {
    const code = value.charCodeAt(i);
    if (code <= 0x20 || (code >= 0x7f && code <= 0xa0)) return true;
  }
  return /\s/.test(value);
}
const DOT_SEGMENT = /^(?:\.|%2e){1,2}$/i;

/**
 * HF-3: the only target `@OpenUrl` may open. An in-app path (or this app's own https/http origin reduced to its path,
 * without credentials) that the route manifest allows through the app's existing `safeHref` — a known page, declared query
 * keys and values, an anchor only on help articles. Script/data/blob/file schemes in any case or encoding,
 * protocol-relative and backslash forms, other hosts, dot segments and undeclared pages or parameters are refused (null).
 */
export function safeOpenUrl(url: unknown, origin?: string | null): string | null {
  if (typeof url !== 'string' || !url || hasUnsafeChar(url)) return null;
  const path = safeInAppPath(url, origin);
  if (!path) return null;
  const pathname = path.split(/[?#]/, 1)[0];
  if (pathname.split('/').some((segment) => DOT_SEGMENT.test(segment))) return null;
  try {
    return safeHref(ROUTES, path);
  } catch {
    return null; // a malformed percent-escape in the query (decodeURIComponent) is a refusal, never a crash
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
      const path = safeOpenUrl(event.params?.url, options.origin ?? null);
      if (path) options.onNavigate(path);
      else options.onBlocked?.('link');
    }
    // Every other type (custom events built by generated code) is ignored on purpose.
  };
}
