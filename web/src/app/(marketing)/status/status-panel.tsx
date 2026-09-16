'use client';

import { useEffect, useState } from 'react';
import { Badge } from '@/components/ui/badge';

type State = 'checking' | 'ok' | 'degraded' | 'down';

interface Component {
  name: string;
  state: State;
  detail: string;
}

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

  const tone: Record<State, 'default' | 'secondary' | 'destructive' | 'outline'> = { ok: 'default', checking: 'outline', degraded: 'secondary', down: 'destructive' };
  const label: Record<State, string> = { ok: 'Operational', checking: 'Checking', degraded: 'Degraded', down: 'Unavailable' };

  return (
    <div className='max-w-2xl'>
      <ul className='divide-y rounded-xl border'>
        {components.map((component) => (
          <li key={component.name} className='flex items-center justify-between gap-3 px-4 py-3'>
            <div>
              <p className='font-medium'>{component.name}</p>
              <p className='text-muted-foreground text-xs'>{component.detail}</p>
            </div>
            <Badge variant={tone[component.state]}>{label[component.state]}</Badge>
          </li>
        ))}
      </ul>
      <p className='text-muted-foreground mt-3 text-xs'>{checkedAt ? `Checked at ${checkedAt} from your browser.` : 'Checking…'}</p>
    </div>
  );
}
