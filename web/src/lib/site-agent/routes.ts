/**
 * Pure helpers over the route manifest (`route-manifest.json`, a byte-identical twin of the API's
 * `site_agent/route_manifest.json`). The panel only follows links the manifest allows, even though the
 * server already built them: an href from an answer is re-checked here before it becomes a link.
 * No imports, so `site-agent.test.cjs` can load this file with `ts.transpileModule`.
 */

export interface ManifestRoute {
  id: string;
  pattern: string;
  family: string;
  title: string;
  summary: string;
  entityTypes: string[];
  query: Record<string, string | string[]>;
  helpDocs: string[];
  access: { permission?: string; role?: string };
  navigable?: boolean;
}

export interface RouteManifest {
  version: string;
  routes: ManifestRoute[];
}

const ID_VALUE = /^[A-Za-z0-9_.:-]{1,120}$/;
const ANCHOR = /^[a-z0-9-]{1,80}$/;
const PARAM = /^\[([a-zA-Z]+)\]$/;

function segments(path: string): string[] {
  return path.split('/').filter(Boolean);
}

/** The manifest route for an app pathname, with its path parameters; null when the manifest does not know it. */
export function matchRoute(manifest: RouteManifest, pathname: string): { route: ManifestRoute; params: Record<string, string> } | null {
  if (typeof pathname !== 'string' || !pathname.startsWith('/') || pathname.length > 300) return null;
  const parts = segments(pathname.split('?')[0].split('#')[0]);
  for (const route of manifest.routes) {
    const pattern = segments(route.pattern);
    if (pattern.length !== parts.length) continue;
    const params: Record<string, string> = {};
    let ok = true;
    for (let i = 0; i < pattern.length; i++) {
      const name = PARAM.exec(pattern[i]);
      if (name) {
        if (!ID_VALUE.test(parts[i])) {
          ok = false;
          break;
        }
        params[name[1]] = parts[i];
      } else if (pattern[i] !== parts[i]) {
        ok = false;
        break;
      }
    }
    if (ok) return { route, params };
  }
  return null;
}

/**
 * The href itself when every part is allowed by the manifest (known path, allowed query keys and values,
 * an anchor only on help articles); null otherwise. Absolute URLs, protocol-relative URLs and scripts never pass.
 */
export function safeHref(manifest: RouteManifest, href: string): string | null {
  if (typeof href !== 'string' || !href.startsWith('/') || href.startsWith('//') || href.length > 400) return null;
  const [beforeHash, anchor] = href.split('#', 2);
  const [path, query] = beforeHash.split('?', 2);
  const matched = matchRoute(manifest, path);
  if (!matched) return null;
  if (anchor !== undefined && (matched.route.id !== 'help_article' || !ANCHOR.test(anchor))) return null;
  if (query) {
    for (const pair of query.split('&')) {
      const [rawKey, rawValue = ''] = pair.split('=', 2);
      const key = decodeURIComponent(rawKey);
      const value = decodeURIComponent(rawValue.replace(/\+/g, ' '));
      const spec = matched.route.query[key];
      if (spec === undefined) return null;
      if (spec === 'id' ? !ID_VALUE.test(value) : Array.isArray(spec) ? !spec.includes(value) : true) return null;
    }
  }
  return href;
}

/** The route family of a pathname, for suggestions and the context chip. */
export function familyOf(manifest: RouteManifest, pathname: string): string | null {
  return matchRoute(manifest, pathname)?.route.family ?? null;
}
