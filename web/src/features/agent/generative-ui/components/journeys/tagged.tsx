'use client';
/**
 * Wrap a journey renderer so its root carries `data-genui="<Name>"` and `data-statement-id` (the same hooks lane C's
 * primitives expose for tests, page-outline and focus return). `display: contents` keeps the layout of the component.
 */
import type { JourneyRenderer, JourneyRendererProps } from './types';

export function tagged(name: string, Inner: JourneyRenderer): JourneyRenderer {
  const Tagged = (input: JourneyRendererProps) => (
    <div className='contents' data-genui={name} data-statement-id={input.statementId ?? undefined}>
      <Inner {...input} />
    </div>
  );
  Tagged.displayName = `Journey(${name})`;
  return Tagged;
}
