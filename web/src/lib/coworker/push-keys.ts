/**
 * Pure helpers for Web Push (no DOM access, no imports) so node's test runner can load them directly.
 * The browser-facing wrapper is `./push.ts`.
 */

/** A VAPID public key (base64url, unpadded) as the `applicationServerKey` bytes `PushManager.subscribe` wants. */
export function urlBase64ToUint8Array(base64String: string): Uint8Array<ArrayBuffer> {
  if (typeof base64String !== 'string' || !/^[A-Za-z0-9_-]+={0,2}$/.test(base64String)) throw new Error('The push key is not base64url.');
  const padding = '='.repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
  const raw = atob(base64);
  const output = new Uint8Array(new ArrayBuffer(raw.length));
  for (let i = 0; i < raw.length; i += 1) output[i] = raw.charCodeAt(i);
  return output;
}

/** An uncompressed P-256 public key is 65 bytes starting with 0x04; anything else is not a VAPID key. */
export function isVapidKey(base64String: string | null | undefined): boolean {
  if (!base64String) return false;
  try {
    const bytes = urlBase64ToUint8Array(base64String);
    return bytes.length === 65 && bytes[0] === 0x04;
  } catch {
    return false;
  }
}

export type PushSupport = 'supported' | 'ios-install' | 'unsupported';

export interface PushEnvironment {
  hasServiceWorker: boolean;
  hasPushManager: boolean;
  hasNotification: boolean;
  /** iPhone / iPad (including iPadOS reporting as a Mac with touch). */
  isIOS: boolean;
  /** Launched from the home screen (`display-mode: standalone` or `navigator.standalone`). */
  isStandalone: boolean;
  secureContext: boolean;
}

/**
 * What the push opt-in can offer here. iOS and iPadOS deliver web push only to a site installed to the home
 * screen (16.4+), so a Safari tab there gets the install hint instead of a button that cannot work.
 */
export function pushSupport(env: PushEnvironment): PushSupport {
  if (!env.secureContext) return 'unsupported';
  if (env.hasServiceWorker && env.hasPushManager && env.hasNotification) return 'supported';
  if (env.isIOS && !env.isStandalone) return 'ios-install';
  return 'unsupported';
}
