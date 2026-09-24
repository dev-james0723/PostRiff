import { KBarResults, useMatches } from 'kbar';
import { StateMessage } from '@/components/rafii';
import ResultItem from './result-item';

export default function RenderResults() {
  const { results, rootActionId } = useMatches();

  if (!results.length) {
    return (
      <div className='flex h-full items-center justify-center px-5 text-center'>
        <StateMessage kind='empty' layout='inline' title='No results found.' />
      </div>
    );
  }

  return (
    <KBarResults
      items={results}
      onRender={({ item, active }) =>
        typeof item === 'string' ? (
          <div className='rafii-eyebrow px-5 pt-3 pb-1.5'>{item}</div>
        ) : (
          <ResultItem action={item} active={active} currentRootActionId={rootActionId ?? ''} />
        )
      }
    />
  );
}
