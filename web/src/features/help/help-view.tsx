'use client';

/**
 * Rafii help: the same versioned articles Rafii cites in its answers, served by the API from one corpus
 * (site agent spec §7). A citation opens the exact section it came from.
 */
import Link from 'next/link';
import { useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import PageContainer from '@/components/layout/page-container';
import { Icons } from '@/components/icons';
import { StateMessage, Surface } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { siteConfig } from '@/config/site';
import { RichText } from '@/features/site-agent/answer';
import { panelStore } from '@/features/site-agent/store';
import { useSiteAgentPageContext } from '@/features/site-agent/use-page-context';
import { ApiError } from '@/lib/api/client';
import { useWorkspaceApi } from '@/lib/workspace/provider';

const GROUPS: { type: string; label: string }[] = [
  { type: 'product_help', label: 'Using Rafii' },
  { type: 'workflow_playbooks', label: 'How work flows' },
  { type: 'capability_explanations', label: 'What each account can do' },
  { type: 'troubleshooting', label: 'When something is stuck' }
];

export function HelpIndexView() {
  const { api, workspaceId } = useWorkspaceApi();
  const catalogue = useQuery({ queryKey: ['help', workspaceId], queryFn: () => api.helpCatalogue(workspaceId as string), enabled: Boolean(workspaceId), staleTime: 10 * 60_000 });
  return (
    <PageContainer pageTitle='Help' pageDescription={`How ${siteConfig.name} works, from the same articles ${siteConfig.name} cites in its answers.`} width='reading'>
      {catalogue.isLoading ? (
        <Skeleton className='h-48 w-full' />
      ) : catalogue.error ? (
        <StateMessage kind='error' title='Help could not be loaded.' description={catalogue.error instanceof ApiError ? catalogue.error.message : undefined} action={<Button variant='glass' onClick={() => void catalogue.refetch()}>Try again</Button>} />
      ) : (
        <div className='flex flex-col gap-6'>
          {GROUPS.map((group) => {
            const docs = (catalogue.data?.documents ?? []).filter((d) => d.sourceType === group.type);
            if (!docs.length) return null;
            return (
              <section key={group.type} aria-labelledby={`help-${group.type}`} className='flex flex-col gap-2'>
                <h2 id={`help-${group.type}`} className='rafii-eyebrow'>
                  {group.label}
                </h2>
                <Surface material='glass' padding='none'>
                  <ul className='divide-y divide-[color-mix(in_oklch,var(--foreground)_6%,transparent)]'>
                    {docs.map((doc) => (
                      <li key={doc.documentId}>
                        <Link href={`/app/help/${doc.documentId}`} className='rafii-focus hover:rafii-quiet flex min-h-14 items-center justify-between gap-3 px-4 py-3'>
                          <span className='flex min-w-0 flex-col'>
                            <span className='text-sm font-medium'>{doc.title}</span>
                            {doc.summary && <span className='text-muted-foreground text-xs'>{doc.summary}</span>}
                          </span>
                          <Icons.chevronRight className='size-4 shrink-0' aria-hidden />
                        </Link>
                      </li>
                    ))}
                  </ul>
                </Surface>
              </section>
            );
          })}
          <p className='text-muted-foreground text-xs'>Articles version {catalogue.data?.productVersion} · snapshot {catalogue.data?.snapshot}</p>
        </div>
      )}
    </PageContainer>
  );
}

export function HelpArticleView({ documentId }: { documentId: string }) {
  const { api, workspaceId } = useWorkspaceApi();
  const doc = useQuery({ queryKey: ['help', workspaceId, documentId], queryFn: () => api.helpDocument(workspaceId as string, documentId), enabled: Boolean(workspaceId), staleTime: 10 * 60_000, retry: false });
  useSiteAgentPageContext({ selectedEntity: { type: 'help_document', id: documentId } });

  // Citations link to a section; scroll there once the article is on screen.
  useEffect(() => {
    if (!doc.data || typeof window === 'undefined' || !window.location.hash) return;
    document.getElementById(decodeURIComponent(window.location.hash.slice(1)))?.scrollIntoView({ block: 'start' });
  }, [doc.data]);

  if (doc.isLoading) {
    return (
      <PageContainer pageTitle='Help' width='reading'>
        <Skeleton className='h-64 w-full' />
      </PageContainer>
    );
  }
  if (doc.error || !doc.data) {
    return (
      <PageContainer pageTitle='Help' width='reading'>
        <StateMessage
          kind={doc.error instanceof ApiError && doc.error.status === 404 ? 'empty' : 'error'}
          title={doc.error instanceof ApiError && doc.error.status === 404 ? 'This help article does not exist.' : 'The article could not be loaded.'}
          action={<Link href='/app/help' className='rafii-focus text-sm font-medium underline underline-offset-2'>All help articles</Link>}
        />
      </PageContainer>
    );
  }
  const article = doc.data;
  return (
    <PageContainer pageTitle={article.title} pageEyebrow='Help' pageDescription={article.summary ?? undefined} width='reading'
      pageHeaderAction={<Button variant='glass' size='sm' onClick={() => panelStore.ask(`About “${article.title}”: `)}>Ask {siteConfig.name} about this</Button>}>
      <article className='flex flex-col gap-6'>
        {article.sections.map((section) => (
          <section key={section.anchor} id={section.anchor} aria-labelledby={`${section.anchor}-title`} className='scroll-mt-20 flex flex-col gap-2'>
            {section.heading !== 'Overview' && (
              <h2 id={`${section.anchor}-title`} className='text-base font-semibold'>
                {section.heading}
              </h2>
            )}
            <RichText text={section.text} />
          </section>
        ))}
        <p className='text-muted-foreground text-xs'>
          Owner: {article.owner} · effective {article.effectiveFrom} · version {article.productVersion}
        </p>
        <Link href='/app/help' className='rafii-focus text-sm font-medium underline underline-offset-2'>
          All help articles
        </Link>
      </article>
    </PageContainer>
  );
}
