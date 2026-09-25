import { Icons } from '@/components/icons';
import { StateMessage, Surface } from '@/components/rafii';

/**
 * No CLI listed. Not an error: the built-in writers still write. `hosted` comes from the Memory
 * endpoint's research summary (the only hosting signal the web has today); null when it is unknown.
 * Hosted: a CLI would need the desktop companion, which does not exist yet, so there is nothing to do.
 * Self-run: the setup steps sit behind a disclosure for the person who runs the app.
 */
function CliSteps() {
  return (
    <ol className='text-muted-foreground mx-auto mt-2 flex max-w-md list-decimal flex-col gap-1.5 pl-5 text-left text-sm leading-relaxed'>
      <li>Install Claude Code or the Codex CLI on the computer that runs the app.</li>
      <li>
        Sign in there in Terminal with <code className='font-mono text-xs'>claude auth login</code> or <code className='font-mono text-xs'>codex login</code>. We never ask for that password.
      </li>
      <li>Restart the app, then press Check again.</li>
    </ol>
  );
}

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
        title='No CLI connected'
        description={hosted === true ? 'Using your own CLI isn’t available yet. The built-in writers below still work.' : 'The built-in writers below still work.'}
        className='bg-transparent p-0'
      />
      {hosted !== true && (
        <details className='mx-auto w-full max-w-md text-sm'>
          <summary className='rafii-focus text-foreground -mx-1 inline-flex min-h-9 cursor-pointer items-center rounded-md px-1 font-medium'>How to add a CLI</summary>
          <CliSteps />
        </details>
      )}
    </Surface>
  );
}
