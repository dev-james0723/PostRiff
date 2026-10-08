'use client';
/**
 * Multi-step task progress (lane E; J01 J02 J05 J08) from `task_progress`: every step with its real state, what it waits
 * for and why it is open. A step reads "Done" only when the server's step state is done (only the tool that did the work
 * marks it so); a failed multi-step request keeps its completed steps and names the unfinished ones.
 */
import { useJourneyEnvironment } from '../../journeys/runtime';
import { Pill, QueryFrame, type Tone } from './shared';
import type { JourneyRendererProps } from './types';

const TONE: Record<string, Tone> = { done: 'good', running: 'waiting', planned: 'muted', needs_user: 'waiting', blocked: 'attention', failed: 'attention', canceled: 'muted' };

export function TaskProgress({ props }: JourneyRendererProps) {
  const { copy } = useJourneyEnvironment();
  return (
    <QueryFrame value={props.data} binding='task_progress' label={copy.tasks.title} title={copy.tasks.title}>
      {(data) => {
        const task = data.task;
        if (!task) return <p className='text-muted-foreground text-sm'>{copy.states.empty}</p>;
        const labels = new Map(task.steps.map((s) => [s.id, s.label]));
        const done = task.steps.filter((s) => s.state === 'done').length;
        return (
          <div className='flex flex-col gap-2'>
            {task.title ? <p className='text-sm font-medium'>{task.title}</p> : null}
            <p className='text-muted-foreground text-xs' role='status'>
              {copy.tasks.doneOf(done, task.steps.length)}
            </p>
            <ol className='flex flex-col gap-1.5'>
              {task.steps.map((step, index) => (
                <li key={step.id} className='flex flex-col gap-0.5 rounded-md border p-2 text-sm'>
                  <span className='flex flex-wrap items-center gap-2'>
                    <span className='text-muted-foreground tabular-nums'>{index + 1}.</span>
                    <span className='break-words'>{step.label}</span>
                    <Pill tone={TONE[step.state] ?? 'muted'}>{copy.tasks.state[step.state] ?? step.state}</Pill>
                    {step.state === 'done' && step.verified ? <span className='text-muted-foreground text-xs'>{copy.tasks.verifiedByTool}</span> : null}
                  </span>
                  {step.dependsOn && step.dependsOn.length > 0 ? (
                    <span className='text-muted-foreground text-xs'>
                      {copy.tasks.dependsOn}: {step.dependsOn.map((d) => labels.get(d) ?? d).join(', ')}
                    </span>
                  ) : null}
                  {step.reason && step.state !== 'done' ? <span className='text-muted-foreground text-xs'>{step.reason}</span> : null}
                </li>
              ))}
            </ol>
          </div>
        );
      }}
    </QueryFrame>
  );
}
