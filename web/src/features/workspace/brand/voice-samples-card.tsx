'use client';

import { useState } from 'react';
import { toast } from 'sonner';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { ApiError } from '@/lib/api/client';
import { useAct } from '@/lib/api/hooks';
import type { SnapshotSource, SnapshotState } from '@/lib/api/types';

function errorMessage(error: unknown) {
  return error instanceof ApiError ? error.message : 'The writing sample could not be updated.';
}

function VoiceSampleRow({ source, revision, isOwner }: { source: SnapshotSource; revision: number; isOwner: boolean }) {
  const act = useAct();
  const [confirmRevoke, setConfirmRevoke] = useState(false);

  async function update(action: string, payload: Record<string, unknown>) {
    try {
      await act.mutateAsync({ revision, action, payload: { sourceId: source.id, ...payload } });
    } catch (error) {
      toast.error(errorMessage(error));
    }
  }

  const allowed = source.purposeGrants?.length || source.routeGrants?.length;
  return (
    <li className='border-border flex min-w-0 flex-col gap-3 rounded-lg border p-3'>
      <div className='flex min-w-0 items-start justify-between gap-3'>
        <div className='min-w-0'>
          <div className='flex flex-wrap items-center gap-2'>
            <span className='font-medium'>{source.title || 'Writing sample'}</span>
            <Badge variant={source.selected ? 'secondary' : 'outline'}>{source.selected ? 'Selected' : 'Not selected'}</Badge>
            {source.label && <Badge variant='outline'>{source.label.replace('_', ' ')}</Badge>}
          </div>
          <p className='text-muted-foreground mt-1 text-xs'>
            {[source.platform, source.account, source.language, source.publishedAt].filter(Boolean).join(' · ') || 'Manual sample'} · revision {source.revision ?? 1}
          </p>
        </div>
        <Checkbox
          aria-label={`Select ${source.title || 'writing sample'}`}
          checked={source.selected === true}
          disabled={act.isPending || !source.active}
          onCheckedChange={(checked) => void update('voice_sample_select', { selected: checked === true })}
        />
      </div>
      <p className='whitespace-pre-wrap text-sm'>{source.text}</p>
      <p className='text-muted-foreground text-xs'>
        {allowed ? `Allowed for ${(source.purposeGrants ?? []).join(' and ')} via ${(source.routeGrants ?? []).join(', ')}.` : 'Retained only. It is not allowed for analysis or drafting yet.'}
      </p>
      <div className='flex flex-wrap gap-2'>
        {isOwner && source.active && (
          <Button
            size='sm'
            variant='outline'
            disabled={act.isPending}
            onClick={() => void update('voice_sample_grant', { grants: [{ purpose: 'analysis', route: 'local-rules' }, { purpose: 'generation', route: 'local-cli' }], confirmed: true })}
          >
            Allow local voice use
          </Button>
        )}
        <Button size='sm' variant='ghost' disabled={act.isPending || !source.active} onClick={() => void update('voice_sample_exclude', {})}>
          Exclude
        </Button>
        <Button
          size='sm'
          variant={confirmRevoke ? 'destructive' : 'ghost'}
          disabled={act.isPending || !source.active}
          onClick={() => {
            if (!confirmRevoke) return setConfirmRevoke(true);
            setConfirmRevoke(false);
            void update('voice_sample_revoke', { confirmed: true });
          }}
        >
          {confirmRevoke ? 'Confirm revoke' : 'Revoke & remove text'}
        </Button>
      </div>
    </li>
  );
}

export function VoiceSamplesCard({ state, revision, isOwner }: { state: SnapshotState | undefined; revision: number; isOwner: boolean }) {
  const act = useAct();
  const [text, setText] = useState('');
  const [platform, setPlatform] = useState('');
  const samples = (state?.sources ?? []).filter((source) => source.kind === 'voice_sample');
  const analyzable = samples.filter((source) => source.active && source.selected && source.useGrants?.some((grant) => grant.purpose === 'analysis' && grant.route === 'local-rules'));

  async function importSample() {
    try {
      await act.mutateAsync({ revision, action: 'voice_samples_import', payload: { format: 'pasted', text, platform, language: /[一-鿿]/.test(text) ? '繁體中文' : 'English' } });
      setText('');
      toast.success('Writing sample retained. Choose it and approve how Raffi may use it.');
    } catch (error) {
      toast.error(errorMessage(error));
    }
  }

  async function analyzeSelected() {
    try {
      await act.mutateAsync({ revision, action: 'voice_profile_analyze', payload: { sourceIds: analyzable.map((source) => source.id), route: 'local-rules' } });
      toast.success('A provisional voice profile is ready for review. It is not active yet.');
    } catch (error) {
      toast.error(errorMessage(error));
    }
  }

  return (
    <Card data-tour='voice-samples'>
      <CardHeader>
        <CardTitle>Learn my voice</CardTitle>
        <CardDescription>Retain writing you choose, then separately select it and approve its use. Sample facts never become current brand facts.</CardDescription>
      </CardHeader>
      <CardContent className='flex flex-col gap-4'>
        <div className='grid gap-2 sm:grid-cols-[minmax(0,1fr)_12rem]'>
          <Textarea aria-label='Writing sample' value={text} onChange={(event) => setText(event.target.value)} maxLength={8000} rows={4} placeholder='Paste one caption or post…' />
          <div className='flex flex-col gap-2'>
            <Input aria-label='Sample platform' value={platform} onChange={(event) => setPlatform(event.target.value)} maxLength={80} placeholder='Platform (optional)' />
            <Button disabled={act.isPending || !text.trim()} onClick={() => void importSample()}>{act.isPending ? 'Saving…' : 'Retain sample'}</Button>
            <p className='text-muted-foreground text-xs'>CSV and JSON use the same server contract; the visible manual route is available first.</p>
          </div>
        </div>
        {samples.length ? (
          <>
            <ul className='flex flex-col gap-3'>
              {samples.map((source) => <VoiceSampleRow key={source.id} source={source} revision={revision} isOwner={isOwner} />)}
            </ul>
            <div className='flex flex-wrap items-center gap-3'>
              <Button disabled={act.isPending || analyzable.length === 0} onClick={() => void analyzeSelected()}>
                {act.isPending ? 'Analysing…' : 'Analyse selected samples'}
              </Button>
              <p className='text-muted-foreground text-xs'>{analyzable.length} selected sample{analyzable.length === 1 ? '' : 's'} allowed for local analysis.</p>
            </div>
          </>
        ) : (
          <p className='text-muted-foreground text-sm'>No retained writing samples. A few samples can produce a provisional profile later; there is no minimum guarantee.</p>
        )}
      </CardContent>
    </Card>
  );
}
