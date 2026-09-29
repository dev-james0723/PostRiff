'use client';

import { useEffect, useId } from 'react';
import type { PageOutlineItem, SiteAgentPageContext } from '@/lib/site-agent/types';
import { panelStore } from './store';

/**
 * A page tells Rafii what is selected on it (an id the server re-reads, never the object) and a few plain
 * view values. The route itself comes from the address. Registered while the page (or panel) is mounted;
 * `null` registers nothing.
 */
export function useSiteAgentPageContext(context: Pick<SiteAgentPageContext, 'selectedEntity' | 'visibleState'> | null) {
  const id = useId();
  const key = JSON.stringify(context ?? null);
  useEffect(() => {
    panelStore.register(id, JSON.parse(key));
    return () => panelStore.register(id, null);
  }, [id, key]);
}

/**
 * What the panel can do with an answer (docs/design/rafii-live-agent/CONTRACTS.md, Contract 2): open a page, show
 * help and run a guided walkthrough. A voice call can also be controlled (`voice`), so only its requests declare it.
 * The server answers with a plain link or sentence for anything not declared.
 */
export const UI_CAPABILITIES = ['navigate', 'show_help', 'guide', 'activate_control'] as const;
export const VOICE_UI_CAPABILITIES = [...UI_CAPABILITIES, 'voice'] as const;

/** The page context a turn carries: the route, what the page registered, and what the screen shows. */
export function currentPageContext(route: string, { voice = false }: { voice?: boolean } = {}): SiteAgentPageContext {
  const registered = panelStore.get().page;
  let outline: PageOutlineItem[] = [];
  try {
    outline = readPageOutline(document);
  } catch {
    /* the outline is a hint; the turn goes without it */
  }
  return {
    route,
    selectedEntity: registered?.selectedEntity ?? null,
    visibleState: registered?.visibleState ?? {},
    uiCapabilities: [...(voice ? VOICE_UI_CAPABILITIES : UI_CAPABILITIES)],
    ...(outline.length ? { outline } : {})
  };
}

/* -------------------------------------------------------------------------- */
/* Page outline (Contract 3): the labels on screen, never what was typed.       */
/* -------------------------------------------------------------------------- */

export const OUTLINE_MAX_ITEMS = 40;
export const OUTLINE_MAX_CHARS = 3000;
const TEXT_MAX = 80;

/** The little of a DOM node the outline reads, so a test can hand it a fake tree. */
export interface OutlineNode {
  /** 1: element, 3: text. */
  nodeType: number;
  /** Elements: the tag name ("BUTTON"). */
  tagName?: string;
  /** Text nodes: the text. */
  nodeValue?: string | null;
  childNodes: ArrayLike<OutlineNode>;
  getAttribute?(name: string): string | null;
}

export interface OutlineOptions {
  /** Whether an element is rendered; the page checks CSS and layout, tests pass a predicate. */
  visible?: (node: OutlineNode) => boolean;
  /** Elements to leave out with everything inside them (the app's own header, Rafii's panel). */
  skip?: (node: OutlineNode) => boolean;
  /** Resolves `aria-labelledby` ids. */
  byId?: (id: string) => OutlineNode | null;
  maxItems?: number;
  maxChars?: number;
}

type Role = PageOutlineItem['role'];
type State = NonNullable<PageOutlineItem['state']>;

/** Never read: code, media, form fields and their values, and anything a person types into. */
const SKIPPED_TAGS = new Set(['SCRIPT', 'STYLE', 'TEMPLATE', 'NOSCRIPT', 'SVG', 'CANVAS', 'IFRAME', 'OBJECT', 'EMBED', 'VIDEO', 'AUDIO', 'IMG', 'PICTURE', 'INPUT', 'TEXTAREA', 'SELECT', 'OPTION', 'DATALIST']);
const VALUE_ROLES = new Set(['textbox', 'searchbox', 'combobox', 'spinbutton', 'slider', 'listbox', 'option', 'log', 'marquee', 'timer']);
const BUTTON_ROLES = new Set(['button', 'switch', 'checkbox', 'radio', 'menuitem', 'menuitemcheckbox', 'menuitemradio']);

/**
 * Labels that read like orders to an assistant are left out: a post, a comment or a file name on screen is data,
 * never an instruction (the server drops them too).
 */
const INSTRUCTION_LIKE = [
  /\b(ignore|disregard|forget|override)\b[^.!?\n]{0,40}\b(instructions?|prompts?|rules|guidelines|messages?|above|previous|prior)\b/i,
  /\b(system|developer)\s+(prompt|message|instructions?)\b/i,
  /\byou\s+are\s+(now|no\s+longer)\b/i,
  /\b(act|behave|pretend)\s+as\b/i,
  /\bnew\s+instructions?\b/i,
  /\bdo\s+not\s+follow\b/i,
  /^\s*(system|assistant|user)\s*:/i,
  /<\/?\s*(system|assistant|user|instructions?)\s*>/i,
  /(忽略|無視|无视|不要理會|不要理会).{0,12}(指示|指令|提示|規則|规则)/,
  /(你現在是|你现在是|扮演)/
];

