/**
 * Voice import: what the browser reads out of a platform export, and what the workspace routes exchange
 * (docs/integrated-brand-intelligence-20261125/ENGINEERING-SPEC.md §5.1). Export files never leave the device;
 * only `ExportItem` records do.
 */

export type ExportProvider = 'instagram' | 'facebook' | 'threads' | 'x' | 'linkedin' | 'mastodon';
export type ExportKind = 'original' | 'reply' | 'quote' | 'repost';

/** One picked file. `name` keeps the folder path when a folder was picked, which is how a layout generation is told apart. */
export interface ExportFile {
  name: string;
  text: string;
}

/** A normalised post record. `kind` is set only where the export states it. */
export interface ExportItem {
  externalId: string;
  text: string;
  publishedAt?: string;
  permalink?: string;
  kind?: ExportKind;
}

/** Why a recognised file gave fewer posts than the person expected. Shown as a sentence; never a thrown error. */
export type ExportNote = 'not_json' | 'unknown_shape';

export interface ParsedExport {
  provider: ExportProvider;
  layout: string;
  items: ExportItem[];
  /** Sent with the upload so the coverage receipt stays truthful: entries the parser could not read, and entries with no text. */
  skipped: { unsupported: number; empty: number };
  /** Counted for the person only and never sent: posts that are not public, and boosts that carry no writing of their own. */
  local: { notPublic: number; reposts: number };
  notes: ExportNote[];
}

/** Every file of one platform in one upload. */
export interface CombinedExport extends ParsedExport {
  files: number;
}

/* ---------- workspace routes ---------- */

export type ImportRoute = 'official_api' | 'platform_export';
export type ImportStatus = 'pending' | 'receiving' | 'running' | 'done' | 'failed' | 'cancelled';
export type Ownership = 'mine' | 'my_organisation' | 'mixed_authors';
export type VoiceScope = 'brand' | 'separate';
/** ISO 8601 text or epoch seconds; the locale formatter accepts both. */
export type Stamp = string | number | null;

export interface ImportCounts {
  discovered?: number;
  retrieved?: number;
  duplicates?: number;
  excluded?: number;
  unsupported?: number;
  failed?: number;
}

export interface VoiceImport {
  id: string;
  route: ImportRoute;
  provider: string;
  connectionId?: string | null;
  accountKey: string;
  accountLabel?: string | null;
  status: ImportStatus;
  consent?: { ownership?: Ownership; voiceScope?: VoiceScope; at?: Stamp };
  requestedSince?: Stamp;
  observed?: { oldest?: Stamp; newest?: Stamp } | null;
  counts?: ImportCounts;
  pages?: number;
  /** `null` while the platform has not said whether more posts exist. */
  moreRemaining?: boolean | null;
  totalKnown?: boolean;
  failure?: string | null;
  retryAt?: Stamp;
  lastSyncAt?: Stamp;
  createdAt?: Stamp;
  updatedAt?: Stamp;
}

export interface CoverageAccount {
  provider: string;
  accountKey: string;
  label?: string | null;
  route?: string | null;
  voiceScope?: VoiceScope;
  retrieved?: number;
  eligible?: number;
  excluded?: Record<string, number | undefined>;
  languages?: Record<string, number | undefined>;
  observed?: { oldest?: Stamp; newest?: Stamp } | null;
  moreRemaining?: boolean | null;
  totalKnown?: boolean;
}

export type CoverageStateId = 'connected' | 'retrieved' | 'processed' | 'proposed' | 'approved';

export interface VoiceCoverage {
  /** The route does not fix the value type of a state, so each is read tolerantly (`coverageStates`). */
  states?: Partial<Record<CoverageStateId, unknown>>;
  accounts?: CoverageAccount[];
  modality?: { text?: string; images?: string; video?: string };
}

export interface ImportRouteRow {
  provider: string;
  official?: { available?: boolean; reason?: string | null } | null;
  export?: { available?: boolean; files?: string[]; reason?: string | null } | null;
}

/** One voice group: the brand, or an account kept separate. Present only when the route lists groups. */
export interface VoiceGroup {
  key: string;
  label?: string;
  eligible?: number;
}

export interface VoiceAnalysis {
  id?: string;
  status?: 'queued' | 'running' | 'done' | 'failed' | 'cancelled' | 'blocked' | string;
  groupKey?: string;
  eligible?: number;
  analysed?: number;
  failure?: string | null;
}

export interface VoiceImportsView {
  imports: VoiceImport[];
  coverage: VoiceCoverage;
  routes: ImportRouteRow[];
  analysis?: VoiceAnalysis | null;
  groups?: VoiceGroup[];
}

export type PostAuthorship = 'self' | 'team' | 'guest' | 'unknown';
export type PostLabel = 'representative' | 'outdated' | 'aspirational';

export interface VoicePost {
  id: string;
  provider: string;
  accountKey: string;
  publishedAt?: Stamp;
  permalink?: string | null;
  /** At most 280 characters, for display to workspace members. Never written back into workspace state. */
  excerpt: string;
  language?: string;
  originality?: 'original' | 'reply' | 'quote' | 'repost' | 'unknown' | string;
  authorship?: PostAuthorship | string;
  generationOrigin?: 'rafii_published' | 'unknown' | string;
  label?: PostLabel | null;
  status?: 'retrieved' | 'eligible' | 'excluded' | 'gone' | string;
  exclusionReason?: string | null;
}

export interface VoicePostPage {
  posts: VoicePost[];
  nextCursor?: string | null;
}

export interface ImportRequest {
  route: ImportRoute;
  provider: string;
  connectionId?: string;
  accountKey?: string;
  accountLabel?: string;
  consent: { ownership: Ownership; voiceScope: VoiceScope; confirmed: true };
  since?: string;
}

export interface ItemsBody {
  items: ExportItem[];
  /** The batch's place in the upload, from 1; a batch the route already has is counted once. */
  seq?: number;
  skipped?: { unsupported: number; empty: number };
  final?: boolean;
}

export interface PostCorrection {
  authorship?: PostAuthorship;
  label?: PostLabel | null;
  excluded?: boolean;
}
