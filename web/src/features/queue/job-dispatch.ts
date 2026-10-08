import type { Job, WorkerBinding } from '@/lib/api/types';

const pendingMessage = 'Approved preview post; choose Publish approved post when due.';
const notSubmittedMessage = 'Live provider transport is not configured; nothing was submitted';
const sameBinding = (a?: WorkerBinding | null, b?: WorkerBinding | null) =>
  (!a && !b) || Boolean(a && b && a.environment === b.environment && a.origin === b.origin);
const noProviderEffect = (job: Job) => !job.providerReference && !job.container && !job.progress
  && !job.providerUpload && !job.providerAssets && !job.providerThread && !job.url && !job.verification;

/** These holds contain definitive no-submission evidence. Every check is repeated by the server. */
export function recoverablePreviewHold(job: Job, workerBinding?: WorkerBinding | null) {
  if (workerBinding?.environment !== 'preview' || job.state !== 'held' || !noProviderEffect(job) || job.cancelRequested) return false;
  const event = job.events.at(-1);
  if (job.previewDispatchPending && sameBinding(job.manifest.workerBinding, workerBinding)
    && sameBinding(job.workerBinding ?? job.manifest.workerBinding, workerBinding)
    && job.attempts.length === 0 && event?.state === 'held' && event.message === pendingMessage) return true;
  const attempt = job.attempts[0];
  return !job.workerBinding && !job.manifest.workerBinding && job.resultSchema === 'postriff.result.v1'
    && job.providerConfirmed === notSubmittedMessage && event?.state === 'held' && event.message === notSubmittedMessage
    && job.attempts.length === 1 && attempt.number === 1 && Number.isFinite(attempt.startedAt)
    && typeof attempt.endedAt === 'number' && Number.isFinite(attempt.endedAt) && attempt.endedAt >= attempt.startedAt;
}

/** Only a due exact approval can run. Known receipts and unknown outcomes never create again. */
export function canPublishApprovedJob(job: Job, nowSeconds: number, allowed: boolean, workerBinding?: WorkerBinding | null) {
  const first = (job.state === 'scheduled' || job.state === 'approved') && job.attempts.length === 0
    && sameBinding(job.workerBinding ?? job.manifest.workerBinding, workerBinding)
    && (!job.workerBinding || !job.manifest.workerBinding || sameBinding(job.workerBinding, job.manifest.workerBinding));
  return allowed && (first || recoverablePreviewHold(job, workerBinding))
    && /^[a-f0-9]{64}$/.test(job.approvalDigest ?? '')
    && typeof job.nextAt === 'number' && Number.isFinite(job.nextAt) && job.nextAt <= nowSeconds
    && Number.isFinite(job.manifest.expiresAt) && job.manifest.expiresAt > nowSeconds
    && (job.leaseUntil ?? 0) <= nowSeconds
    && !job.cancelRequested && noProviderEffect(job);
}
