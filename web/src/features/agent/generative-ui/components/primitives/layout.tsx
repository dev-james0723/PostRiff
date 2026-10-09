'use client';
/**
 * Layout primitives: RafiiRoot, Stack, Grid, Section, Card, Tabs/TabItem, Accordion/AccordionItem, Text, EvidenceLink.
 * Containers key children by statement id; text is rendered as text (no HTML), with `dir="auto"` for RTL content.
 * Grids and rows respond to the width of the generated frame (container queries), so the same view works in the side
 * panel, the full chat and the expanded surface.
 */
import { type JSX, type ReactNode, useEffect, useId } from 'react';
import { z } from 'zod';
import { Tabs as TabsRoot, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { cn } from '@/lib/utils';
import { safeInAppPath } from '../../core/actions';
import type { RafiiComponentRenderer } from '../../core/component-types';
import { useGenUiLocale } from '../../core/locale';
import { useStateField } from '../../core/openui';
import { isElementLike, plainText, safeProps, type ElementLike } from '../../core/props';
import { getPath } from '../../core/query-data';
import { useGenUiRuntime } from '../../core/runtime-context';
import { Children, Unrenderable } from './shared';

const nodes = z.array(z.unknown());

const rootProps = z.object({ children: nodes, title: z.string().optional() });
export const RafiiRoot: RafiiComponentRenderer = ({ props, renderNode, statementId }) => {
  const p = safeProps(rootProps, props);
  const runtime = useGenUiRuntime();
  const children = p.ok ? p.value.children : [];
  const hasContent = children.some((child) => isElementLike(child) && child.typeName !== 'LoadingState');
  useEffect(() => {
    if (hasContent) runtime.onFirstComponent();
  }, [hasContent, runtime]);
  if (!p.ok) return <Unrenderable component="RafiiRoot" />;
  return (
    <div data-genui="RafiiRoot" data-statement-id={statementId} className="grid gap-4">
      {p.value.title ? (
        <h3 dir="auto" className="text-base font-semibold text-foreground">
          {plainText(p.value.title, 200)}
        </h3>
      ) : null}
      <Children value={children} renderNode={renderNode} />
    </div>
  );
};

const stackProps = z.object({
  children: nodes,
  direction: z.enum(['vertical', 'horizontal']).optional(),
  gap: z.enum(['sm', 'md', 'lg']).optional(),
});
const GAP = { sm: 'gap-2', md: 'gap-3', lg: 'gap-5' } as const;
export const Stack: RafiiComponentRenderer = ({ props, renderNode, statementId }) => {
  const p = safeProps(stackProps, props);
  if (!p.ok) return <Unrenderable component="Stack" />;
  const horizontal = p.value.direction === 'horizontal';
  return (
    <div
      data-genui="Stack"
      data-statement-id={statementId}
      className={cn('flex min-w-0', horizontal ? 'flex-row flex-wrap items-end' : 'flex-col', GAP[p.value.gap ?? 'md'])}
    >
      <Children value={p.value.children} renderNode={renderNode} />
    </div>
  );
};

const gridProps = z.object({ children: nodes, columns: z.number().optional() });
const COLUMNS: Record<number, string> = {
  1: 'grid-cols-1',
  2: 'grid-cols-1 @md:grid-cols-2',
  3: 'grid-cols-1 @md:grid-cols-2 @3xl:grid-cols-3',
  4: 'grid-cols-1 @md:grid-cols-2 @3xl:grid-cols-4',
};
export const Grid: RafiiComponentRenderer = ({ props, renderNode, statementId }) => {
  const p = safeProps(gridProps, props);
  if (!p.ok) return <Unrenderable component="Grid" />;
  const columns = Math.max(1, Math.min(4, Math.round(p.value.columns ?? 2)));
  return (
    <div data-genui="Grid" data-statement-id={statementId} className={cn('grid min-w-0 gap-3', COLUMNS[columns])}>
      <Children value={p.value.children} renderNode={renderNode} />
    </div>
  );
};

const sectionProps = z.object({ title: z.string(), children: nodes, description: z.string().optional() });
export const Section: RafiiComponentRenderer = ({ props, renderNode, statementId }) => {
  const p = safeProps(sectionProps, props);
  const id = useId();
  if (!p.ok) return <Unrenderable component="Section" />;
  return (
    <section data-genui="Section" data-statement-id={statementId} aria-labelledby={id} className="grid min-w-0 gap-2">
      <div className="grid gap-0.5">
        <h4 id={id} dir="auto" className="text-sm font-semibold text-foreground">
          {plainText(p.value.title, 200)}
        </h4>
        {p.value.description ? (
          <p dir="auto" className="text-xs text-muted-foreground">
            {plainText(p.value.description, 600)}
          </p>
        ) : null}
      </div>
      <Children value={p.value.children} renderNode={renderNode} />
    </section>
  );
};

const cardProps = z.object({
  children: nodes,
  title: z.string().optional(),
  description: z.string().optional(),
  tone: z.enum(['default', 'muted', 'highlight']).optional(),
});
export const Card: RafiiComponentRenderer = ({ props, renderNode, statementId }) => {
  const p = safeProps(cardProps, props);
  if (!p.ok) return <Unrenderable component="Card" />;
  const tone = p.value.tone ?? 'default';
  return (
    <div
      data-genui="Card"
      data-statement-id={statementId}
      className={cn(
        'grid min-w-0 gap-2 rounded-[var(--rafii-radius-card,0.875rem)] border p-3 @md:p-4',
        tone === 'default' && 'border-border bg-card text-card-foreground',
        tone === 'muted' && 'border-transparent bg-muted/50',
        tone === 'highlight' && 'border-primary/30 bg-primary/5',
      )}
    >
      {p.value.title ? (
        <h4 dir="auto" className="text-sm font-semibold">
          {plainText(p.value.title, 200)}
        </h4>
      ) : null}
      {p.value.description ? (
        <p dir="auto" className="text-xs text-muted-foreground">
          {plainText(p.value.description, 600)}
        </p>
      ) : null}
      <Children value={p.value.children} renderNode={renderNode} />
    </div>
  );
};

interface TabEntry {
  value: string;
  label: string;
  children: unknown;
  node: ElementLike;
}

function tabEntries(items: unknown[]): TabEntry[] {
  const seen = new Set<string>();
  const out: TabEntry[] = [];
  for (const item of items) {
    if (!isElementLike(item) || item.typeName !== 'TabItem') continue;
    const label = plainText(item.props.label, 80);
    if (!label) continue;
    let value = typeof item.props.value === 'string' && item.props.value ? item.props.value : label;
    while (seen.has(value)) value = `${value}_`;
    seen.add(value);
    out.push({ value, label, children: item.props.children, node: item });
  }
  return out;
}

const tabsProps = z.object({ items: z.array(z.unknown()), value: z.unknown().optional() });
export const Tabs: RafiiComponentRenderer = ({ props, renderNode, statementId }) => {
  const p = safeProps(tabsProps, props);
  const entries = tabEntries(p.ok ? p.value.items : []);
  const field = useStateField<string>(`tabs_${statementId ?? 'view'}`, p.ok ? (p.value.value as string | undefined) : undefined);
  if (!p.ok || !entries.length) return <Unrenderable component="Tabs" />;
  const current = typeof field.value === 'string' && entries.some((e) => e.value === field.value) ? field.value : entries[0].value;
  return (
    <div data-genui="Tabs" data-statement-id={statementId} className="min-w-0">
      <TabsRoot value={current} onValueChange={(next) => typeof next === 'string' && field.setValue(next)}>
        <div className="max-w-full overflow-x-auto">
          <TabsList>
            {entries.map((entry) => (
              <TabsTrigger key={entry.value} value={entry.value}>
                <span dir="auto">{entry.label}</span>
              </TabsTrigger>
            ))}
          </TabsList>
        </div>
        {entries.map((entry) => (
          <TabsContent key={entry.value} value={entry.value} className="grid gap-3 pt-2">
            <Children value={entry.children} renderNode={renderNode} />
          </TabsContent>
        ))}
      </TabsRoot>
    </div>
  );
};

const tabItemProps = z.object({ label: z.string(), children: nodes, value: z.string().optional() });
/** A TabItem outside Tabs renders as a plain titled group. */
export const TabItem: RafiiComponentRenderer = ({ props, renderNode, statementId }) => {
  const p = safeProps(tabItemProps, props);
  if (!p.ok) return <Unrenderable component="TabItem" />;
  return (
    <div data-genui="TabItem" data-statement-id={statementId} className="grid gap-2">
      <p dir="auto" className="text-sm font-semibold">
        {plainText(p.value.label, 80)}
      </p>
      <Children value={p.value.children} renderNode={renderNode} />
    </div>
  );
};

function AccordionPart(props: { title: string; open?: boolean; children: unknown; renderNode: (value: unknown) => ReactNode; statementId?: string }) {
  return (
    <details
      data-genui="AccordionItem"
      data-statement-id={props.statementId}
      open={props.open || undefined}
      className="group border-b border-border last:border-b-0"
    >
      <summary
        dir="auto"
        className="flex cursor-pointer list-none items-center justify-between gap-2 py-2.5 text-sm font-medium outline-none focus-visible:ring-3 focus-visible:ring-ring/50 [&::-webkit-details-marker]:hidden"
      >
        <span>{props.title}</span>
        <span aria-hidden="true" className="text-muted-foreground transition-transform group-open:rotate-180 motion-reduce:transition-none">
          ▾
        </span>
      </summary>
      <div className="grid gap-2 pb-3">
        <Children value={props.children} renderNode={props.renderNode} />
      </div>
    </details>
  );
}

const accordionProps = z.object({ items: z.array(z.unknown()) });
export const Accordion: RafiiComponentRenderer = ({ props, renderNode, statementId }) => {
  const p = safeProps(accordionProps, props);
  if (!p.ok) return <Unrenderable component="Accordion" />;
  const items = p.value.items.filter((item): item is ElementLike => isElementLike(item) && item.typeName === 'AccordionItem');
  return (
    <div data-genui="Accordion" data-statement-id={statementId} className="rounded-[var(--rafii-radius-card,0.875rem)] border border-border px-3">
      {items.map((item, index) => (
        <AccordionPart
          key={item.statementId ? `s:${item.statementId}` : `i:${index}`}
          title={plainText(item.props.title, 200)}
          open={item.props.open === true}
          renderNode={renderNode}
          statementId={item.statementId}
        >
          {item.props.children}
        </AccordionPart>
      ))}
    </div>
  );
};

const accordionItemProps = z.object({ title: z.string(), children: nodes, open: z.boolean().optional() });
export const AccordionItem: RafiiComponentRenderer = ({ props, renderNode, statementId }) => {
  const p = safeProps(accordionItemProps, props);
  if (!p.ok) return <Unrenderable component="AccordionItem" />;
  return (
    <AccordionPart title={plainText(p.value.title, 200)} open={p.value.open} renderNode={renderNode} statementId={statementId}>
      {p.value.children}
    </AccordionPart>
  );
};

const textProps = z.object({
  content: z.union([z.string(), z.number()]),
  variant: z.enum(['body', 'muted', 'heading', 'caption', 'emphasis']).optional(),
});
export const Text: RafiiComponentRenderer = ({ props, statementId }) => {
  const p = safeProps(textProps, props);
  if (!p.ok) return null;
  const text = plainText(p.value.content);
  if (!text) return null;
  const variant = p.value.variant ?? 'body';
  const common = { 'data-genui': 'Text', 'data-statement-id': statementId, dir: 'auto' as const };
  if (variant === 'heading') return <h4 {...common} className="text-sm font-semibold text-foreground">{text}</h4>;
  if (variant === 'emphasis') return <p {...common} className="text-sm font-medium text-foreground">{text}</p>;
  return (
    <p
      {...common}
      className={cn(
        'text-sm leading-relaxed whitespace-pre-line break-words',
        variant === 'muted' && 'text-muted-foreground',
        variant === 'caption' && 'text-xs text-muted-foreground',
      )}
    >
      {text}
    </p>
  );
};

/** https only for links that come from bound data; in-app paths stay in the app. */
export function safeLinkTarget(href: unknown): { href: string; external: boolean } | null {
  const origin = typeof window !== 'undefined' ? window.location.origin : null;
  const inApp = safeInAppPath(href, origin);
  if (inApp) return { href: inApp, external: false };
  if (typeof href !== 'string') return null;
  try {
    const url = new URL(href);
    if (url.protocol !== 'https:' || url.username || url.password) return null;
    return { href: url.toString(), external: true };
  } catch {
    return null;
  }
}

const linkProps = z.object({
  label: z.union([z.string(), z.number()]),
  href: z.unknown().optional(),
  source: z.union([z.string(), z.number()]).optional(),
  asOf: z.union([z.string(), z.number()]).optional(),
});
export const EvidenceLink: RafiiComponentRenderer = ({ props, statementId }) => {
  const p = safeProps(linkProps, props);
  const l = useGenUiLocale();
  if (!p.ok) return <Unrenderable component="EvidenceLink" />;
  const label = plainText(p.value.label, 300);
  const target = safeLinkTarget(typeof p.value.href === 'object' ? getPath(p.value.href, 'url') : p.value.href);
  const meta = [p.value.source ? plainText(p.value.source, 120) : '', p.value.asOf ? l.formatDate(p.value.asOf) : ''].filter(Boolean).join(' · ');
  return (
    <span data-genui="EvidenceLink" data-statement-id={statementId} className="inline-flex min-w-0 flex-wrap items-baseline gap-x-2 text-sm">
      {target ? (
        <a
          href={target.href}
          dir="auto"
          className="font-medium text-primary underline-offset-4 hover:underline focus-visible:rounded-sm focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none [.rafii-chat_&]:text-foreground"
          {...(target.external ? { target: '_blank', rel: 'noopener noreferrer nofollow', referrerPolicy: 'no-referrer' as const } : {})}
        >
          {label}
        </a>
      ) : (
        <span dir="auto" className="font-medium">
          {label}
          <span className="sr-only"> ({l.t('linkBlocked')})</span>
        </span>
      )}
      {meta ? <span className="text-xs text-muted-foreground">{meta}</span> : null}
    </span>
  );
};
