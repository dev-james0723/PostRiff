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

const MAX_BYTES = 8 * 1024 * 1024;

function toBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.addEventListener('load', () => resolve(String(reader.result).split(',')[1] ?? ''));
    reader.addEventListener('error', () => reject(reader.error ?? new Error('The image could not be read.')));
    reader.readAsDataURL(file);
  });
}

export function AttachImage({ conversationId, onAttached, disabled }: { conversationId: string | null; onAttached: (image: { assetId: string; index: number | null }) => void; disabled?: boolean }) {
  const { api, workspaceId, status } = useAgent();
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [justAdded, setJustAdded] = useState(false);
  useEffect(() => {
    if (!justAdded) return;
    const timer = setTimeout(() => setJustAdded(false), 6000);
    return () => clearTimeout(timer);
  }, [justAdded]);
  if (!status?.imageAvailable && !status?.manager.available) return null;

  async function onFile(file: File | undefined) {
    if (!file || !conversationId) return;
    setMessage(null);
    if (!/^image\/(png|jpeg)$/.test(file.type)) return setMessage('Use a PNG or JPEG image.');
    if (file.size > MAX_BYTES) return setMessage('Images must be at most 8 MB.');
    setBusy(true);
    try {
      const attached = await api.attach(workspaceId, { conversationId, data: await toBase64(file) });
      onAttached({ assetId: attached.assetId, index: attached.index });
      voiceSession.imageAttached(attached.assetId, attached.index);
      setMessage(`Image ${attached.index ?? ''} added. Ask Rafii about it.`);
      setJustAdded(true);
    } catch (error) {
      setMessage(error instanceof ApiError ? error.message : 'The image could not be added.');
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
      </span>
      {/* The result is announced without taking space from the composer. */}
      <span className='sr-only' role='status' aria-live='polite'>
        {message ?? ''}
      </span>
    </>
  );
}
