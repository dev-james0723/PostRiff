'use client';

import { useState } from 'react';

export default function DemoAccess({ token }: { token: string }) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function enter() {
    if (pending) return;
    setPending(true);
    setError(null);
    try {
      const response = await fetch('/api/control/v2/session/exchange', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token, 'X-Control-Exchange': '1' },
        body: '{}',
        cache: 'no-store',
      });
      if (!response.ok) throw new Error('Local Demo session unavailable. Check that the isolated preview runtime is running.');
      window.location.assign('/control/command?mode=demo');
    } catch {
      setError('Local Demo session unavailable. Check that the isolated preview runtime is running.');
      setPending(false);
    }
  }
  return <div>
    <button type="button" onClick={enter} disabled={pending}>{pending ? 'Opening Demo…' : 'Enter Demo as simulated founder'}</button>
    {error && <p role="alert">{error}</p>}
  </div>;
}
