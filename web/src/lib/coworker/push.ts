/**
 * Browser Web Push for Rafii (coworker spec §18): explicit opt-in only. Nothing here asks for permission on its
 * own; `subscribe` is called from a click handler, which is the only place `Notification.requestPermission()` runs.
 * The service worker (`/sw.js`) shows the minimal payload and deep-links inside the app; it caches nothing.
 */
import type { PushSubscriptionBody } from './types';
import { pushSupport, urlBase64ToUint8Array, type PushSupport } from './push-keys';

export { urlBase64ToUint8Array } from './push-keys';
export type { PushSupport } from './push-keys';

export const SERVICE_WORKER_URL = '/sw.js';

export function isSupported(): boolean {
  return detectPushSupport() === 'supported';
}

/** Read the browser's capabilities (client only; returns 'unsupported' during server rendering). */
export function detectPushSupport(): PushSupport {
  if (typeof window === 'undefined' || typeof navigator === 'undefined') return 'unsupported';
  const ua = navigator.userAgent || '';
  const isIOS = /iPad|iPhone|iPod/.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1);
  const standalone = window.matchMedia?.('(display-mode: standalone)').matches || (navigator as Navigator & { standalone?: boolean }).standalone === true;
  return pushSupport({
    hasServiceWorker: 'serviceWorker' in navigator,
    hasPushManager: 'PushManager' in window,
    hasNotification: 'Notification' in window,
    isIOS,
    isStandalone: Boolean(standalone),
    secureContext: window.isSecureContext !== false
  });
}

/** The current permission without asking for one. */
export function permissionState(): NotificationPermission | 'unsupported' {
  if (typeof window === 'undefined' || !('Notification' in window)) return 'unsupported';
  return Notification.permission;
}

export async function register(): Promise<ServiceWorkerRegistration> {
  const registration = await navigator.serviceWorker.register(SERVICE_WORKER_URL, { scope: '/', updateViaCache: 'none' });
  await navigator.serviceWorker.ready;
  return registration;
}

/** This browser's existing subscription, if any (never prompts). */
export async function currentSubscription(): Promise<PushSubscription | null> {
  if (!isSupported()) return null;
  const registration = await navigator.serviceWorker.getRegistration('/');
  return registration ? registration.pushManager.getSubscription() : null;
}

export class PushPermissionError extends Error {
  permission: NotificationPermission;
  constructor(permission: NotificationPermission) {
    super(permission === 'denied' ? 'Notifications are blocked for this site. Allow them in your browser settings, then try again.' : 'Notifications were not allowed.');
    this.name = 'PushPermissionError';
    this.permission = permission;
  }
}

/**
 * Ask for permission (must run inside a user gesture), register the worker and subscribe with the server's VAPID
 * key. Returns the JSON body the server stores. A previous subscription made with another key is replaced.
 */
export async function subscribe(vapidPublicKey: string): Promise<{ subscription: PushSubscription; body: PushSubscriptionBody }> {
  const permission = Notification.permission === 'granted' ? 'granted' : await Notification.requestPermission();
  if (permission !== 'granted') throw new PushPermissionError(permission);
  const registration = await register();
  const key = urlBase64ToUint8Array(vapidPublicKey);
  let subscription = await registration.pushManager.getSubscription();
  if (subscription && !sameKey(subscription.options.applicationServerKey, key)) {
    await subscription.unsubscribe();
    subscription = null;
  }
  subscription ??= await registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: key });
  const json = subscription.toJSON();
  if (!json.endpoint || !json.keys?.p256dh || !json.keys?.auth) throw new Error('The browser returned an incomplete push subscription.');
  return { subscription, body: { endpoint: json.endpoint, expirationTime: json.expirationTime ?? null, keys: { p256dh: json.keys.p256dh, auth: json.keys.auth } } };
}

/** Unsubscribe this browser; returns the endpoint so the server can revoke it too. */
export async function unsubscribe(): Promise<string | null> {
  const subscription = await currentSubscription();
  if (!subscription) return null;
  const endpoint = subscription.endpoint;
  await subscription.unsubscribe();
  return endpoint;
}

function sameKey(current: ArrayBuffer | null | undefined, wanted: Uint8Array): boolean {
  if (!current) return false;
  const bytes = new Uint8Array(current);
  if (bytes.length !== wanted.length) return false;
  return bytes.every((value, index) => value === wanted[index]);
}
