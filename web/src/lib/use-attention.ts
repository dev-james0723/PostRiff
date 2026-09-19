'use client';
import { useEffect, useState } from 'react';
import { useChannels, useSnapshot, useUsage } from '@/lib/api/hooks';
import { deriveAttention } from './attention';

export function useAttention() {
  const snapshot = useSnapshot();
  const channels = useChannels();
  const usage = useUsage();
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => { const timer = window.setInterval(() => setNow(Date.now() / 1000), 30_000); return () => window.clearInterval(timer); }, []);
  return { ...deriveAttention({snapshot, channels, usage, now}), loading: snapshot.isLoading || channels.isLoading || usage.isLoading };
}
