/**
 * Visual Pack API shapes (src/postriff_phase2/visual_pack/service.py, `rafii.visual-pack.v1`). The server is the
 * source of truth for every state, check and file; the browser edits and previews server-rendered PNGs only.
 */

export type PackState = 'draft' | 'rendered' | 'accepted' | 'export_ready' | 'downloaded' | 'user_confirmed_used' | 'queued' | 'superseded';
export type SlideRole = 'hook' | 'point' | 'close';
export type PackWeight = 'regular' | 'bold';
export type SourceStatus = 'current' | 'changed' | 'unavailable';
export type FindingSeverity = 'blocking' | 'warning' | 'info';

export interface GlyphFinding {
  char: string;
  codePoint: string;
  name: string | null;
  invisible: boolean;
}

export interface PackFinding {
  code: 'empty_slide' | 'missing_glyphs' | 'needs_shorter_copy' | 'missing_image' | 'alt_text_missing' | 'alt_text_differs' | 'long_word_broken' | 'generated_image_labelled' | (string & {});
  severity: FindingSeverity;
  glyphs?: GlyphFinding[];
  excessPx?: number;
  excessLines?: number;
  minimumSize?: number;
  suggestedMaxChars?: number;
  assetId?: string;
  words?: string[];
  label?: string;
}

export interface SlideCheck {
  position: number;
  key: string;
  role: SlideRole;
  ok: boolean;
  findings: PackFinding[];
  typography: { weight: PackWeight; size: number; lines: number } | null;
}

export interface PackChecks {
  definition: string;
  ok: boolean;
  blocking: number;
  warnings: number;
  safeArea: { top: number; bottom: number; sides: number };
  slides: SlideCheck[];
}

export interface PackSlide {
  position: number;
  role: SlideRole;
  key: string;
  text: string;
  altText: string;
  imageAssetId: string | null;
  plannedRole: string;
  altCustom: boolean;
}

export interface RenderedSlide {
  position: number;
  key: string;
  file: string;
  width: number;
  height: number;
  mime: string;
  bytes: number;
  sha256: string;
  altText: string;
  href: string;
}

export interface PackSettings {
  palette: string;
  weight: PackWeight;
}

export interface PackFacts {
  renderedAt: number | null;
  acceptedAt: number | null;
  exportReadyAt: number | null;
  downloadedAt: number | null;
  downloadCount: number;
  userConfirmedUsedAt: number | null;
  queuedAt: number | null;
  supersededAt: number | null;
  purgedAt: number | null;
}

export interface PackExport {
  handoff: 'assisted_export';
  sha256: string;
  bytes: number;
  href: string;
  filename: string;
}

export interface PackRevision {
  revision: number;
  state: PackState;
  current: boolean;
  createdAt: number;
  slides: PackSlide[];
  caption: string;
  settings: PackSettings;
  checks: PackChecks;
  sourceStatus: SourceStatus;
  contentDigest: string;
  approvalDigest: string | null;
  render: { renderDigest: string; renderedAt: number; available: boolean; renderer: Record<string, unknown>; slides: RenderedSlide[] } | null;
  facts: PackFacts;
  export: PackExport | null;
}

export interface PackPalette {
  id: string;
  label: string;
  background: string;
  text: string;
  accent: string;
}

export interface PackView {
  definitionVersion: string;
  dataState: 'available' | 'partial' | 'unavailable' | 'stale';
  asOf: number;
  pack: { id: string; language: string; currentRevision: number; createdAt: number; updatedAt: number; status: 'active' | 'archived'; format: string; source: { variantId: string | null; campaignId: string | null } };
  revision: PackRevision;
  receipt: string;
  handoff: {
    assistedExport: { available: boolean; state: PackState | null; nextStep: string };
    queue: { available: false; reason: string; channels: { channelId: string; platform: string; supported: boolean; reason: string }[] };
  };
  history: { revision: number; state: PackState; createdAt: number; supersededAt: number | null; rendered: boolean }[];
  options: { palettes: PackPalette[]; weights: PackWeight[]; slides: number; size: [number, number]; limits: { text: number; altText: number; caption: number } };
  replayed?: boolean;
  unchanged?: boolean;
  /** Export of an already-exported revision: the recorded files were checked again and still rebuild exactly (the
   *  recorded export can't change; when it no longer rebuilds the server answers integrity_failed: make a new version). */
  verified?: boolean;
}

export interface PackListItem {
  id: string;
  language: string;
  revision: number;
  state: PackState;
  rendered: boolean;
  title: string;
  createdAt: number;
  updatedAt: number;
  sourceStatus: SourceStatus;
  cover: string | null;
}

export interface PackList {
  items: PackListItem[];
  nextCursor: string | null;
  definitionVersion: string;
  dataState: 'available' | 'partial' | 'unavailable' | 'stale';
  asOf: number;
}

export interface SlidePatch {
  key: string;
  text?: string;
  altText?: string;
  imageAssetId?: string | null;
}

export interface PackEditInput {
  slides?: SlidePatch[];
  order?: string[];
  caption?: string;
  settings?: Partial<PackSettings>;
  source?: 'keep' | 'resplit';
}

export type PackAction = 'render' | 'accept' | 'export' | 'confirm-used';
