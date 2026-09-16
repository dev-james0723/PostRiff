'use client';

import { useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import PageContainer from '@/components/layout/page-container';
import { Icons } from '@/components/icons';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger
} from '@/components/ui/alert-dialog';
import { Badge } from '@/components/ui/badge';
import { Button, buttonVariants } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { siteConfig } from '@/config/site';
import { keys, useDataRequests, usePrivacyNotice } from '@/lib/api/hooks';
import { ApiError } from '@/lib/api/client';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import { useAuth } from '@/lib/auth/session';
import { downloadBlob } from '@/lib/download';
import { formatDateTime } from '@/lib/time';
import { useWorkspaceApi } from '@/lib/workspace/provider';

const infoContent = {
  title: 'Your data, your call',
  sections: [
    {
      title: 'Export with a receipt',
      description: 'Exports are zipped drafts, sources, approvals and receipts. Each export is recorded with its SHA-256 so you can prove what you received.'
    },
    {
      title: 'Diagnostics need consent',
      description: 'A diagnostics package contains counts and states only — never prompts, post bodies, tokens or files.'
    },
    {
      title: 'Deletion',
      description: 'Deleting the account removes the workspace and its media. Content-free receipts survive as tombstones where audit rules require it.'
    }
  ]
};

export function PrivacyView() {
  const { api, workspaceId } = useWorkspaceApi();
  const auth = useAuth();
  const router = useRouter();
  const client = useQueryClient();
  const access = useWorkspaceAccess();
  const owner = checkAccess(access, { permission: 'owner' });
  const requests = useDataRequests();
  const notice = usePrivacyNotice();
  const [busy, setBusy] = useState<string | null>(null);
  const [consent, setConsent] = useState(false);
  const [confirmation, setConfirmation] = useState('');
  const [deleting, setDeleting] = useState(false);

  async function run(kind: string, task: () => Promise<void>) {
    setBusy(kind);
    try {
      await task();
      await client.invalidateQueries({ queryKey: keys.dataRequests(workspaceId) });
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : 'The request failed.');
    } finally {
      setBusy(null);
    }
  }

  async function exportDrafts() {
    const result = await api.dataRequest(workspaceId, { kind: 'export' });
    const receipt = result.receipt as { sha256?: string } | undefined;
    downloadBlob(await api.exportDrafts(workspaceId), 'postriff-private-drafts.zip');
    toast.success(`Export recorded · sha256 ${receipt?.sha256?.slice(0, 12) ?? ''}…`);
  }

  async function exportProfile() {
    downloadBlob(await api.exportProfile(workspaceId), 'postriff-personal-voice.zip');
    toast.success('Voice profile exported.');
  }

  async function diagnostics() {
    await api.dataRequest(workspaceId, { kind: 'diagnostics', consent: true });
    toast.success('Diagnostics package recorded (counts and states only).');
    setConsent(false);
  }

  async function deleteAccount() {
    setDeleting(true);
    try {
      await api.deleteAccount(workspaceId, confirmation.trim());
      toast.success('Your account and workspace were deleted.');
      await auth.signOut();
      router.replace('/');
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : 'The account could not be deleted.');
      setDeleting(false);
    }
  }

  const retention = notice.data?.retention ?? {};

  return (
    <PageContainer pageTitle='Privacy & data' pageDescription='Export, retract, inspect or delete. Every action leaves a receipt.' infoContent={infoContent}>
      <div className='flex flex-col gap-6'>
        <div className='grid gap-4 lg:grid-cols-3'>
          <Card>
            <CardHeader>
              <CardTitle>Export</CardTitle>
              <CardDescription>Drafts, sources, approvals and receipts as a zip. No tokens, no media bytes.</CardDescription>
            </CardHeader>
            <CardFooter className='flex flex-wrap gap-2'>
              <Button disabled={busy !== null} onClick={() => void run('export', exportDrafts)}>
                {busy === 'export' ? 'Preparing…' : 'Export drafts'}
              </Button>
              <Button variant='outline' disabled={busy !== null} onClick={() => void run('profile', exportProfile)}>
                Voice profile
              </Button>
            </CardFooter>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>Diagnostics</CardTitle>
              <CardDescription>A sanitised package for support: counts and states only.</CardDescription>
            </CardHeader>
            <CardContent>
              <Label className='flex items-center gap-2 text-sm font-normal'>
                <Checkbox checked={consent} onCheckedChange={(value) => setConsent(value === true)} />I consent to creating a diagnostics package
              </Label>
            </CardContent>
            <CardFooter>
              <Button variant='outline' disabled={!consent || busy !== null} onClick={() => void run('diagnostics', diagnostics)}>
                Create package
              </Button>
            </CardFooter>
          </Card>
          <Card className='border-destructive/40'>
            <CardHeader>
              <CardTitle>Delete account</CardTitle>
              <CardDescription>
                {owner ? 'Removes this workspace, its media and your account. In-flight publications must finish first.' : 'Only the workspace owner can delete the account.'}
              </CardDescription>
            </CardHeader>
            <CardFooter>
              {owner && (
                <AlertDialog>
                  <AlertDialogTrigger render={<Button variant='outline' className='text-destructive' />}>
                    Delete account…
                  </AlertDialogTrigger>
                  <AlertDialogContent>
                    <AlertDialogHeader>
                      <AlertDialogTitle>Delete your account?</AlertDialogTitle>
                      <AlertDialogDescription>
                        This cannot be undone. Export first if you want a copy. Type <strong>DELETE</strong> to confirm.
                      </AlertDialogDescription>
                    </AlertDialogHeader>
                    <Input value={confirmation} onChange={(event) => setConfirmation(event.target.value)} aria-label='Type DELETE to confirm' placeholder='DELETE' />
                    <AlertDialogFooter>
                      <AlertDialogCancel>Keep my account</AlertDialogCancel>
                      <AlertDialogAction disabled={confirmation.trim() !== 'DELETE' || deleting} onClick={() => void deleteAccount()}>
                        {deleting ? 'Deleting…' : 'Delete everything'}
                      </AlertDialogAction>
                    </AlertDialogFooter>
                  </AlertDialogContent>
                </AlertDialog>
              )}
            </CardFooter>
          </Card>
        </div>

        <section className='flex flex-col gap-3' aria-labelledby='requests-heading'>
          <h3 id='requests-heading' className='text-lg font-semibold'>
            Data requests
          </h3>
          {requests.isLoading ? (
            <Skeleton className='h-24 w-full' />
          ) : (requests.data?.requests ?? []).length === 0 ? (
            <p className='text-muted-foreground text-sm'>No requests yet.</p>
          ) : (
            <div className='overflow-x-auto rounded-lg border'>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>When</TableHead>
                    <TableHead>Kind</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Receipt</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(requests.data?.requests ?? []).map((request) => {
                    const sha = (request.receipt as { sha256?: string })?.sha256;
                    return (
                      <TableRow key={request.requestId}>
                        <TableCell className='whitespace-nowrap'>{formatDateTime(request.requestedAt)}</TableCell>
                        <TableCell>{request.kind}</TableCell>
                        <TableCell>
                          <Badge variant='outline'>{request.status}</Badge>
                        </TableCell>
                        <TableCell className='font-mono text-xs'>{sha ? `${sha.slice(0, 16)}…` : '—'}</TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>
          )}
        </section>

        <section className='flex flex-col gap-3' aria-labelledby='notice-heading'>
          <div className='flex flex-wrap items-center justify-between gap-2'>
            <h3 id='notice-heading' className='text-lg font-semibold'>
              Privacy notice
            </h3>
            <div className='flex gap-2'>
              <Link href={siteConfig.links.privacy} className={buttonVariants({ variant: 'ghost', size: 'sm' })}>
                Full policy <Icons.externalLink className='size-3.5' />
              </Link>
              <Link href={siteConfig.links.dataDeletion} className={buttonVariants({ variant: 'ghost', size: 'sm' })}>
                Deletion steps
              </Link>
            </div>
          </div>
          {notice.isLoading ? (
            <Skeleton className='h-40 w-full' />
          ) : notice.data ? (
            <div className='grid gap-4 lg:grid-cols-2'>
              <Card>
                <CardHeader>
                  <CardTitle className='text-base'>How your content is used</CardTitle>
                  <CardDescription>{notice.data.status}</CardDescription>
                </CardHeader>
                <CardContent className='flex flex-col gap-3 text-sm'>
                  <p>{notice.data.aiProcessing}</p>
                  <p>{notice.data.providerAccess}</p>
                  <p>{notice.data.telemetry}</p>
                </CardContent>
              </Card>
              <Card>
                <CardHeader>
                  <CardTitle className='text-base'>Retention</CardTitle>
                  <CardDescription>What is kept, for how long.</CardDescription>
                </CardHeader>
                <CardContent>
                  <Table>
                    <TableBody>
                      {Object.entries(retention).map(([key, value]) => (
                        <TableRow key={key}>
                          <TableCell className='font-medium'>{key.replace(/_/g, ' ')}</TableCell>
                          <TableCell className='text-muted-foreground text-xs'>{value.retention}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </CardContent>
              </Card>
            </div>
          ) : (
            <p className='text-muted-foreground text-sm'>The privacy notice could not be loaded.</p>
          )}
        </section>
      </div>
    </PageContainer>
  );
}

