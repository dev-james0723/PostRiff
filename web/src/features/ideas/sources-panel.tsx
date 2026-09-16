'use client';

import { motion, useReducedMotion } from 'motion/react';
import { toast } from 'sonner';
import { Switch } from '@/components/motion/switch';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { useAct, useSnapshot } from '@/lib/api/hooks';
import { ApiError } from '@/lib/api/client';
import type { SnapshotSource, SourcePolicy } from '@/lib/api/types';
import { EASE_OUT } from '@/lib/ease';

const POLICIES: { id: SourcePolicy; label: string; note: string }[] = [
  { id: 'public_quote', label: 'My own writing', note: 'May be quoted publicly.' },
  { id: 'rewrite_approval', label: 'Reference — rewrite and approve', note: 'Never quoted; drafts need your public-use approval.' },
  { id: 'internal_reference', label: 'Internal only', note: 'Summaries only, never in public drafts.' },
  { id: 'prohibited', label: 'Do not use', note: 'Kept, but excluded from every draft.' }
];

/**
 * Per-source policy and cloud-egress consent (`source_policy` action). The paid
 * model route only ever sees sources with cloud consent; everything else stays
 * on the deterministic preview.
 */
export function SourcesPanel({ cloudAvailable }: { cloudAvailable: boolean }) {
  const snapshot = useSnapshot();
  const act = useAct();
  const reduce = useReducedMotion();
  const sources = (snapshot.data?.state.sources ?? []).filter((s) => s.active);
  const revision = snapshot.data?.revision ?? 0;

  function update(source: SnapshotSource, policy: SourcePolicy, cloud: boolean) {
    const consent = cloud ? ['local', 'cloud'] : ['local'];
    act.mutate(
      { revision, action: 'source_policy', payload: { sourceId: source.id, policy, egressConsent: consent, confirmed: true } },
      {
        onSuccess: () => toast.success(cloud ? 'Cloud drafting allowed for this source.' : 'Source policy saved.'),
        onError: (err) => toast.error(err instanceof ApiError ? err.message : 'The source policy could not be saved.')
      }
    );
  }

  if (sources.length === 0) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle className='text-base'>Sources ({sources.length})</CardTitle>
        <CardDescription>
          What each source may be used for, and whether it may leave this server for the AI model. Nothing is sent to a model without the switch.
        </CardDescription>
      </CardHeader>
      <CardContent className='flex flex-col gap-3'>
        {sources.map((source, index) => {
          const policy = (source.sourcePolicy ?? '') as SourcePolicy | '';
          const cloud = (source.egressConsent ?? []).includes('cloud');
          const facts = (source.facts ?? []).filter((f) => f.approved).length;
          return (
            <motion.div
              key={source.id}
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              transition={reduce ? { duration: 0 } : { duration: 0.24, delay: Math.min(index * 0.04, 0.2), ease: EASE_OUT }}
              className='flex flex-col gap-3 rounded-lg border p-3 sm:flex-row sm:items-center sm:justify-between'
            >
              <div className='min-w-0'>
                <p className='truncate text-sm font-medium'>{source.title || source.kind}</p>
                <p className='text-muted-foreground text-xs'>
                  {source.kind} · {facts} approved fact{facts === 1 ? '' : 's'}
                  {!policy && (
                    <Badge variant='outline' className='ml-2'>
                      policy needed
                    </Badge>
                  )}
                </p>
              </div>
              <div className='flex flex-wrap items-center gap-3'>
                <Select value={policy} onValueChange={(value) => update(source, value as SourcePolicy, cloud)}>
                  <SelectTrigger className='h-8 w-56' aria-label='Source policy' disabled={act.isPending}>
                    <SelectValue>{POLICIES.find((p) => p.id === policy)?.label ?? 'Choose how it may be used'}</SelectValue>
                  </SelectTrigger>
                  <SelectContent>
                    {POLICIES.map((p) => (
                      <SelectItem key={p.id} value={p.id}>
                        <span className='flex flex-col'>
                          <span>{p.label}</span>
                          <span className='text-muted-foreground text-xs'>{p.note}</span>
                        </span>
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <div className='flex items-center gap-2'>
                  <Switch
                    checked={cloud}
                    disabled={act.isPending || !policy || policy === 'prohibited'}
                    onCheckedChange={(checked) => update(source, (policy || 'public_quote') as SourcePolicy, checked)}
                    ariaLabel='Allow cloud drafting'
                    label='Allow AI model (cloud)'
                  />
                  {!cloudAvailable && <span className='text-muted-foreground text-xs'>· no paid route yet</span>}
                </div>
              </div>
            </motion.div>
          );
        })}
      </CardContent>
    </Card>
  );
}
