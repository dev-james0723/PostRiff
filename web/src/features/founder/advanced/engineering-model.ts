/**
 * Advanced → Engineering (CONTRACTS §8.D), pure reading only. Evidence rows are `GET /engineering`
 * (`rafii_control.engineering_evidence`: attested exact-SHA checks, deployments, errors); the required-check manifest
 * for a SHA comes from `GET /engineering/checks` (an operator-admitted capture, or in hosted environments the CI
 * collector's 'ci_attested' manifest, migration 071). `engineeringState` is `intelligence.engineering_state` line for
 * line and `engineeringVerdict` is `QueryService.engineering`'s verdict, so the page never shows a green the server's
 * rule would not: 'checks_passed' needs the count from the newest trusted manifest for one exact 40-hex SHA and exactly
 * that many required checks, all attested and concluded 'success'. Everything else is 'suspected'. Neither state ever
 * means merged, deployed or fixed.
 */

export const EXACT_SHA = /^[0-9a-f]{40}$/;

/** `intelligence.TRUSTED_MANIFEST_PROVENANCE`: synthetic and unadmitted captures never say how many checks are required. */
export const TRUSTED_MANIFEST_PROVENANCE: readonly string[] = ['admitted_operational', 'ci_attested'];

export interface EngineeringEvidenceRow {
  id: string;
  kind: string;
  provider: string;
  external_id: string | null;
  exact_sha: string | null;
  state: string;
  conclusion: string | null;
  failure_class: string | null;
  attested: boolean;
  required: boolean;
  observed_at: string;
  /** Set by the server when it downgraded a stage claim it cannot qualify (the row's `state` is then 'suspected'). */
  observed_stage?: string;
  qualification?: string;
}

export interface CheckSnapshot {
  id: string;
  exactSha: string;
  provenance: string;
  observedAt: string;
  /** The server's word on whether this manifest's count may be used (trusted provenance and a payload it re-derived). */
  trusted?: boolean;
  qualification?: { requiredCount?: number | null; observedRequiredCount?: number; qualification?: string } | null;
}

export type EngineeringState = 'checks_passed' | 'suspected';

/** `intelligence.engineering_state`: no branch-name, empty, skipped, stale or untrusted green. */
export function engineeringState(rows: readonly Partial<EngineeringEvidenceRow>[], sha: string | null | undefined, requiredCount = 0): EngineeringState {
  if (typeof sha !== 'string' || !EXACT_SHA.test(sha) || !(requiredCount > 0)) return 'suspected';
  const checks = rows.filter((row) => row.kind === 'check' && Boolean(row.required));
  if (checks.length !== requiredCount) return 'suspected';
  return checks.every((row) => row.exact_sha === sha && row.attested === true && row.conclusion === 'success') ? 'checks_passed' : 'suspected';
}

export type VerdictReason = 'no_required_checks' | 'no_exact_sha' | 'manifest_unavailable' | 'manifest_missing' | 'count_mismatch' | 'unattested' | 'not_green' | 'all_green';

export interface EngineeringVerdict {
  state: EngineeringState;
  reason: VerdictReason;
  /** The SHA judged: the one the newest required check ran on. */
  sha: string | null;
  /** How many checks the manifest for that SHA requires; null when no manifest names it. */
  required: number | null;
  /** Required check rows observed on that SHA. */
  observed: number;
  unattested: number;
  notGreen: number;
  manifestProvenance: string | null;
}

function newestFirst<T>(rows: readonly T[], at: (row: T) => string | null | undefined): T[] {
  const time = (row: T) => Date.parse(at(row) ?? '') || 0;
  return rows.toSorted((a, b) => time(b) - time(a));
}

/**
 * The overall state for the newest exact SHA a required check ran on. `snapshots` is null when the manifest could not
 * be read; a missing or unreadable manifest leaves the count unconfirmed, so the state stays 'suspected'.
 */
