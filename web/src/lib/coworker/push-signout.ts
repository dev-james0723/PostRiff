/**
 * Sign-out: stop this browser receiving the signed-out person's push notifications. Once the browser drops its
 * subscription, the push service answers the server's next send with 404/410, and the delivery worker revokes the
 * stored subscription (notifications/delivery.py). This never registers the service worker and never throws, and it
 * gives up after a short wait, so sign-out is never held up.
 */
export async function forgetPushOnSignOut(timeoutMs = 3000): Promise<boolean> {
  if (typeof window === 'undefined' || typeof navigator === 'undefined' || !('serviceWorker' in navigator)) return false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const timeout = new Promise<boolean>((resolve) => {
    timer = setTimeout(() => resolve(false), timeoutMs);
  });
  const work = (async () => {
    const registration = await navigator.serviceWorker.getRegistration('/');
    const subscription = await registration?.pushManager?.getSubscription();
    if (!subscription) return false;
    return await subscription.unsubscribe();
  })();
  try {
    return await Promise.race([work, timeout]);
  } catch {
    return false;
  } finally {
    clearTimeout(timer);
  }
}
