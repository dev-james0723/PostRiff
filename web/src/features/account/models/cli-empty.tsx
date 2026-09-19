import { Icons } from '@/components/icons';
import { Card, CardContent } from '@/components/ui/card';
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty';

/**
 * No CLI listed. Not an error: the preview still writes. `hosted` comes from the Memory endpoint's
 * research summary (the only deployment signal the web has today); null when it is unknown.
 */
export function CliEmpty({ hosted }: { hosted: boolean | null }) {
  return (
    <Card data-tour='models-empty'>
      <CardContent>
        <Empty className='p-2'>
          <EmptyHeader>
            <EmptyMedia variant='icon'>
              <Icons.terminal />
            </EmptyMedia>
            <EmptyTitle>No CLI writer on this deployment</EmptyTitle>
            <EmptyDescription>
              {hosted === true
                ? 'A CLI you already pay for will run through a desktop companion on your own computer. That is not available yet; the writers under PostRiff are what write here today.'
                : 'You can keep drafting with the writers under PostRiff. To add a coding CLI you already pay for:'}
            </EmptyDescription>
          </EmptyHeader>
          {hosted !== true && (
            <ol className='text-muted-foreground flex list-decimal flex-col gap-1 pl-5 text-left text-sm'>
              <li>Install Claude Code or the Codex CLI on the machine that serves the PostRiff API.</li>
              <li>
                Sign in there in Terminal with <code className='font-mono text-xs'>claude auth login</code> or <code className='font-mono text-xs'>codex login</code>. PostRiff never asks for that password.
              </li>
              <li>Restart the PostRiff API. It looks for CLIs when it starts, so Check again alone will not find a newly installed one.</li>
            </ol>
          )}
        </Empty>
      </CardContent>
    </Card>
  );
}
