/**
 * A reconnect leaves the app for the provider and comes back through the public callback,
 * so nothing in the URL survives the trip. The expected account is parked in
 * sessionStorage for the return page, which compares the connection the provider
 * returned with the one that needed reconnecting. Nothing sensitive is stored: a
 * connection id, a display handle and the transaction id.
 */

const KEY = 'postriff.channels.expected-reconnect';

export interface ExpectedReconnect {
  channelId: string;
  account: string;
  transactionId: string;
}

export function rememberExpectedReconnect(expect: ExpectedReconnect) {
  try {
    window.sessionStorage.setItem(KEY, JSON.stringify(expect));
  } catch {
    // Private mode or blocked storage: the return page simply skips the comparison.
  }
}

/** Reads and clears the expectation, so a later, unrelated connection is never compared against it. */
export function takeExpectedReconnect(): ExpectedReconnect | null {
  try {
    const raw = window.sessionStorage.getItem(KEY);
    window.sessionStorage.removeItem(KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<ExpectedReconnect>;
    if (typeof parsed.channelId !== 'string' || typeof parsed.account !== 'string') return null;
    return { channelId: parsed.channelId, account: parsed.account, transactionId: String(parsed.transactionId ?? '') };
  } catch {
    return null;
  }
}
