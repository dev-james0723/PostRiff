'use strict';
// Known cancelled speculative RSC requests when a hard document navigation
// replaces Next.js App Router's document. See microsoft/playwright#42823.
// Narrow: WebKit only; localhost app path; genuine RSC key; near a hard navigation.
// This is NOT a generic CORS, request failure or JavaScript-error suppression.
function isWebKitNavigationPrefetchAbort(engine, error) {
  if (engine !== 'webkit' || !error || error.name !== 'Error' && error.name !== 'TypeError') return false;
  if (error.nearHardNavigation !== true || typeof error.message !== 'string') return false;
  const s = error.message.trim();
  return /(?:https?:\/\/|\/)127\.0\.0\.1:4448\/app(?:[/?]|$)/.test(s)
    && /[?&]_rsc=[A-Za-z0-9_-]+/.test(s)
    && /due to access control checks\.$/.test(s)
    && s.length < 1024;
}
module.exports = { isWebKitNavigationPrefetchAbort };
