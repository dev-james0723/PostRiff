'use client';

import { useEffect, useState } from 'react';
import { AnimatedBadge, type AnimatedBadgeStatus } from '@/components/motion/animated-badge';
import { CollectionRow } from '@/components/rafii';

type State = 'checking' | 'ok' | 'degraded' | 'down';

interface Component {
  name: string;
  state: State;
  detail: string;
}

/**
 * One live check of /api/health rendered as quiet collection rows (DNA §13.3, §20.1). The badge
 * is the row's state slot: `checking` is a real in-flight request, and the result badge names the
 * operation's actual outcome; nothing is claimed before the response arrives.
 */
export function StatusPanel() {
  const [components, setComponents] = useState<Component[]>([
    { name: 'Web app', state: 'ok', detail: 'You are reading it.' },
    { name: 'API', state: 'checking', detail: 'Checking…' },
    { name: 'Authentication', state: 'checking', detail: 'Checking…' },
    { name: 'Publishing workers', state: 'checking', detail: 'Checking…' }
  ]);
  const [checkedAt, setCheckedAt] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function check() {
      try {
        const res = await fetch('/api/health', { cache: 'no-store' });
        const body = (await res.json()) as { status?: string; configured?: boolean };
        if (cancelled) return;
        const ok = res.ok && body.status === 'ok';
        setComponents([
          { name: 'Web app', state: 'ok', detail: 'You are reading it.' },
          { name: 'API', state: ok ? 'ok' : 'degraded', detail: ok ? 'Responding.' : `Responded with ${res.status}.` },
          { name: 'Authentication', state: ok ? (body.configured ? 'ok' : 'degraded') : 'down', detail: body.configured ? 'Configured.' : 'Not configured on this deployment.' },
          { name: 'Publishing workers', state: ok ? 'ok' : 'down', detail: ok ? 'Scheduled every minute.' : 'Unknown while the API is unreachable.' }
        ]);
      } catch {
        if (cancelled) return;
        setComponents((current) => current.map((c) => (c.name === 'Web app' ? c : { ...c, state: 'down', detail: 'Unreachable from this page.' })));
      } finally {
        if (!cancelled) setCheckedAt(new Date().toLocaleTimeString());
      }
    }
    void check();
    return () => {
      cancelled = true;
    };
  }, []);

  // `checking` is a real in-flight request, so it gets the spinner; the badge rolls to the result when the check returns.
  const tone: Record<State, AnimatedBadgeStatus> = { ok: 'success', checking: 'loading', degraded: 'warning', down: 'danger' };
  const label: Record<State, string> = { ok: 'Operational', checking: 'Checking', degraded: 'Degraded', down: 'Unavailable' };

  return (
    <div className='max-w-2xl'>
      <ul className='flex flex-col gap-1.5'>
        {components.map((component) => (
          <CollectionRow
            key={component.name}
            as='li'
            title={component.name}
            meta={component.detail}
            state={
              <AnimatedBadge status={tone[component.state]} size='sm'>
                {label[component.state]}
              </AnimatedBadge>
            }
          />
        ))}
      </ul>
      <p role='status' aria-live='polite' className='text-muted-foreground mt-3 text-xs'>
        {checkedAt ? `Checked at ${checkedAt} from your browser.` : 'Checking…'}
      </p>
    </div>
  );
}