export function looksLikeInstruction(text: string): boolean {
  return INSTRUCTION_LIKE.some((pattern) => pattern.test(text));
}

function attr(node: OutlineNode, name: string): string | null {
  return typeof node.getAttribute === 'function' ? node.getAttribute(name) : null;
}

function tag(node: OutlineNode): string {
  return (node.tagName ?? '').toUpperCase();
}

function clean(text: string): string {
  const flat = text.replace(/\s+/g, ' ').trim();
  return flat.length > TEXT_MAX ? `${flat.slice(0, TEXT_MAX - 1).trimEnd()}…` : flat;
}

/** Left out with everything inside it. */
function excluded(node: OutlineNode, options: OutlineOptions): boolean {
  if (SKIPPED_TAGS.has(tag(node))) return true;
  if (attr(node, 'data-private') !== null || attr(node, 'hidden') !== null || attr(node, 'inert') !== null) return true;
  if (attr(node, 'aria-hidden') === 'true') return true;
  if (attr(node, 'type') === 'password') return true;
  const editable = attr(node, 'contenteditable');
  if (editable !== null && editable !== 'false') return true;
  if (VALUE_ROLES.has(attr(node, 'role') ?? '')) return true;
  if (options.skip?.(node)) return true;
  return options.visible ? !options.visible(node) : false;
}

function roleOf(node: OutlineNode): Role | null {
  const role = attr(node, 'role');
  const name = tag(node);
  if (role === 'dialog' || role === 'alertdialog' || name === 'DIALOG') return 'dialog';
  if (role === 'heading' || /^H[1-6]$/.test(name)) return 'heading';
  if (role === 'tab') return 'tab';
  if (role && BUTTON_ROLES.has(role)) return 'button';
  if (role === 'link') return 'link';
  if (role === 'status' || role === 'alert') return 'status';
  if (role) return null;
  if (name === 'BUTTON' || name === 'SUMMARY') return 'button';
  if (name === 'A' && attr(node, 'href') !== null) return 'link';
  if (name === 'OUTPUT') return 'status';
  return null;
}

function stateOf(node: OutlineNode, role: Role): State | undefined {
  const selected = attr(node, 'aria-selected') === 'true' || attr(node, 'aria-pressed') === 'true' || attr(node, 'aria-current') === 'page';
  if (role === 'tab' && selected) return 'selected';
  if (attr(node, 'disabled') !== null || attr(node, 'aria-disabled') === 'true') return 'disabled';
  if (attr(node, 'aria-checked') === 'true') return 'checked';
  if (selected) return 'selected';
  if (attr(node, 'aria-expanded') === 'true') return 'expanded';
  return undefined;
}

/** Visible text inside a node, stopping once it is too long to be a label. `controls` false leaves controls out. */
function textOf(node: OutlineNode, options: OutlineOptions, controls = true, budget = TEXT_MAX * 4): string {
  const parts: string[] = [];
  let length = 0;
  const walk = (current: OutlineNode) => {
    for (const child of Array.from(current.childNodes)) {
      if (length > budget) return;
      if (child.nodeType === 3) {
        const value = child.nodeValue ?? '';
        parts.push(value);
        length += value.length;
      } else if (child.nodeType === 1 && !excluded(child, options)) {
        const role = roleOf(child);
        if (!controls && role && role !== 'heading') continue;
        walk(child);
      }
    }
  };
  walk(node);
  return parts.join(' ').replace(/\s+/g, ' ').trim();
}

/** A label from `aria-label` or `aria-labelledby`, if the node has one. */
function ariaName(node: OutlineNode, options: OutlineOptions): string {
  const label = attr(node, 'aria-label')?.trim();
  if (label) return label;
  const ids = attr(node, 'aria-labelledby');
  if (!ids || !options.byId) return '';
  return ids
    .split(/\s+/)
    .map((id) => options.byId?.(id) ?? null)
    .filter((found): found is OutlineNode => found !== null)
    .map((found) => textOf(found, options))
    .join(' ')
    .trim();
}

/** The first heading inside a node (not inside a control). */
function firstHeading(node: OutlineNode, options: OutlineOptions, depth = 0): OutlineNode | null {
  if (depth > 6) return null;
  for (const child of Array.from(node.childNodes)) {
    if (child.nodeType !== 1 || excluded(child, options)) continue;
    const role = roleOf(child);
    if (role === 'heading') return child;
    if (role) continue;
    const found = firstHeading(child, options, depth + 1);
    if (found) return found;
  }
  return null;
}

function hasControls(node: OutlineNode, options: OutlineOptions, depth = 0): boolean {
  if (depth > 12) return false;
  return Array.from(node.childNodes).some((child) => {
    if (child.nodeType !== 1 || excluded(child, options)) return false;
    const role = roleOf(child);
    if (role && role !== 'heading') return true;
    return hasControls(child, options, depth + 1);
  });
}

