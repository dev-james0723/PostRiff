'use client';

import Link from 'next/link';
import { useEffect, useId, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { createApi } from '@/lib/api/client';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Surface } from '@/components/rafii';
import type { PostCheck } from '@/lib/growth/types';
import { CheckResult } from './shared';

const api = createApi(async () => null);

export function PublicPostDoctor() {
  const [ready, setReady] = useState(false);
  useEffect(() => setReady(true), []);
  const draftId = useId();
  const [text, setText] = useState('');
  const [platform, setPlatform] = useState('Threads');
  const [language, setLanguage] = useState('en');
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<PostCheck | null>(null);
  async function check() {
    setBusy(true);
    setError('');
    setResult(null);
    try {
      setResult(await api.publicPostDoctor({ text, platform, language, confirmed }));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Post Doctor is unavailable.');
    } finally {
      setBusy(false);
    }
  }
  return (
    <Surface material='quiet' className='mx-auto flex max-w-3xl flex-col gap-4'>
      <label htmlFor={draftId} className='flex flex-col gap-2 text-sm'>
        Your draft
        <Textarea
          disabled={!ready}
          id={draftId}
          aria-label='Your draft'
          value={text}
          onChange={(e) => {
            setText(e.target.value);
            setResult(null);
          }}
          maxLength={8000}
          rows={8}
          placeholder='Paste your own draft here.'
        />
      </label>
      <div className='flex flex-wrap gap-4'>
        <label className='flex flex-col gap-1 text-sm'>
          Platform
          <select
            disabled={!ready}
            aria-label='Platform'
            className='rafii-field rounded-lg p-2'
            value={platform}
            onChange={(e) => setPlatform(e.target.value)}
          >
            {['Threads', 'Instagram', 'LinkedIn', 'X', 'Bluesky', 'Mastodon'].map((p) => (
              <option key={p}>{p}</option>
            ))}
          </select>
        </label>
        <label className='flex flex-col gap-1 text-sm'>
          Draft language
          <select
            disabled={!ready}
            aria-label='Draft language'
            className='rafii-field rounded-lg p-2'
            value={language}
            onChange={(e) => setLanguage(e.target.value)}
          >
            <option value='en'>English</option>
            <option value='zh-HK'>繁體中文</option>
            <option value='zh-CN'>简体中文</option>
            <option value='other'>Other</option>
          </select>
        </label>
      </div>
      <label className='flex items-start gap-2 text-sm'>
        <input
          disabled={!ready}
          aria-label='Allow analysis of my public draft'
          type='checkbox'
          className='mt-1'
          checked={confirmed}
          onChange={(e) => setConfirmed(e.target.checked)}
        />
        Send this draft to Jev or the Gemini fallback for writing feedback. Draft text is not saved;
        the qualitative result expires after 24 hours.
      </label>
      <Button
        variant='action'
        disabled={busy || !confirmed || !text.trim()}
        onClick={() => void check()}
      >
        {busy ? 'Checking your draft…' : 'Check my draft'}
      </Button>
      <p className='text-muted-foreground text-xs'>
        Up to 3 anonymous checks per day. No account metrics are inferred.
      </p>
      {error && (
        <p role='alert' className='text-destructive text-sm'>
          {error}
        </p>
      )}
      {result && <CheckResult result={result} />}
      <Link href='/app' className='text-sm underline'>
        Open Rafii for saved drafts, rewriting and your Creator Genome
      </Link>
    </Surface>
  );
}

export function ContentDNA({ token }: { token: string }) {
  // Query is public and label-only. No workspace or corpus API is reached from this page.
  const query = useQuery({
    queryKey: ['public-content-dna', token],
    queryFn: () => api.contentDNA(token),
    retry: false
  });
  return (
    <Surface material='quiet' className='mx-auto flex max-w-xl flex-col gap-4'>
      {query.isPending && <p className='text-muted-foreground'>Loading Content DNA…</p>}
      {query.isError && (
        <p role='alert' className='text-muted-foreground'>
          This card is unavailable or has been revoked.
        </p>
      )}
      {query.data && (
        <>
          <ul className='flex flex-wrap gap-2'>
            {query.data.labels.map((label) => (
              <li key={label} className='rafii-paper rounded-full px-4 py-2'>
                {label}
              </li>
            ))}
          </ul>
          <p className='text-muted-foreground text-sm'>{query.data.description}</p>
        </>
      )}
      <Link href='/post-doctor' className='text-sm underline'>
        Try Post Doctor with your own writing
      </Link>
    </Surface>
  );
}
