import { Surface } from '@/components/rafii';

const ALLOWANCES = ['Writing', 'Media', 'Connected accounts', 'Members', 'Storage'];

/** Product allowances are separate from external spending and individual post approval. */
export function FounderAccess() {
  return (
    <Surface material='glass' radius='card' padding='md' data-tour='billing-plan' role='region' aria-labelledby='founder-access-heading'>
      <h2 id='founder-access-heading' className='text-2xl font-medium tracking-tight md:text-3xl'>Founder access</h2>
      <p className='text-muted-foreground mt-1 text-sm'>Unlimited product access in this workspace. Your spending limits and post approvals still apply.</p>
      <dl className='mt-5 grid gap-3 sm:grid-cols-2'>
        {ALLOWANCES.map((label) => (
          <div key={label} className='flex items-center justify-between gap-4 text-sm'>
            <dt>{label}</dt>
            <dd className='font-medium'>Unlimited</dd>
          </div>
        ))}
      </dl>
    </Surface>
  );
}