/**
 * The outline of what is on screen: headings, buttons (with their state), tabs, links, status lines and the
 * `data-tour` regions guides point at, in page order. Roots are read in order (an open dialog before `main`), every
 * text is at most 80 characters, and the list stops at 40 items or about 3,000 characters. Input values, anything
 * under `[data-private]`, password fields, hidden elements and instruction-like labels never appear.
 */
export function buildPageOutline(roots: readonly (OutlineNode | null | undefined)[], options: OutlineOptions = {}): PageOutlineItem[] {
  const maxItems = options.maxItems ?? OUTLINE_MAX_ITEMS;
  const maxChars = options.maxChars ?? OUTLINE_MAX_CHARS;
  const items: PageOutlineItem[] = [];
  const seen = new Set<string>();
  const named = new Set<OutlineNode>();
  const rootSet = new Set(roots.filter((root): root is OutlineNode => Boolean(root)));
  let chars = 0;
  let full = false;

  const push = (role: Role, raw: string, target: string | null, state?: State) => {
    const text = clean(raw);
    if (!text || looksLikeInstruction(raw)) return;
    const item: PageOutlineItem = { role, text, ...(target ? { target: target.slice(0, TEXT_MAX) } : {}), ...(action ? { action: action.slice(0, TEXT_MAX) } : {}), ...(state ? { state } : {}) };
    const key = `${item.role}|${item.text}|${item.target ?? ''}|${item.state ?? ''}`;
    if (seen.has(key)) return;
    // Counted as sent: the item's JSON and its comma.
    const size = JSON.stringify(item).length + 1;
    if (items.length >= maxItems || chars + size > maxChars) {
      full = true;
      return;
    }
    seen.add(key);
    chars += size;
    items.push(item);
  };

  const visit = (node: OutlineNode, root: OutlineNode) => {
    if (full || node.nodeType !== 1) return;
    if (node !== root && rootSet.has(node)) return; // an open dialog inside main was read first
    if (excluded(node, options)) return;
    const role = roleOf(node);
    const target = attr(node, 'data-tour');
    const action = attr(node, 'data-rafii-action');
    if (role === 'dialog') {
      const heading = firstHeading(node, options);
      const name = ariaName(node, options) || (heading ? textOf(heading, options) : '');
      if (heading && name) named.add(heading);
      push('dialog', name || 'Dialog', target);
    } else if (role === 'status') {
      // A status line keeps its own words; the buttons inside it are listed on their own below.
      push('status', ariaName(node, options) || textOf(node, options, false), target);
    } else if (role) {
      if (!named.has(node)) push(role, ariaName(node, options) || textOf(node, options), target, stateOf(node, role));
      return; // a label: nothing inside it is listed separately
    } else if (target) {
      // A region guides point at: named by its label, its first heading, or its own words when they are short.
      let name = ariaName(node, options);
      if (!name) {
        const heading = firstHeading(node, options);
        if (heading) {
          name = textOf(heading, options);
          named.add(heading);
        } else if (!hasControls(node, options)) {
          const own = textOf(node, options, false, TEXT_MAX + 1);
          if (own.length <= TEXT_MAX) name = own;
        }
      }
      if (name) push('region', name, target);
    }
    for (const child of Array.from(node.childNodes)) visit(child, root);
  };

  for (const root of roots) if (root && !full) visit(root, root);
  return items;
}

/** Rafii's own surfaces are never part of the page it reads. */
const OWN_SURFACES = '#rafii-panel, [data-guide-overlay], [data-slot="tour-overlay"]';

/** The roots in reading order: open dialogs and sheets (the one on top first), then `main`. */
export function outlineRoots(doc: Pick<Document, 'querySelectorAll' | 'querySelector'>): Element[] {
  const dialogs = Array.from(doc.querySelectorAll('[role="dialog"], [role="alertdialog"], dialog[open]')).filter((el) => !el.closest(OWN_SURFACES));
  const main = doc.querySelector('main');
  return [...dialogs.toReversed(), ...(main ? [main] : [])];
}

function rendered(node: OutlineNode): boolean {
  const el = node as unknown as Element;
  if (typeof el.checkVisibility === 'function') {
    if (el.checkVisibility({ checkVisibilityCSS: true })) return true;
    // `display: contents` has no box of its own, yet its children render.
    return getComputedStyle(el).display === 'contents';
  }
  return el.getClientRects().length > 0;
}

/** The outline of the live page: open dialogs first, then `main` without the app's header bar. */
export function readPageOutline(doc: Document): PageOutlineItem[] {
  const main = doc.querySelector('main');
  return buildPageOutline(outlineRoots(doc) as unknown as OutlineNode[], {
    visible: rendered,
    skip: (node) => {
      const el = node as unknown as Element;
      return (el.tagName === 'HEADER' && el.parentElement === main) || el.matches(OWN_SURFACES);
    },
    byId: (id) => doc.getElementById(id) as unknown as OutlineNode | null
  });
}
