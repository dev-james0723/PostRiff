'use client';

import { toast } from 'sonner';
import { Icons } from '@/components/icons';
import { Button } from '@/components/ui/button';
import { formatBytes } from '@/lib/time';
import { groupHex } from './privacy-model';

export interface FileFingerprint {
  filename: string;
  bytes: number;
  /** SHA-256 of the downloaded bytes, computed in this browser; `null` where the browser cannot hash. */
  sha256: string | null;
}

export async function copyText(text: string, what: string) {
  try {
    await navigator.clipboard.writeText(text);
    toast.success(`${what} copied.`);
  } catch {
    toast.error('Copying is blocked in this browser. Select the text and copy it instead.');
  }
}

/**
 * The fingerprint of the file this browser received. It is not compared with the recorded receipt: the
 * server builds the receipt's copy and the download separately, so a match is not guaranteed today.
 */
export function Fingerprint({ file, note }: { file: FileFingerprint; note: string }) {
  return (
    <div className='bg-muted/40 flex min-w-0 flex-col gap-1.5 rounded-lg border p-3' aria-live='polite'>
      <div className='flex items-center justify-between gap-2'>
        <span className='text-xs font-medium'>Your file&apos;s fingerprint</span>
        {file.sha256 && (
          <Button variant='ghost' size='icon-xs' aria-label='Copy the fingerprint' onClick={() => void copyText(file.sha256 as string, 'Fingerprint')}>
            <Icons.copy />
          </Button>
        )}
      </div>
      {file.sha256 ? (
        <code className='font-mono text-xs leading-relaxed break-all'>{groupHex(file.sha256)}</code>
      ) : (
        <p className='text-muted-foreground text-xs'>This browser could not compute a fingerprint for this file.</p>
      )}
      <span className='text-muted-foreground text-xs'>
        SHA-256 · {file.filename} · {formatBytes(file.bytes)}
      </span>
      <p className='text-muted-foreground text-xs'>{note}</p>
    </div>
  );
}
