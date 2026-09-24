'use client';

import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { rafiiDialog, rafiiDialogFooter } from '@/components/auth/form-styles';
import { Icons } from '@/components/icons';
import { StatefulButton } from '@/components/motion/button';
import { Checkbox } from '@/components/motion/checkbox';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { ApiError } from '@/lib/api/client';
import { keys } from '@/lib/api/hooks';
import { downloadBlob } from '@/lib/download';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { cn } from '@/lib/utils';
import { SettingsSection } from '../settings-section';
import { GLASS_STATEFUL, type BusyProps } from './export-cards';
import { copyText } from './fingerprint';

interface DiagnosticsResult {
  requestId: string;
  package: Record<string, unknown>;
}

export function DiagnosticsCard({ busy, setBusy }: BusyProps) {
  const { api, workspaceId } = useWorkspaceApi();
  const client = useQueryClient();
  const [consent, setConsent] = useState(false);
  const [creating, setCreating] = useState(false);
  const [result, setResult] = useState<DiagnosticsResult | null>(null);
  const [open, setOpen] = useState(false);

  async function create() {
    setBusy('diagnostics');
    setCreating(true);
    try {
      const response = await api.dataRequest(workspaceId, { kind: 'diagnostics', consent: true });
      const pkg = response.package;
      if (!pkg || typeof pkg !== 'object') throw new Error('The server did not return a package.');
      setResult({ requestId: String(response.requestId ?? ''), package: pkg as Record<string, unknown> });
      setConsent(false);
      setOpen(true);
    } catch (err) {
      toast.error(err instanceof ApiError || err instanceof Error ? err.message : 'The diagnostics package could not be created.');
    } finally {
      setCreating(false);
      setBusy(null);
      void client.invalidateQueries({ queryKey: keys.dataRequests(workspaceId) });
      void client.invalidateQueries({ queryKey: keys.audit(workspaceId) });
    }
  }

  const json = result ? JSON.stringify(result.package, null, 2) : '';
  const filename = result ? `postriff-diagnostics-${result.requestId.slice(0, 8) || 'package'}.json` : '';

  return (
    <SettingsSection
      id='privacy-diagnostics'
      title='Diagnostics'
      description='A package for support with counts and states only: no prompts, post text, sources, tokens or files.'
      className='h-full'
      bodyClassName='flex-1'
      data-tour='privacy-diagnostics'
    >
      <Checkbox
        checked={consent}
        onCheckedChange={setConsent}
        disabled={creating}
        label='I consent to creating a diagnostics package'
        className='min-h-11 items-start [&>button]:mt-0.5'
      />
      <p className='text-muted-foreground text-xs leading-relaxed'>
        Creating it adds a receipt to Data requests and shows you the whole package first. PostRiff does not send it anywhere; downloading it is up to you.
      </p>
      <div className='mt-auto flex flex-wrap items-center gap-2 pt-1'>
        <StatefulButton
          variant='outline'
          className={GLASS_STATEFUL}
          state={creating ? 'loading' : 'idle'}
          loadingText='Creating…'
          disabled={!consent || (busy !== null && busy !== 'diagnostics')}
          onClick={() => void create()}
        >
          Create package
        </StatefulButton>
        {result && !creating && (
          <Button variant='quiet' size='sm' className='min-h-9' onClick={() => setOpen(true)}>
            View last package
          </Button>
        )}
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className={cn(rafiiDialog, 'gap-5 sm:max-w-lg')}>
          <DialogHeader className='gap-1.5 pr-8'>
            <DialogTitle className='text-foreground text-xl font-medium tracking-tight'>Your diagnostics package</DialogTitle>
            <DialogDescription className='leading-relaxed'>
              This is the whole package. PostRiff does not send it anywhere and keeps only a receipt listing what it counts. Download it and attach it when
              you contact support.
            </DialogDescription>
          </DialogHeader>
          <pre className='rafii-quiet max-h-72 min-w-0 overflow-auto rounded-[var(--rafii-radius-control)] p-3 font-mono text-xs leading-relaxed break-all whitespace-pre-wrap'>
            {json}
          </pre>
          <DialogFooter className={rafiiDialogFooter}>
            <Button variant='glass' size='control' onClick={() => void copyText(json, 'Package')}>
              <Icons.copy /> Copy
            </Button>
            <Button
              variant='action'
              size='control'
              onClick={() => {
                downloadBlob(new Blob([json], { type: 'application/json' }), filename);
                toast.success('Diagnostics package downloaded.');
              }}
            >
              <Icons.download /> Download JSON
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </SettingsSection>
  );
}
