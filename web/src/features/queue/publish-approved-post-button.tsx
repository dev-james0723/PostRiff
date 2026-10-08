'use client';

import { useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Icons } from '@/components/icons';
import { keys } from '@/lib/api/hooks';
import type { Job, WorkerBinding } from '@/lib/api/types';
import { useWorkspace } from '@/lib/workspace/provider';
import { canPublishApprovedJob } from './job-dispatch';

/** Sends one existing exact approval to the fenced worker; never retries a lost response. */
export function PublishApprovedPostButton({ job, nowSeconds, allowed, workerBinding }: { job: Job; nowSeconds: number; allowed: boolean; workerBinding?: WorkerBinding | null }) {
  const { api, workspaceId } = useWorkspace();
  const client = useQueryClient();
  const execute = useMutation({
    retry: false,
    mutationFn: () => {
      if (!workspaceId || job.manifest.workspaceId !== workspaceId || !job.approvalDigest) throw new Error('Reload this post in its workspace.');
      return api.executeJob(workspaceId, job.id, job.approvalDigest);
    },
    onSuccess: (result) => toast.info(result.processed ? 'Worker check complete. View the post status.' : 'This post wasn’t dispatched. Check its latest status.'),
    onError: () => toast.error('Couldn’t confirm this worker request', {
      description: 'Reload the post status before continuing. Do not submit it again.',
      action: { label: 'Reload status', onClick: () => window.location.reload() }
    }),
    onSettled: () => client.invalidateQueries({ queryKey: keys.snapshot(workspaceId ?? '') })
  });
  if (job.manifest.workspaceId !== workspaceId || !canPublishApprovedJob(job, nowSeconds, allowed, workerBinding)) return null;
  return (
    <Button variant='action' size='control' className='h-11 px-3.5 text-[13px]'
      disabled={execute.isPending || execute.isError} onClick={() => execute.mutate()}>
      {execute.isPending ? <Icons.spinner className='animate-spin' /> : <Icons.send />}
      {execute.isPending ? 'Checking post…' : 'Publish approved post'}
    </Button>
  );
}
