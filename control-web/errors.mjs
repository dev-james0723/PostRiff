/** Fixed public messages only; never display a provider-supplied message/body. */
export function controlError(status, code) {
  if (status === 429 && code === 'RATE_LIMITED') return 'Identity source is rate limited. Wait before retrying.';
  if (status === 503) return 'Identity source is unavailable. Retry when it recovers.';
  if (status === 401) return 'Authentication could not be verified. Sign in again.';
  if (status === 403) return 'This operator does not have permission for this view.';
  return 'Control request could not be completed. Review its evidence and retry.';
}
