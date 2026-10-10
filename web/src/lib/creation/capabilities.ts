/**
 * The creation-capability facet (`GET /api/ideas/models` → `creation`, schema `rafii.creation-capabilities.v1`).
 *
 * The server owns the projection and validates every turn against it; the browser only reads it to decide what to
 * offer. Nothing here authorizes anything: a platform the facet does not list as draftable is never offered, and a
 * missing or malformed facet offers the original five platforms only (it never widens the list).
 */

export const CREATION_SCHEMA = 'rafii.creation-capabilities.v1';
/** The flag-off drafting set; mirrors `creation_capabilities.ORIGINAL_PLATFORMS` (a Python test checks the copy). */
export const ORIGINAL_PLATFORMS = ['LinkedIn', 'Instagram', 'Threads', 'Xiaohongshu', 'X'] as const;

export type OperationState = 'ready' | 'needs_input' | 'unavailable' | 'blocked' | 'unknown';

export interface OperationStatus {
  state: OperationState;
  reason: string;
  detail: string;
}

export interface NativeFormat {
  id: string;
  mediaKind: 'optional' | 'image' | 'video' | 'document' | string;
  nativeFields: string[];
  draftFields: string[];
  bindingFields: string[];
  media: OperationStatus;
  constraints: { verified: boolean; note?: string };
}

export interface CreationPlatform {
  platform: string;
  id: string;
  labelKey: string;
  original: boolean;
  skill: { id: string; version: string | null; sha256: string | null; registryVersion: string | null; required: string[] };
  formats: NativeFormat[];
  defaultFormat: string | null;
  limits: { verified: boolean; characters: number | null; version: string | null; note?: string };
  operations: Record<'draft' | 'media' | 'export' | 'connect' | 'publish' | 'analytics' | 'learning', OperationStatus>;
  qualification: { code: string; modelRoute: string; production: string; evidence: string };
}

export interface CreationCatalog {
  schema: string;
  revision: string;
  registryRelease: string | null;
  rollout: { waves: string[] };
  originalPlatforms: string[];
  draftable: string[];
  platforms: CreationPlatform[];
}

function valid(catalog: unknown): catalog is CreationCatalog {
  const c = catalog as CreationCatalog | null | undefined;
  return Boolean(c && c.schema === CREATION_SCHEMA && typeof c.revision === 'string' && Array.isArray(c.draftable) && Array.isArray(c.platforms));
}

/** Platforms the composer may offer, in the original order first. Falls back to the original five. */
export function draftableFrom(catalog: unknown): string[] {
  if (!valid(catalog)) return [...ORIGINAL_PLATFORMS];
  const ready = new Set(catalog.platforms.filter((p) => p.operations?.draft?.state === 'ready').map((p) => p.platform));
  const listed = catalog.draftable.filter((p) => ready.has(p));
  const originals = ORIGINAL_PLATFORMS.filter((p) => listed.includes(p) || !ready.size);
  return [...originals, ...listed.filter((p) => !(ORIGINAL_PLATFORMS as readonly string[]).includes(p))];
}

/** The revision a turn sends back so the server can refuse a stale list (`schema_revision_mismatch`). */
export function revisionOf(catalog: unknown): string | undefined {
  return valid(catalog) ? catalog.revision : undefined;
}

export function platformRow(catalog: unknown, platform: string): CreationPlatform | undefined {
  return valid(catalog) ? catalog.platforms.find((p) => p.platform === platform) : undefined;
}

/**
 * Whether the review shows native-draft facts: only while a creation wave is on, so a deployment with every flag off
 * looks exactly as it did before (the facts arrive with the rollout they describe). A missing facet shows none.
 */
export function reviewFactsEnabled(catalog: unknown): boolean {
  return valid(catalog) && Array.isArray(catalog.rollout?.waves) && catalog.rollout.waves.length > 0;
}

/** Native formats of a platform the composer can offer (none when the facet is unavailable). */
export function formatsFor(catalog: unknown, platform: string): NativeFormat[] {
  const row = platformRow(catalog, platform);
  return row && row.operations.draft.state === 'ready' ? row.formats : [];
}

const FORMAT_WORDS: Record<string, string> = {
  post: 'Post', page_post: 'Page post', carousel: 'Carousel', story: 'Story', reel: 'Reel', video: 'Video', short: 'Short',
  community_post: 'Community post', thread: 'Thread', reply: 'Reply', note: 'Note', document: 'Document', article: 'Article',
  answer: 'Answer', idea: 'Idea', pin: 'Pin', message: 'Message', forum_post: 'Forum post', poll: 'Poll', status: 'Status',
  update: 'Update', event: 'Event', offer: 'Offer', broadcast: 'Broadcast', photo: 'Photo', album: 'Album', spotlight: 'Spotlight',
  community_message: 'Group message'
};

/** "instagram.carousel" → "Carousel"; "qzone.post" → "Qzone post" (the prefix shows only when it names another surface). */
export function formatLabel(platform: string, formatId: string): string {
  const [surface, kind = ''] = formatId.split('.');
  const word = FORMAT_WORDS[kind] ?? kind.replace(/_/g, ' ');
  const slug = platform.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
  const sameSurface = surface === slug || slug.split('-').includes(surface) || slug.startsWith(surface) || surface.startsWith(slug.split('-')[0]);
  return sameSurface ? word : `${surface.charAt(0).toUpperCase()}${surface.slice(1)} ${word.toLowerCase()}`;
}

