import type { Manifest } from '@/lib/api/types';

/** The immutable provider fields being approved, including settings absent from the app mockup. */
export function MastodonPollDetails({ manifest }: { manifest: Manifest }) {
  if (manifest.platform !== 'Mastodon' || !manifest.publishOptions?.poll) return null;
  const poll = manifest.publishOptions.poll as Record<string, unknown>;
  const answers = Array.isArray(poll.options) ? poll.options.filter((answer): answer is string => typeof answer === 'string') : [];
  return <section aria-label='Exact Mastodon poll for approval' className='flex flex-col gap-1 rounded border p-3 text-sm'>
    <p className='font-medium whitespace-pre-wrap'>{manifest.payload.text}</p>
    <ol className='list-inside list-decimal'>{answers.map((answer, index) => <li key={index} className='whitespace-pre-wrap'>{answer}</li>)}</ol>
    <p>Duration: {String(poll.expires_in)} seconds · {poll.multiple === true ? 'Multiple answers allowed' : 'One answer per person'} · {poll.hide_totals === true ? 'Vote totals hidden until the poll ends' : 'Vote totals visible'}</p>
    <p>Visibility: {String(manifest.publishOptions.visibility ?? 'public')} · No media attached</p>
    <p className='text-muted-foreground text-xs'>The server applies its current poll limits before submission. This review does not publish until explicitly approved.</p>
  </section>;
}