export function engineeringVerdict(rows: readonly EngineeringEvidenceRow[], snapshots: readonly CheckSnapshot[] | null): EngineeringVerdict {
  const base = { sha: null, required: null, observed: 0, unattested: 0, notGreen: 0, manifestProvenance: null };
  const required = newestFirst(
    rows.filter((row) => row.kind === 'check' && row.required === true),
    (row) => row.observed_at
  );
  if (required.length === 0) return { ...base, state: 'suspected', reason: 'no_required_checks' };
  const sha = required[0].exact_sha;
  if (typeof sha !== 'string' || !EXACT_SHA.test(sha)) return { ...base, state: 'suspected', reason: 'no_exact_sha' };
  const onSha = required.filter((row) => row.exact_sha === sha);
  const unattested = onSha.filter((row) => row.attested !== true).length;
  const notGreen = onSha.filter((row) => row.conclusion !== 'success').length;
  // The newest manifest of a trusted provenance speaks for the SHA; one the server could not re-derive (trusted: false)
  // supplies no count rather than letting an older one outvote it (`QueryService.manifest_for` / `manifest_count`).
  const trusted = snapshots === null ? [] : snapshots.filter((snapshot) => snapshot.exactSha === sha && TRUSTED_MANIFEST_PROVENANCE.includes(snapshot.provenance));
  const manifest = snapshots === null ? null : (newestFirst(trusted, (snapshot) => snapshot.observedAt)[0] ?? null);
  const count = manifest?.trusted === false ? undefined : manifest?.qualification?.requiredCount;
  const requiredCount = typeof count === 'number' && Number.isInteger(count) && count > 0 ? count : null;
  const reason: VerdictReason =
    snapshots === null
      ? 'manifest_unavailable'
      : requiredCount === null
        ? 'manifest_missing'
        : onSha.length !== requiredCount
          ? 'count_mismatch'
          : unattested > 0
            ? 'unattested'
            : notGreen > 0
              ? 'not_green'
              : 'all_green';
  return {
    state: engineeringState(onSha, sha, requiredCount ?? 0),
    reason,
    sha,
    required: requiredCount,
    observed: onSha.length,
    unattested,
    notGreen,
    manifestProvenance: manifest?.provenance ?? null
  };
}

export const STATE_LABELS: Record<EngineeringState, string> = { checks_passed: 'Checks passed', suspected: 'Suspected' };
export const KIND_LABELS: Record<string, string> = { check: 'Check', deployment: 'Deployment', error: 'Error', log: 'Log', security: 'Security' }; // copy-audit: allow — founder-only engineering evidence kind
export const PROVIDER_LABELS: Record<string, string> = { github: 'GitHub', vercel: 'Vercel', sentry: 'Sentry', local: 'Local' };
export const CONCLUSION_TONE: Record<string, 'success' | 'danger' | 'warning' | 'neutral'> = {
  success: 'success',
  failure: 'danger',
  timed_out: 'danger',
  action_required: 'danger',
  cancelled: 'warning',
  skipped: 'neutral',
  neutral: 'neutral',
  unknown: 'neutral'
};

export function shortSha(sha: string | null | undefined): string | null {
  return typeof sha === 'string' && EXACT_SHA.test(sha) ? sha.slice(0, 7) : null;
}

export function shortRef(value: string | null | undefined, max = 28): string | null {
  if (typeof value !== 'string' || value.length === 0) return null;
  return value.length > max ? `${value.slice(0, max - 1)}…` : value;
}

function checks(n: number): string {
  return `${n} required check${n === 1 ? '' : 's'}`;
}

/** One sentence for the verdict; every number it names is a count the page saw. */
export function verdictText(verdict: EngineeringVerdict): string {
  const sha = shortSha(verdict.sha) ?? 'this SHA';
  switch (verdict.reason) {
    case 'no_required_checks':
      return 'No required check is in the evidence yet, so nothing can be called green.';
    case 'no_exact_sha':
      return 'The newest required check carries no exact SHA; a branch name never counts.';
    case 'manifest_unavailable':
      return `${checks(verdict.observed)} on ${sha}, but the required-check manifest could not be read, so completeness is unconfirmed.`;
    case 'manifest_missing':
      return `${checks(verdict.observed)} on ${sha}, but no trusted required-check manifest for this SHA says how many are required.`;
    case 'count_mismatch':
      return `${checks(verdict.observed)} observed on ${sha}; its manifest requires ${verdict.required ?? 'an unknown number'}.`;
    case 'unattested':
      return `${verdict.unattested} of ${checks(verdict.observed)} on ${sha} ${verdict.unattested === 1 ? 'is' : 'are'} not attested.`;
    case 'not_green':
      return `${verdict.notGreen} of ${checks(verdict.observed)} on ${sha} did not conclude success.`;
    case 'all_green':
      return verdict.observed === 1
        ? `The 1 required check on ${sha} is attested green, as its manifest requires.`
        : `All ${checks(verdict.observed)} on ${sha} are attested green, as its manifest requires.`;
  }
}
