'use client';

import { useCallback, useEffect, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { Icons } from '@/components/icons';
import { StateMessage } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { Band } from '@/features/workspace/rafii-parts';
import { errorMessage } from '@/lib/coworker/api';
import { coworkerKeys, useCoworkerApi, usePushDevices } from '@/lib/coworker/hooks';
import { currentSubscription, detectPushSupport, permissionState, subscribe, unsubscribe, type PushSupport } from '@/lib/coworker/push';
import { isVapidKey } from '@/lib/coworker/push-keys';
import { relativeTime } from '@/lib/time';

type Phase = 'checking' | 'off' | 'on' | 'busy';

/**
 * Explicit Web Push opt-in (coworker spec §18). The browser's permission prompt appears only after a click on
 * “Turn on push notifications”; nothing asks on page load. iPhone and iPad get the Home Screen hint instead of a
 * button that cannot work in a Safari tab. Lock-screen notifications carry a short title and a link, never draft
 * text or private messages.
 */
export function PushOptIn({ available, vapidPublicKey }: { available: boolean; vapidPublicKey: string | null }) {
  const { api, w } = useCoworkerApi();
  const client = useQueryClient();
  const devices = usePushDevices(available);
  const [support, setSupport] = useState<PushSupport | null>(null);
  const [permission, setPermission] = useState<NotificationPermission | 'unsupported'>('default');
  const [phase, setPhase] = useState<Phase>('checking');
  const [endpoint, setEndpoint] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    const detected = detectPushSupport();
    setSupport(detected);
    setPermission(permissionState());
    if (detected !== 'supported') return setPhase('off');
    try {
      const subscription = await currentSubscription();
      setEndpoint(subscription?.endpoint ?? null);
      setPhase(subscription ? 'on' : 'off');
    } catch {
      setPhase('off');
    }
  }, []);

  useEffect(() => {
    void refresh();
    if (typeof navigator === 'undefined' || !('serviceWorker' in navigator)) return;
    // The worker re-subscribed on its own (pushsubscriptionchange): re-read and re-register the new endpoint.
    const onMessage = (event: MessageEvent) => {
      if (event.data?.type === 'rafii:push-subscription-changed') void refresh();
    };
    navigator.serviceWorker.addEventListener('message', onMessage);
    return () => navigator.serviceWorker.removeEventListener('message', onMessage);
  }, [refresh]);

  async function turnOn() {
    if (!vapidPublicKey || !isVapidKey(vapidPublicKey)) return toast.error('Push notifications aren’t set up correctly yet. Try again later.');
    setPhase('busy');
    try {
      const { body } = await subscribe(vapidPublicKey);
      const saved = await api.subscribePush(w, body);
      if (!saved.verified || !saved.active) {
        toast.warning('This browser subscribed, but Rafii could not confirm it on the server. Try again.');
      } else {
        toast.success('Push notifications are on for this browser.');
      }
      setEndpoint(body.endpoint);
      setPhase('on');
    } catch (err) {
      setPermission(permissionState());
      setPhase('off');
      toast.error(errorMessage(err, 'Push notifications could not be turned on.'));
    } finally {
      void client.invalidateQueries({ queryKey: coworkerKeys.pushDevices(w) });
      void client.invalidateQueries({ queryKey: coworkerKeys.preferences(w) });
    }
  }

  async function turnOff() {
    setPhase('busy');
    try {
      const gone = (await unsubscribe()) ?? endpoint;
      if (gone) {
        const result = await api.unsubscribePushEndpoint(w, gone);
        if (!result.verified) toast.warning('This browser stopped, but Rafii could not confirm the server removed it. Remove it from the list below.');
        else toast.success('Push notifications are off for this browser.');
      }
      setEndpoint(null);
      setPhase('off');
    } catch (err) {
      toast.error(errorMessage(err));
      void refresh();
    } finally {
      void client.invalidateQueries({ queryKey: coworkerKeys.pushDevices(w) });
    }
  }

  async function revoke(id: string) {
    try {
      const result = await api.revokePushDevice(w, id);
      if (!result.verified) toast.warning('Rafii could not confirm the device was removed. Refresh and try again.');
      else toast.success('Removed. That device no longer receives push notifications.');
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      void client.invalidateQueries({ queryKey: coworkerKeys.pushDevices(w) });
    }
  }

  if (!available) {
    return <StateMessage kind='unsupported' layout='inline' title='Push notifications aren’t available yet.' description='In-app notifications still work.' />;
  }

  const now = Date.now() / 1000;
  const list = devices.data?.devices ?? [];

  return (
    <div className='flex flex-col gap-3'>
      <Band className='gap-3 sm:flex-row sm:items-center sm:justify-between' data-push-support={support ?? 'checking'} data-push-permission={permission}>
        <div className='flex min-w-0 flex-col gap-1'>
          <p className='text-foreground text-sm font-medium'>This browser</p>
          <p className='text-muted-foreground text-sm leading-relaxed' aria-live='polite'>
            {support === null || phase === 'checking'
              ? 'Checking this browser…'
              : support === 'ios-install'
                ? 'On iPhone and iPad, push works only from the Home Screen app: tap Share, then “Add to Home Screen”, open Rafii from there and turn push on.'
                : support === 'unsupported'
                  ? 'This browser can’t receive push notifications. In-app notifications still work.'
                  : permission === 'denied'
                    ? 'Notifications are blocked for this site. Allow them in your browser’s site settings, then come back.'
                    : phase === 'on'
                      ? 'On. Lock-screen notifications show a short title and open the right page; never draft text or private messages.'
                      : 'Off. Turn it on to hear about approvals, failed posts and a ready week even when Rafii isn’t open.'}
          </p>
        </div>
        {support === 'supported' && permission !== 'denied' && phase !== 'checking' && (
          phase === 'on' ? (
            <Button variant='glass' size='control' onClick={() => void turnOff()}>
              Turn off on this browser
            </Button>
          ) : (
            <Button variant='action' size='control' disabled={phase === 'busy'} onClick={() => void turnOn()} data-testid='push-opt-in'>
              <Icons.notification className='size-4' aria-hidden />
              {phase === 'busy' ? 'Turning on…' : 'Turn on push notifications'}
            </Button>
          )
        )}
      </Band>

      <div className='flex flex-col gap-1'>
        <p className='text-foreground text-sm font-medium'>Devices receiving push</p>
        {devices.isPending ? (
          <p className='text-muted-foreground text-xs'>Loading devices…</p>
        ) : list.length === 0 ? (
          <p className='text-muted-foreground text-xs'>None yet.</p>
        ) : (
          <ul className='flex flex-col gap-1'>
            {list.map((device) => (
              <li key={device.id} className='rafii-quiet flex min-h-12 flex-col gap-2 rounded-[var(--rafii-radius-control)] px-3 py-2 sm:flex-row sm:items-center sm:justify-between'>
                <span className='min-w-0'>
                  <span className='text-foreground block text-sm'>{device.label || 'A browser'}</span>
                  <span className='text-muted-foreground block text-xs'>
                    Added {relativeTime(device.createdAt, now)} · {device.lastSuccessAt ? `last delivered ${relativeTime(device.lastSuccessAt, now)}` : 'nothing delivered yet'}
                  </span>
                </span>
                <Button variant='quiet' size='control' onClick={() => void revoke(device.id)} aria-label={`Remove ${device.label || 'this browser'} from push notifications`}>
                  Remove
                </Button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
