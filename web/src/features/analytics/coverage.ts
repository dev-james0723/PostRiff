/**
 * Coverage is computed on the client from three things the API already returns:
 * the channel list (per-capability levels), the workspace snapshot (verified jobs)
 * and the analytics summary (posts with at least one reading). Nothing here is
 * estimated; every count is a length of a real list.
 */
import type { AnimatedBadgeStatus } from '@/components/motion/animated-badge';
import type { Analytics, AnalyticsPost, ChannelView, Job, ProviderView } from '@/lib/api/types';

export type AnalyticsPostRow = AnalyticsPost;

export type JobRow = Job;

export type CoverageState = 'unavailable' | 'pending' | 'partial' | 'ready';

export interface ConnectionCoverage {
  id: string;
  platform: string;
  account: string;
  /** The API's own level string for the analytics capability (`Direct`, `Assisted`, `Bridge`, `Unsupported`). */
  level: string;
  evidence: string;
  verifiedAt: number | null;
  /** Whether the provider adapter offers analytics at all (LinkedIn does not for this app). */
  providerOffersAnalytics: boolean;
  providerId: string | null;
  direct: boolean;
  verifiedJobs: JobRow[];
  /** Verified jobs on this account that have at least one reading in the summary. */
  readJobIds: Set<string>;
  posts: AnalyticsPostRow[];
  lastObservedAt: number | null;
}

export interface Coverage {
  connections: ConnectionCoverage[];
  /** Posts whose connection could not be told apart from the channel list; still shown under "All". */
  unmatchedPosts: AnalyticsPostRow[];
  /** True when at least one post had no `connectionId` and was matched by platform instead. */
  usesPlatformFallback: boolean;
}

export const STATE_LABEL: Record<CoverageState, string> = {
  unavailable: 'No analytics source',
  pending: 'Waiting for first reading',
  partial: 'Some posts unread',
  ready: 'All posts read'
};

export const STATE_STATUS: Record<CoverageState, AnimatedBadgeStatus> = {
  unavailable: 'neutral',
  pending: 'warning',
  partial: 'warning',
  ready: 'success'
};

export const ALL_CONNECTIONS = 'all';

function findProvider(providers: ProviderView[], platform: string) {
  return providers.find((p) => p.platform.toLowerCase() === platform.toLowerCase()) ?? null;
}

/**
 * The connection a post belongs to. When the API named a connection, only that id counts (a post
 * from a removed account stays unmatched rather than landing on another account). Without one, the
 * post goes to the only channel on its platform, and the page says it matched by platform.
 */
function matchPost(
  post: AnalyticsPostRow,
  channels: ChannelView[]
): { id: string | null; byPlatform: boolean } {
  if (post.connectionId) {
    return {
      id: channels.some((c) => c.id === post.connectionId) ? post.connectionId : null,
      byPlatform: false
    };
  }
  const platform = (post.platform ?? post.provider).toLowerCase();
  const onPlatform = channels.filter((c) => c.platform.toLowerCase() === platform);
  return onPlatform.length === 1
    ? { id: onPlatform[0].id, byPlatform: true }
    : { id: null, byPlatform: false };
}

function matchJob(job: JobRow, channels: ChannelView[]): string | null {
  if (job.manifest.channelId && channels.some((c) => c.id === job.manifest.channelId))
    return job.manifest.channelId;
  const hit = channels.find(
    (c) =>
      c.platform.toLowerCase() === job.manifest.platform.toLowerCase() &&
      c.account === job.manifest.account
  );
  return hit?.id ?? null;
}

/** The job that published a post: by the provider's own reference first, then by the job id the reading carries. */
export function jobForPost(
  post: AnalyticsPost,
  jobs: { byReference: Map<string, JobRow>; byId: Map<string, JobRow> }
) {
  return (
    jobs.byReference.get(post.providerPostId) ??
    (post.jobId ? (jobs.byId.get(post.jobId) ?? null) : null)
  );
}

export function indexJobs(jobs: JobRow[]) {
  const byReference = new Map<string, JobRow>();
  const byId = new Map<string, JobRow>();
  for (const job of jobs) {
    if (job.providerReference) byReference.set(job.providerReference, job);
    byId.set(job.id, job);
  }
  return { byReference, byId };
}

