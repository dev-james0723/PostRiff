'use client';

import { useQuery } from '@tanstack/react-query';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { useGrowthCatalog } from './shared';

export function PerformanceFeedback({ jobId }: { jobId: string }) {
  const { api, workspaceId } = useWorkspaceApi();
  const catalog = useGrowthCatalog();
  const query = useQuery({
    queryKey: ['growth-feedback', workspaceId, jobId],
    queryFn: () => api.performanceFeedback(workspaceId, jobId),
    enabled: catalog.data?.postDoctor === true,
    retry: false
  });
  if (!catalog.data?.postDoctor) return null;
  return (
    <section
      className='rafii-quiet flex flex-col gap-3 rounded-xl p-4'
      aria-label='Observed performance feedback'
    >
      <h3 className='rafii-eyebrow'>Observed performance feedback</h3>
      {query.isPending && (
        <p className='text-muted-foreground text-sm'>Loading verified readings…</p>
      )}
      {query.isError && (
        <p role='alert' className='text-muted-foreground text-sm'>
          Performance feedback could not be loaded.
        </p>
      )}
      {query.data && (
        <>
          {query.data.prediction ? (
            <>
              <p className='text-muted-foreground text-xs'>
                Post Doctor advice for published revision {query.data.prediction.contentRevision}
              </p>
              <ul className='flex flex-wrap gap-x-4 gap-y-1 text-xs'>
                {query.data.prediction.levels.map((d) => (
                  <li key={d.id}>
                    {d.label}: {d.levelName}
                  </li>
                ))}
              </ul>
            </>
          ) : (
            <p className='text-muted-foreground text-sm'>
              This publication has no saved Post Doctor prediction.
            </p>
          )}
          {query.data.readings.map((reading) => (
            <div key={reading.horizon}>
              <h4 className='font-medium'>{reading.horizon} reading</h4>
              {reading.status !== 'observed' ? (
                <p className='text-muted-foreground text-sm'>
                  No verified reading for this window yet.
                </p>
              ) : (
                <dl className='mt-2 flex flex-col gap-2 text-sm'>
                  {Object.entries(reading.metrics).map(([metric, value]) => (
                    <div key={metric} className='flex flex-wrap justify-between gap-2'>
                      <dt className='capitalize'>{metric}</dt>
                      <dd>
                        {value.value === null ? 'Unavailable' : value.value.toLocaleString()}
                        {value.multiple != null
                          ? ` · ${value.multiple}× median of ${value.baselineCount} comparable posts`
                          : value.median === 0
                            ? ` · median is 0 across ${value.baselineCount} comparable posts; ratio unavailable`
                            : ` · ${value.baselineCount} comparable posts; baseline needs ${reading.minimumBaselinePosts}`}
                      </dd>
                    </div>
                  ))}
                </dl>
              )}
            </div>
          ))}
          {query.data.reason === 'publication_not_verified' && (
            <p className='text-muted-foreground text-sm'>
              Feedback begins after the publication is verified.
            </p>
          )}
          <p className='text-muted-foreground text-xs'>
            Comparisons use the same account, platform, format, language, time group and reading
            window. {query.data.notice}
          </p>
        </>
      )}
    </section>
  );
}