/** What a format still needs before it is more than copy (shown beside the format, never hidden). */
export function mediaNote(format: NativeFormat): string | null {
  if (format.mediaKind === 'video') return 'Needs your video · Rafii writes the script';
  if (format.mediaKind === 'image') return 'Needs an image';
  if (format.mediaKind === 'document') return 'Needs a document';
  return null;
}

/** Destinations with the chosen native format added (omitted for the platform default, so old payloads are unchanged). */
export function withFormats<D extends { platform: string; channelId?: string }>(destinations: D[], chosen: Record<string, string>, catalog: unknown): (D & { format?: string })[] {
  return destinations.map((d) => {
    const format = chosen[d.channelId ?? d.platform];
    const row = platformRow(catalog, d.platform);
    if (!format || !row || format === row.defaultFormat || !row.formats.some((f) => f.id === format)) return d;
    return { ...d, format };
  });
}

// -- review facts ---------------------------------------------------------------------------------------
/**
 * What a review shows beside one native draft (Content Skills A29): the exact destination, the native format, whether
 * the platform's writing instructions reached the writer, what media the format still needs, and whether Rafii can
 * publish it. Read-only: every value comes from the draft the server wrote (`rafii.native-draft.v1`); nothing here
 * checks or grants a connection, an approval or a publish.
 */

export interface NativeSkillRoute {
  qualified: boolean;
  generic?: boolean;
  missing?: string[];
  cut?: boolean;
}

export interface NativeDraft {
  schema?: string;
  platform?: string;
  formatId?: string;
  unresolved?: string[];
  missingContent?: string[];
  media?: { required?: string; state?: string; reason?: string };
  constraints?: { verified?: boolean };
  readiness?: { draft?: string; export?: string; publish?: string; publishNote?: string };
  skillRoute?: NativeSkillRoute | null;
}

export type FactTone = 'neutral' | 'attention';

export interface DraftFact {
  key: 'destination' | 'format' | 'writing' | 'media' | 'publish' | 'limits';
  label: string;
  value: string;
  tone: FactTone;
}

const BINDING_WORDS: Record<string, string> = {
  page_ref: 'Facebook Page', board_ref: 'board', subreddit: 'subreddit', chat_ref: 'chat', channel_ref: 'channel',
  group_ref: 'group', location_ref: 'location', official_account_ref: 'official account', destination_url: 'link',
  did: 'account DID', pds: 'data server'
};

function bindingWord(name: string): string {
  return BINDING_WORDS[name] ?? name.replace(/_ref$/, '').replaceAll('_', ' ');
}

const MEDIA_WORDS: Record<string, string> = {
  video: 'Needs your video · Rafii wrote the script, not a video',
  image: 'Needs an image',
  document: 'Needs a document'
};

/**
 * Facts in display order. `connected` is whether the workspace has a connection on this platform (the caller knows;
 * `undefined` when it doesn't). A draft without a native record (older or formatless) gets the destination only.
 */
export function draftFacts(variant: { platform: string; account?: string; channelId?: string; native?: NativeDraft | null }, connected?: boolean): DraftFact[] {
  const native = variant.native && typeof variant.native === 'object' ? variant.native : null;
  const facts: DraftFact[] = [];
  const unresolved = native?.unresolved ?? [];
  const account = variant.account
    ? variant.account
    : connected === false
      ? `No ${variant.platform} account connected · draft, copy and export only`
      : 'Not written for a specific account';
  facts.push({ key: 'destination', label: 'Account', value: account, tone: variant.account ? 'neutral' : 'attention' });
  if (!native) return facts;
  if (native.formatId) facts.push({ key: 'format', label: 'Format', value: formatLabel(variant.platform, native.formatId), tone: 'neutral' });
  const route = native.skillRoute;
  if (route) {
    facts.push(
      route.qualified
        ? { key: 'writing', label: 'Writing guide', value: `${variant.platform} guide applied in full`, tone: 'neutral' }
        : {
            key: 'writing',
            label: 'Writing guide',
            value: `Unverified generic draft · ${route.cut ? 'the guide was cut short' : `missing ${(route.missing ?? []).length || 'some'} required instruction${(route.missing ?? []).length === 1 ? '' : 's'}`}`,
            tone: 'attention'
          }
    );
  } else {
    facts.push({ key: 'writing', label: 'Writing guide', value: 'Not recorded for this draft', tone: 'attention' });
  }
  const media = native.media;
  if (media && media.required && media.required !== 'optional') {
    const attached = media.state === 'attached_unvalidated';
    facts.push({ key: 'media', label: 'Media', value: attached ? 'Attached · not yet checked against the format' : (MEDIA_WORDS[media.required] ?? 'Needs media'), tone: attached ? 'neutral' : 'attention' });
  }
  const publish = native.readiness?.publish;
  const missingPlace = unresolved.map(bindingWord);
  const publishValue =
    publish === 'export_only'
      ? 'Export only · Rafii can’t publish this format yet'
      : missingPlace.length
        ? `Needs ${missingPlace.slice(0, 3).join(', ')}${missingPlace.length > 3 ? ` and ${missingPlace.length - 3} more` : ''} before publishing`
        : connected === false
          ? `Connect ${variant.platform} to publish`
          : 'Not checked · publishing runs the live account and approval checks';
  facts.push({ key: 'publish', label: 'Publishing', value: publishValue, tone: publish === 'export_only' || missingPlace.length || connected === false ? 'attention' : 'neutral' });
  if (native.constraints && native.constraints.verified === false) {
    facts.push({ key: 'limits', label: 'Limits', value: 'Platform limits for this format are unverified', tone: 'neutral' });
  }
  return facts;
}
