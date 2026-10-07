import type { NextConfig } from 'next';
import { assertPreviewEnvironment } from './src/lib/deployment-env.mjs';
assertPreviewEnvironment(process.env);
import { withSentryConfig } from '@sentry/nextjs/config';

// The Python WSGI API is served at /api/*. On Vercel the platform-level
// rewrite in the repo-root vercel.json routes /api to the Python service, so
// this rewrite exists only for local development (or when an explicit origin
// is provided). Production must NOT add it.
const apiOrigin = process.env.POSTRIFF_API_ORIGIN;
const shouldProxyApi = Boolean(apiOrigin) || process.env.NODE_ENV === 'development';

/**
 * Founder admin redirects (CONTRACTS §6, PRD §5.1): the retired `/control/*` preview and the two merged sections.
 * Mirrors `FOUNDER_REDIRECTS` in `src/config/founder-nav.ts` verbatim (this file cannot import TypeScript);
 * `tests/founder-nav.test.cjs` fails when the two drift. Query strings are preserved by Next.
 */
const founderRedirects = [
  { source: '/control/command', destination: '/founder', permanent: false },
  { source: '/control/billing', destination: '/founder/revenue', permanent: false },
  { source: '/control/connections', destination: '/founder/operations?tab=connections', permanent: false },
  { source: '/control/workspaces', destination: '/founder/customers?tab=workspaces', permanent: false },
  { source: '/control/:tab(evidence|engineering|founder|audit|infrastructure)', destination: '/founder/advanced?tab=:tab', permanent: false },
  { source: '/control', destination: '/founder', permanent: false },
  { source: '/control/:section', destination: '/founder/:section', permanent: false },
  { source: '/founder/connections', destination: '/founder/operations?tab=connections', permanent: false },
  { source: '/founder/workspaces', destination: '/founder/customers?tab=workspaces', permanent: false }
];

const baseConfig: NextConfig = {
  allowedDevOrigins: ['127.0.0.1'],
  output: process.env.BUILD_STANDALONE === 'true' ? 'standalone' : undefined,
  // Local only: `next dev` allows one server per dist dir, so a second harness (another API port)
  // runs with POSTRIFF_DIST_DIR=.next-alt. Production builds never set it.
  distDir: process.env.POSTRIFF_DIST_DIR || '.next',
  images: {
    remotePatterns: []
  },
  // Pin the workspace root to this app so Turbopack never infers the repo
  // root (or a stray lockfile above it) as the project root.
  turbopack: {
    root: process.cwd()
  },
  transpilePackages: ['geist'],
  compiler: {
    removeConsole: process.env.NODE_ENV === 'production'
  },
  async redirects() {
    return founderRedirects;
  },
  async rewrites() {
    if (!shouldProxyApi) return [];
    return [
      {
        source: '/api/:path*',
        destination: `${apiOrigin ?? 'http://127.0.0.1:4331'}/api/:path*`
      },
      {
        // Dev harness only: the synthetic provider consent page.
        source: '/dev/:path*',
        destination: `${apiOrigin ?? 'http://127.0.0.1:4331'}/dev/:path*`
      }
    ];
  }
};

let configWithPlugins = baseConfig;

// Conditionally enable Sentry configuration
if (!process.env.NEXT_PUBLIC_SENTRY_DISABLED) {
  configWithPlugins = withSentryConfig(configWithPlugins, {
    org: process.env.NEXT_PUBLIC_SENTRY_ORG,
    project: process.env.NEXT_PUBLIC_SENTRY_PROJECT,
    // Only print logs for uploading source maps in CI
    silent: !process.env.CI,

    // Upload a larger set of source maps for prettier stack traces (increases build time)
    widenClientFileUpload: true,

    // Route browser requests to Sentry through a Next.js rewrite to circumvent ad-blockers.
    tunnelRoute: '/monitoring',

    // Disable Sentry telemetry
    telemetry: false,

    // Sentry v10: moved under webpack namespace
    webpack: {
      reactComponentAnnotation: {
        enabled: true
      },
      treeshake: {
        removeDebugLogging: true
      }
    },

    // Disable source map upload when org/project are not configured
    sourcemaps: {
      disable: !process.env.NEXT_PUBLIC_SENTRY_ORG || !process.env.NEXT_PUBLIC_SENTRY_PROJECT
    }
  });
}

const nextConfig = configWithPlugins;
export default nextConfig;
