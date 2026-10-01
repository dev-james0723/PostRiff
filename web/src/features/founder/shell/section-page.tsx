'use client';

import { Component, lazy, Suspense, useCallback, type ComponentType, type ErrorInfo, type LazyExoticComponent, type ReactNode } from 'react';
import PageContainer from '@/components/layout/page-container';
import { Icons } from '@/components/icons';
import { StateMessage } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { FOUNDER_SECTIONS, type RoutedSectionId } from '@/config/founder-nav';
import { founderPanelStore } from '@/features/founder/agent/store';
import { SECTIONS, type FounderAskRequest, type FounderSectionProps } from '@/features/founder/sections';
import { useFounderPageContext, type FounderPageRegistration } from '@/lib/founder/page-context';

/**
 * The `[section]` route body: the registered view (`features/founder/sections.ts`, filled by the domain pages) under
 * the shell's page column, or the "coming soon" state while a section's module is missing or fails to load. Each
 * view renders its own `PageHeader`; it receives `onAsk`, which hands a question and the page's context to the
 * Founder Rafii panel.
 */

/** Lazy components are created once per section so a re-render never re-suspends an already loaded page. */
const LOADED = new Map<RoutedSectionId, LazyExoticComponent<ComponentType<FounderSectionProps>>>();

function viewFor(section: RoutedSectionId) {
  const load = SECTIONS[section];
  if (!load) return null;
  let view = LOADED.get(section);
  if (!view) {
    view = lazy(load);
    LOADED.set(section, view);
  }
  return view;
}

/** What a page's Ask request contributes to the next turn's page context (chart ids become chart context). */
export function registrationFromAsk(request: FounderAskRequest): FounderPageRegistration {
  return {
    section: request.section,
    selectedEntity: request.selectedEntity ?? null,
    chart: request.chart ? { chartId: request.chart, viewVersion: 1 } : null,
    period: request.period ?? null,
    filters: request.filters ?? {},
    incidentId: request.incidentId ?? null
  };
}

export function ComingSoon({ section }: { section: RoutedSectionId }) {
  const meta = FOUNDER_SECTIONS[section];
  return (
    <StateMessage
      kind='empty'
      title={`${meta.title} is on its way`}
      description='This page is being built. Rafii already answers questions about it from the same records.'
      action={
        <Button type='button' variant='glass' onClick={() => founderPanelStore.ask(`What can you tell me about ${meta.title.toLowerCase()} right now?`, { section })} className='gap-1.5'>
          <Icons.sparkles className='size-4' aria-hidden /> Ask Rafii
        </Button>
      }
    />
  );
}

/**
 * A section whose module failed to load (not built yet, or a broken chunk) falls back to the coming-soon state. The
 * parent keys it by section, so moving to another section mounts a fresh boundary instead of carrying the failure.
 */
class SectionBoundary extends Component<{ section: RoutedSectionId; children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('Founder section failed to render', this.props.section, error, info.componentStack);
  }
  render() {
    return this.state.failed ? <ComingSoon section={this.props.section} /> : this.props.children;
  }
}

export function FounderSectionPage({ section }: { section: RoutedSectionId }) {
  const meta = FOUNDER_SECTIONS[section];
  useFounderPageContext({ section });
  const View = viewFor(section);
  const onAsk = useCallback((request: FounderAskRequest) => founderPanelStore.ask(request.prompt, registrationFromAsk(request)), []);
  return (
    <PageContainer>
      {View ? (
        <SectionBoundary key={section} section={section}>
          <Suspense fallback={<StateMessage kind='loading' title={`Opening ${meta.title}…`} />}>
            <View onAsk={onAsk} />
          </Suspense>
        </SectionBoundary>
      ) : (
        <ComingSoon section={section} />
      )}
    </PageContainer>
  );
}
