'use strict';
// Known cancelled speculative RSC requests when a hard document navigation
// replaces Next.js App Router's document. See microsoft/playwright#42823.
// Narrow: WebKit only; localhost app path; genuine RSC key; near a hard navigation.
// This is NOT a generic CORS, request failure or JavaScript-error suppression.
function isWebKitNavigationPrefetchAbort(engine, error) {
  // WebKit's Error.name is sometimes the truncated first URL phrase of its
  // JS message, as confirmed by the authentic G5 diagnostic trace (45 events).
  // This is an EXACT additional name case, not generic error suppression.
  if (engine !== 'webkit' || !error ||
      !['Error', 'TypeError', 'Fetch API cannot load http'].includes(error.name)) return false;
  if (error.nearHardNavigation !== true || typeof error.message !== 'string') return false;
  const s = error.message.trim();
  return /(?:https?:\/\/|\/)127\.0\.0\.1:4448\/app(?:[/?]|$)/.test(s)
    && /[?&]_rsc=[A-Za-z0-9_-]+/.test(s)
    && /due to access control checks\.$/.test(s)
    && s.length < 1024;
}
module.exports = { isWebKitNavigationPrefetchAbort };