export function buildCoverage(input: {
  channels: ChannelView[];
  providers: ProviderView[];
  jobs: Job[];
  posts: AnalyticsPost[];
}): Coverage {
  const { channels, providers } = input;
  const byId = new Map<string, ConnectionCoverage>();
  for (const channel of channels) {
    const capability = channel.capabilities.analytics;
    const provider = findProvider(providers, channel.platform);
    byId.set(channel.id, {
      id: channel.id,
      platform: channel.platform,
      account: channel.account,
      level: capability?.level ?? 'Unsupported',
      evidence: capability?.evidence ?? '',
      verifiedAt: capability?.verifiedAt ?? null,
      providerOffersAnalytics: provider?.capabilities.analytics ?? false,
      providerId: provider?.id ?? null,
      direct: capability?.level === 'Direct',
      verifiedJobs: [],
      readJobIds: new Set(),
      posts: [],
      lastObservedAt: null
    });
  }
  for (const job of input.jobs) {
    if (job.state !== 'verified') continue;
    const id = matchJob(job, channels);
    if (id) byId.get(id)?.verifiedJobs.push(job);
  }
  const jobIndex = indexJobs(input.jobs);
  const unmatchedPosts: AnalyticsPostRow[] = [];
  let usesPlatformFallback = false;
  for (const post of input.posts as AnalyticsPostRow[]) {
    const match = matchPost(post, channels);
    const target = match.id ? byId.get(match.id) : undefined;
    if (!target) {
      unmatchedPosts.push(post);
      continue;
    }
    if (match.byPlatform) usesPlatformFallback = true;
    target.posts.push(post);
    const job = jobForPost(post, jobIndex);
    if (job && job.state === 'verified') target.readJobIds.add(job.id);
    const at = post.freshness.observedAt;
    if (target.lastObservedAt === null || at > target.lastObservedAt) target.lastObservedAt = at;
  }
  return { connections: Array.from(byId.values()), unmatchedPosts, usesPlatformFallback };
}

/** Verified jobs on these accounts that have no reading yet. */
export function unreadVerifiedCount(connections: ConnectionCoverage[]) {
  return connections.reduce(
    (n, c) => n + c.verifiedJobs.filter((job) => !c.readJobIds.has(job.id)).length,
    0
  );
}

/**
 * The page state, from real coverage only: no Direct account → unavailable; Direct but nothing
 * read → pending; some of the Direct accounts' verified posts read → partial; every one read → ready.
 */
export function coverageState(coverage: Coverage): CoverageState {
  const direct = coverage.connections.filter((c) => c.direct);
  if (direct.length === 0) return 'unavailable';
  const readings = direct.reduce((n, c) => n + c.posts.length, 0);
  if (readings === 0) return 'pending';
  return unreadVerifiedCount(direct) > 0 ? 'partial' : 'ready';
}

export function latestObservedAt(posts: AnalyticsPost[]): number | null {
  let latest: number | null = null;
  for (const post of posts) {
    const at = post.freshness.observedAt;
    if (latest === null || at > latest) latest = at;
  }
  return latest;
}

/**
 * Where to grant the analytics capability for a provider that offers it. The Channels page does
 * not act on `connect`/`capability` yet; the parameters are kept so the link starts working when it does.
 */
export function enableAnalyticsHref(providerId: string | null) {
  return providerId
    ? `/app/channels?connect=${encodeURIComponent(providerId)}&capability=analytics`
    : '/app/channels';
}

/** The honest sentence for a provider whose adapter does not offer analytics. Never "coming soon". */
export function notOfferedSentence(platform: string) {
  return `Not offered by ${platform}’s API for this app.`;
}

/** What PostRiff can say about one connection's analytics capability, from the matrix alone. */
export function capabilitySummary(connection: ConnectionCoverage) {
  if (!connection.providerOffersAnalytics) {
    return connection.evidence
      ? `${notOfferedSentence(connection.platform)} ${connection.evidence}`
      : notOfferedSentence(connection.platform);
  }
  if (connection.evidence) return connection.evidence;
  if (connection.direct)
    return 'Direct: PostRiff reads the provider’s official insights for posts it published.';
  return 'Analytics has not been granted for this account. It is a separate permission from publishing.';
}

/**
 * Metric keys in the API's own family order (attention before resonance), then anything the
 * families do not list, in the order the API sent them. Families only order; nothing is summed.
 */
export function orderMetricKeys(keys: string[], families: Record<string, string[]>) {
  const order = Object.values(families).flat();
  const rank = (key: string) => {
    const at = order.indexOf(key);
    return at === -1 ? order.length : at;
  };
  return keys.toSorted((a, b) => rank(a) - rank(b));
}

/** Native metric families order columns without summing providers. */
export function analyticsFamilies(data: Analytics | undefined): Record<string, string[]> {
  return data?.families ?? {};
}

/** A provider's display name for table groups: the post's platform when the API sent one, else the raw provider id. */
export function providerLabel(post: AnalyticsPost) {
  return post.platform || post.provider;
}
