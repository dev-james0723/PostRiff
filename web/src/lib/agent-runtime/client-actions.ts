/**
 * Safe client-side actions Rafii may perform on the current page.
 *
 * Nothing is inferred from arbitrary DOM controls. A product surface must explicitly opt a control in with
 * `data-rafii-action="<stable id>"`; the server only receives those ids through the bounded page outline.
 */
export type ClientActionReceipt = {
  actionId: string;
  status: 'verified' | 'sent' | 'blocked';
  label?: string;
  reason?: string;
};

const OWN_SURFACES = '#rafii-panel, [data-guide-overlay], [data-slot="tour-overlay"]';

function visible(element: HTMLElement): boolean {
  if (element.closest(OWN_SURFACES)) return false;
  if (element.hidden || element.getAttribute('aria-hidden') === 'true') return false;
  if ('disabled' in element && Boolean((element as HTMLButtonElement).disabled)) return false;
  if (element.getAttribute('aria-disabled') === 'true') return false;
  if (typeof element.checkVisibility === 'function') return element.checkVisibility({ checkVisibilityCSS: true });
  return element.getClientRects().length > 0;
}

function nameOf(element: HTMLElement): string {
  return (element.getAttribute('aria-label') || element.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 80);
}

async function observeChange(doc: Document, beforeUrl: string): Promise<boolean> {
  if (doc.defaultView?.location.href !== beforeUrl) return true;
  const root = doc.querySelector('main') ?? doc.body;
  if (!root || typeof MutationObserver === 'undefined') {
    await new Promise<void>((resolve) => setTimeout(resolve, 0));
    return doc.defaultView?.location.href !== beforeUrl;
  }
  return new Promise<boolean>((resolve) => {
    let done = false;
    const finish = (changed: boolean) => {
      if (done) return;
      done = true;
      observer.disconnect();
      clearTimeout(timer);
      resolve(changed || doc.defaultView?.location.href !== beforeUrl);
    };
    const observer = new MutationObserver(() => finish(true));
    observer.observe(root, { subtree: true, childList: true, attributes: true });
    const timer = setTimeout(() => finish(false), 900);
  });
}

/**
 * Activate exactly one visible, enabled, explicitly opted-in control and observe whether the page changes.
 * A missing, duplicate or disabled target fails closed.
 */
export async function activateClientControl(actionId: string, doc: Document = document): Promise<ClientActionReceipt> {
  if (!actionId || actionId.length > 80) return { actionId, status: 'blocked', reason: 'invalid_action' };
  const matches = Array.from(doc.querySelectorAll<HTMLElement>('[data-rafii-action]')).filter(
    (element) => element.getAttribute('data-rafii-action') === actionId && visible(element)
  );
  if (matches.length !== 1) {
    return { actionId, status: 'blocked', reason: matches.length === 0 ? 'not_available' : 'ambiguous' };
  }

  const element = matches[0];
  const role = element.getAttribute('role');
  const tag = element.tagName;
  if (!(tag === 'BUTTON' || tag === 'A' || role === 'button' || role === 'tab' || role === 'link')) {
    return { actionId, status: 'blocked', label: nameOf(element), reason: 'not_activatable' };
  }

  const beforeUrl = doc.defaultView?.location.href ?? '';
  const label = nameOf(element);
  element.click();
  const changed = await observeChange(doc, beforeUrl);
  const receipt: ClientActionReceipt = { actionId, label, status: changed ? 'verified' : 'sent' };
  try {
    doc.defaultView?.dispatchEvent(new CustomEvent('rafii:client-action', { detail: receipt }));
  } catch {
    // Telemetry is additive; the action itself already ran.
  }
  return receipt;
}
