'use client';

/**
 * Add an image to the conversation (typed or during Voice Mode). The server decodes it, stores it privately in this
 * workspace and records it on the conversation, so "the second image" means the same thing to everyone.
 */
import { useEffect, useRef, useState } from 'react';
import { IconPhoto } from '@tabler/icons-react';
import { Button } from '@/components/ui/button';
import { ApiError } from '@/lib/api/client';
import { useAgent } from '@/lib/agent-runtime/use-agent';
import { voiceSession } from '@/lib/agent-runtime/voice-session';

// Vercel Functions take request bodies up to 4.5 MB and base64 adds a third, so an image is sent at 3 MiB or less: a
// larger photo is scaled down (long edge 2048 px, then smaller) and re-encoded here, before it leaves the browser.
const MAX_PICK_BYTES = 30 * 1024 * 1024;
const MAX_SEND_BYTES = 3 * 1024 * 1024;
const EDGES = [2048, 1600, 1200];

function toBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.addEventListener('load', () => resolve(String(reader.result).split(',')[1] ?? ''));
    reader.addEventListener('error', () => reject(reader.error ?? new Error('The image could not be read.')));
    reader.readAsDataURL(blob);
  });
}

class UnreadableImage extends Error {}

async function fitForUpload(file: File): Promise<Blob | null> {
  if (file.size <= MAX_SEND_BYTES) return file;
  let bitmap: ImageBitmap;
  try {
    // Decoded upright (camera photos carry their rotation in EXIF).
    bitmap = await createImageBitmap(file, { imageOrientation: 'from-image' }).catch(() => createImageBitmap(file));
  } catch {
    throw new UnreadableImage('This image could not be read here. Try a PNG or JPEG exported from your photos app.');
  }
  try {
    for (const edge of EDGES) {
      const scale = Math.min(1, edge / Math.max(bitmap.width, bitmap.height));
      const canvas = document.createElement('canvas');
      canvas.width = Math.max(1, Math.round(bitmap.width * scale));
      canvas.height = Math.max(1, Math.round(bitmap.height * scale));
      const context = canvas.getContext('2d');
      if (!context) throw new UnreadableImage('This browser couldn’t scale the image down. Try a smaller one.');
      context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
      // The original format first (a PNG keeps its transparency), then JPEG.
      for (const [type, quality] of [[file.type, 0.9], ['image/jpeg', 0.85]] as const) {
        const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, type, quality));
        if (blob && blob.size <= MAX_SEND_BYTES) return blob;
      }
    }
    return null;
  } finally {
    bitmap.close();
  }
}

export function AttachImage({ conversationId, onAttached, disabled }: { conversationId: string | null; onAttached: (image: { assetId: string; index: number | null }) => void; disabled?: boolean }) {
  const { api, workspaceId, status } = useAgent();
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [problem, setProblem] = useState(false);
  const [justAdded, setJustAdded] = useState(false);
  useEffect(() => {
    if (!justAdded && !problem) return;
    const timer = setTimeout(() => {
      setJustAdded(false);
      setProblem(false);
    }, 6000);
    return () => clearTimeout(timer);
  }, [justAdded, problem]);
  if (!status?.imageAvailable && !status?.manager.available) return null;

  async function onFile(file: File | undefined) {
    if (!file || !conversationId) return;
    setMessage(null);
    setProblem(false);
    const fail = (text: string) => {
      setMessage(text);
      setProblem(true);
    };
    if (!/^image\/(png|jpeg)$/.test(file.type)) return fail('Use a PNG or JPEG image.');
    if (file.size > MAX_PICK_BYTES) return fail('Images must be at most 30 MB.');
    setBusy(true);
    try {
      let fitted: Blob | null;
      try {
        fitted = await fitForUpload(file);
      } catch (error) {
        return fail(error instanceof UnreadableImage ? error.message : 'This image could not be prepared for sending.');
      }
      if (!fitted) return fail('This image is too large to send, even scaled down. Try a smaller one.');
      const attached = await api.attach(workspaceId, { conversationId, data: await toBase64(fitted) });
      onAttached({ assetId: attached.assetId, index: attached.index });
      voiceSession.imageAttached(attached.assetId, attached.index);
      setMessage(`Image ${attached.index ?? ''} added. Ask Rafii about it.`);
      setJustAdded(true);
    } catch (error) {
      fail(error instanceof ApiError ? error.message : 'The image could not be added.');
    } finally {
      setBusy(false);
      if (input.current) input.current.value = '';
    }
  }

  return (
    <>
      <input ref={input} type='file' accept='image/png,image/jpeg' className='sr-only' tabIndex={-1} aria-hidden onChange={(event) => void onFile(event.target.files?.[0])} />
      <span className='relative inline-flex shrink-0'>
        <Button
          type='button'
          variant='quiet'
          size='icon-sm'
          aria-label={conversationId ? 'Add an image' : 'Add an image (send a message first)'}
          title={message ?? 'Add an image'}
          disabled={disabled || busy || !conversationId}
          onClick={() => input.current?.click()}
        >
          <IconPhoto className='size-4' aria-hidden />
        </Button>
        {justAdded && <span aria-hidden className='pointer-events-none absolute -top-0.5 -right-0.5 size-2.5 rounded-full bg-emerald-500' />}
        {problem && message && (
          // Visible to everyone (not only screen readers), above the button so the composer keeps its width.
          <span aria-hidden className='bg-popover text-popover-foreground pointer-events-none absolute bottom-full left-0 z-10 mb-1.5 w-max max-w-56 rounded-md px-2 py-1 text-[11px] leading-snug shadow-md' data-rafii-attach-error>
            {message}
          </span>
        )}
      </span>
      {/* The result is announced without taking space from the composer. */}
      <span className='sr-only' role='status' aria-live='polite'>
        {message ?? ''}
      </span>
    </>
  );
}
