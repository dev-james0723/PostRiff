/**
 * What the ＋ picker and the `@` list offer, from the workspace snapshot alone (chat-context SPEC §4.3, §11.1): the web
 * twin of `site_agent.reads.picker_search`, with the same filters — posts not rejected; templates not archived and
 * the viewer's own or shared with the workspace; accounts not disconnected; folders with their connected members;
 * sources active, not voice samples, not prohibited; Library photos and videos that are ready. An empty query gives
 * recents (8 per group); a category alias switches to that group, a platform alias to that platform's accounts.
 * Pure: relative imports only (node --test transpiles it).
 */
import { isLibraryAsset, isReady, kindOf, type AssetLike } from '../../../lib/media/asset-kinds';
import { labelFor } from './chips';
import { rank, type PickerCategory, type PickerItemLike } from './matcher';

export const RECENTS = 8;

export const CATEGORY_ORDER: readonly PickerCategory[] = [
  'posts',
  'templates',
  'accounts',
  'folders',
  'sources',
  'library'
];

export interface PickerItem extends PickerItemLike {
  kind: 'post' | 'template' | 'account' | 'folder' | 'source' | 'image' | 'video';
  /** Accounts only: always "Connected" (disconnected ones are left out). */
  state?: string;
  duration?: number;
  width?: number;
  height?: number;
}

export interface PickerGroup {
  category: PickerCategory;
  items: PickerItem[];
}

export interface PickerResult {
  /** The group a category or platform alias switched to, or null. */
  category: PickerCategory | null;
  groups: PickerGroup[];
}

type Json = Record<string, unknown>;

interface SnapshotLike {
  state?: {
    variants?: unknown[];
    sources?: unknown[];
    contentTypes?: { templates?: unknown[]; catalog?: unknown[] } | null;
    contentSystem?: { templates?: unknown[] } | null;
    phase2?: {
      channels?: unknown[];
      channelFolders?: unknown[];
      assets?: unknown[];
      jobs?: unknown[];
      reviews?: unknown[];
    } | null;
  } | null;
}

function records(value: unknown): Json[] {
  return Array.isArray(value)
    ? value.filter((item): item is Json => Boolean(item) && typeof item === 'object')
    : [];
}

