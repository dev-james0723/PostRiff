import { Icons } from '@/components/icons';
import { StateMessage, Surface } from '@/components/rafii';

/**
 * No CLI listed. Not an error: the preview still writes. `hosted` comes from the Memory endpoint's
 * research summary (the only deployment signal the web has today); null when it is unknown.
 */
export function CliEmpty({ hosted }: { hosted: boolean | null }) {
  return (
    <Surface material='quiet' radius='card' padding='md' data-tour='models-empty' className='flex flex-col gap-4'>
      <StateMessage
        kind='empty'
        media={
          <span aria-hidden className='rafii-glass text-muted-foreground flex size-11 items-center justify-center rounded-full'>
            <Icons.terminal className='size-5' />
          </span>
        }
        title='No CLI writer on this deployment'
        description={
          hosted === true
            ? 'A CLI you already pay for will run through a desktop companion on your own computer. That is not available yet; the writers under PostRiff are what write here today.'
            : 'You can keep drafting with the writers under PostRiff. To add a coding CLI you already pay for:'
        }
        className='bg-transparent p-0'
      />
      {hosted !== true && (
        <ol className='text-muted-foreground mx-auto flex max-w-md list-decimal flex-col gap-1.5 pl-5 text-left text-sm leading-relaxed'>
          <li>Install Claude Code or the Codex CLI on the machine that serves the PostRiff API.</li>
          <li>
            Sign in there in Terminal with <code className='font-mono text-xs'>claude auth login</code> or <code className='font-mono text-xs'>codex login</code>. PostRiff never asks for that password.
          </li>
          <li>Restart the PostRiff API. It looks for CLIs when it starts, so Check again alone will not find a newly installed one.</li>
        </ol>
      )}
    </Surface>
  );
}
