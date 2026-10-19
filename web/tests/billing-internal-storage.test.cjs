/**
 * Internal Ops /usage returns nullable plan allowances. Render the real Allowances
 * component so a missing allowance cannot crash the complete Usage & plan page.
 * Only presentation primitives are stubbed; entitlement readings use production code.
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { createLoader, SRC, pkg } = require('./agent-ui-journeys/_load.cjs');
const React = pkg('react');
const { renderToStaticMarkup } = pkg('react-dom/server');

const box = ({ children }) => React.createElement('div', null, children);
const loader = createLoader({ stubs: {
  [path.join(SRC, 'components/rafii')]: { Surface: box, InfoTip: () => null },
  [path.join(SRC, 'components/icons')]: { Icons: { warning: () => null } },
  [path.join(SRC, 'components/motion/number-ticker')]: { NumberTicker: ({ value }) => React.createElement('span', null, String(value)) },
  [path.join(SRC, 'components/ui/button')]: { Button: box },
  [path.join(SRC, 'components/ui/skeleton')]: { Skeleton: () => React.createElement('span', null, 'Loading') },
  [path.join(SRC, 'lib/api/client')]: { usd: (micro) => String(micro) }
} });
const { Allowances } = loader.load('src/features/billing/allowances.tsx');

function renderStorage(storageMb, unlimited = false) {
  const entitlement = {
    planTermsId: unlimited ? null : 'existing-plan', writingBatchesRemaining: unlimited ? null : 100,
    mediaCreditsRemaining: unlimited ? null : 5, connectedAccounts: unlimited ? null : 3,
    members: unlimited ? null : 2, storageMb, resetsAt: null, source: unlimited ? 'internal' : 'subscription',
    version: 1, ...(unlimited ? { unlimited: true } : {})
  };
  const usage = { entitlement, credits: null, subscription: null, budget: null, overage: 'stop',
    ledger: [], planTerms: [], lifecycle: { status: unlimited ? 'internal' : 'active', canPublish: true } };
  return renderToStaticMarkup(React.createElement(Allowances, {
    usage, channels: { data: { channels: [], providers: [] }, isPending: false, isError: false },
    members: { data: { members: [] }, isPending: false, isError: false }, isOwner: true, now: 1792416000
  }));
}

test('existing internal entitlement with null storage renders without inventing a customer quota', () => {
  const html = renderStorage(null, true);
  assert.match(html, /Storage<\/span><span[^>]*>No plan limit<\/span>/);
  assert.doesNotMatch(html, /Infinity MB|NaN MB|null MB|0 MB/);
});

test('finite customer storage keeps its existing amount and unit', () => {
  assert.match(renderStorage(1200), /Storage<\/span><span[^>]*>1,200 MB<\/span>/);
});

test('an actual zero storage allowance remains zero', () => {
  assert.match(renderStorage(0), /Storage<\/span><span[^>]*>0 MB<\/span>/);
});

for (const [label, value] of [['null', null], ['missing', undefined], ['negative', -1], ['NaN', NaN], ['infinite', Infinity], ['string', '1024']]) {
  test(`unknown or malformed storage is unavailable, never a fabricated quota: ${label}`, () => {
    const html = renderStorage(value);
    assert.match(html, /Storage<\/span><span[^>]*>Unavailable<\/span>/);
    assert.doesNotMatch(html, /Storage<\/span><span[^>]*>0 MB<\/span>/);
  });
}
