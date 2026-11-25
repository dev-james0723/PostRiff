import type { FreePreview as Preview, PreviewAction } from '@/lib/api/types';
import { Surface } from '@/components/rafii';
import { PREVIEW_REASON } from './billing-copy';

function Action({ label, action, note }: { label: string; action: PreviewAction; note?: string }) {
  const status = action.eligible ? 'Available' : action.reason ? PREVIEW_REASON[action.reason] : 'Preview unavailable';
  return <div className='flex flex-col gap-1 text-sm'><dt className='font-medium'>{label}</dt><dd className='text-muted-foreground'>{action.remaining} preview{action.remaining === 1 ? '' : 's'} remaining · {status}{note && <span className='mt-1 block'>{note}</span>}</dd></div>;
}

export function FreePreview({ preview }: { preview: Preview }) {
  return <section aria-labelledby='free-preview-heading' className='flex flex-col gap-3'>
    <h2 id='free-preview-heading' className='px-1 text-lg font-medium'>Free preview</h2>
    <Surface material='quiet' radius='card' padding='md'>
      <dl className='grid gap-5 sm:grid-cols-2'>
        <Action label='Post Doctor' action={preview.postDoctor} />
        <Action label='Genome' action={preview.genome} note={`Up to ${preview.genome.maxPosts} recent posts`} />
      </dl>
    </Surface>
  </section>;
}