function text(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

/** When a post was last scheduled or reviewed (`manifest.timing.timestamp`), per variant id. */
function postActivity(phase2: NonNullable<SnapshotLike['state']>['phase2']): Map<string, number> {
  const seen = new Map<string, number>();
  for (const item of [...records(phase2?.jobs), ...records(phase2?.reviews)]) {
    const manifest = (item.manifest ?? {}) as Json;
    const variantId = text(item.variantId) || text(manifest.variantId);
    const at = Number(((manifest.timing ?? {}) as Json).timestamp) || 0;
    if (variantId) seen.set(variantId, Math.max(seen.get(variantId) ?? 0, at));
  }
  return seen;
}

/** Every item the viewer may add, newest first within each kind (before any query). */
export function allPickerItems(
  snapshot: SnapshotLike | null | undefined,
  principal: string | null | undefined
): PickerItem[] {
  const state = snapshot?.state ?? {};
  const phase2 = state.phase2 ?? {};
  const channels = records(phase2.channels);
  const byChannel = new Map(channels.map((channel) => [text(channel.id), channel]));
  const items: PickerItem[] = [];

  const activity = postActivity(phase2);
  records(state.variants).forEach((variant, index) => {
    const id = text(variant.id);
    if (!id || variant.rejected) return;
    const channel = variant.channelId ? byChannel.get(text(variant.channelId)) : undefined;
    const account = channel ? text(channel.account) : '';
    items.push({
      kind: 'post',
      id,
      label: labelFor('post', variant),
      sublabel: [text(variant.platform), account, text(variant.language)]
        .filter(Boolean)
        .join(' · '),
      platform: text(variant.platform) || undefined,
      updatedAt: activity.get(id) || index,
      search: [text(variant.text), account].filter(Boolean).join('\n')
    });
  });

  const typeLabels = new Map(
    records(state.contentTypes?.catalog).map((item) => [text(item.id), text(item.label)])
  );
  records(state.contentTypes?.templates ?? state.contentSystem?.templates).forEach(
    (template, index) => {
      const id = text(template.id);
      const visible =
        template.visibility === 'workspace' ||
        (Boolean(principal) && template.ownerUserId === principal);
      if (!id || template.archived || !visible) return;
      const typeLabel = typeLabels.get(text(template.contentTypeId)) || undefined;
      items.push({
        kind: 'template',
        id,
        label: labelFor('template', template),
        sublabel: typeLabel,
        updatedAt: index
      });
    }
  );

  channels.forEach((channel, index) => {
    const id = text(channel.id);
    if (!id || channel.revoked) return;
    items.push({
      kind: 'account',
      id,
      label: labelFor('account', channel),
      platform: text(channel.platform) || undefined,
      state: 'Connected',
      updatedAt: index,
      search: [text(channel.account), text(channel.platform)].filter(Boolean).join('\n')
    });
  });

  records(phase2.channelFolders).forEach((folder, index) => {
    const id = text(folder.id);
    if (!id) return;
    const members = (Array.isArray(folder.accountIds) ? folder.accountIds : []).filter(
      (accountId) => {
        const channel = byChannel.get(text(accountId));
        return Boolean(channel) && !channel?.revoked;
      }
    ).length;
    items.push({
      kind: 'folder',
      id,
      label: labelFor('folder', folder),
      sublabel: `${members} account${members === 1 ? '' : 's'}`,
      updatedAt: index
    });
  });

  records(state.sources).forEach((source, index) => {
    const id = text(source.id);
    if (
      !id ||
      !source.active ||
      source.kind === 'voice_sample' ||
      source.sourcePolicy === 'prohibited'
    )
      return;
    const approved = records(source.facts).filter((fact) => fact.approved).length;
    items.push({
      kind: 'source',
      id,
      label: labelFor('source', source),
      sublabel: `${approved} approved fact${approved === 1 ? '' : 's'}`,
      updatedAt: index
    });
  });

  records(phase2.assets).forEach((asset, index) => {
    const id = text(asset.id);
    const like = asset as AssetLike;
    if (!id || !isLibraryAsset(like) || !isReady(like)) return;
    const kind = kindOf(like);
    if (!kind) return;
    items.push({
      kind,
      id,
      label: kind === 'video' ? 'Video' : 'Photo',
      search: kind === 'video' ? 'video' : 'photo image',
      updatedAt: Number(asset.createdAt) || index,
      ...(kind === 'video'
        ? { duration: Number(asset.duration) || undefined }
        : { width: Number(asset.width) || undefined, height: Number(asset.height) || undefined })
    });
  });
  return items;
}

/** The groups for `query` (`@` text without the `@`, or the picker's search box), at most `limit` per group. */
export function pickerItems(
  snapshot: SnapshotLike | null | undefined,
  principal: string | null | undefined,
  query = '',
  limit = RECENTS
): PickerResult {
  const ranked = rank(query, allPickerItems(snapshot, principal));
  const groups = CATEGORY_ORDER.map((category) => ({
    category,
    items: ranked.items.filter((item) => KIND_GROUP[item.kind] === category).slice(0, limit)
  })).filter((group) => group.items.length > 0);
  return { category: ranked.category, groups };
}

const KIND_GROUP: Record<PickerItem['kind'], PickerCategory> = {
  post: 'posts',
  template: 'templates',
  account: 'accounts',
  folder: 'folders',
  source: 'sources',
  image: 'library',
  video: 'library'
};

/** The flat order the `@` list shows: groups in `CATEGORY_ORDER`, best first within each. */
export function flatten(result: PickerResult): PickerItem[] {
  return result.groups.flatMap((group) => group.items);
}
