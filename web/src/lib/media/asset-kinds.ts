/**
 * What a Library asset is, derived exactly like the server's `asset_kinds.py` (chat-context SPEC §5.13, §7.6):
 * `kind` from `mime` (never a stored or client kind), `category` defaulting to `media`, readiness per kind.
 */

export type AssetKind = 'image' | 'video';

export interface AssetLike {
  mime?: string | null;
  category?: string | null;
  processing?: string | null;
  deleted?: boolean | null;
  deletionPending?: boolean | null;
}

const READY: Record<AssetKind, string> = { image: 'decoded', video: 'ready' };

export function kindOf(asset: AssetLike | null | undefined): AssetKind | null {
  if (!asset) return null;
  const mime = String(asset.mime ?? '').toLowerCase();
  // Records from before video existed carry no mime; every one of them is an image.
  if (!mime) return 'image';
  if (mime.startsWith('video/')) return 'video';
  if (mime.startsWith('image/')) return 'image';
  return null;
}

export function category(asset: AssetLike | null | undefined): string {
  return typeof asset?.category === 'string' && asset.category ? asset.category : 'media';
}

function live(asset: AssetLike | null | undefined): asset is AssetLike {
  return Boolean(asset) && !asset?.deleted && !asset?.deletionPending;
}

export function isReady(asset: AssetLike | null | undefined): boolean {
  const kind = kindOf(asset);
  return live(asset) && kind !== null && asset.processing === READY[kind];
}

/** Images a post can be scheduled with. Videos never are in Phase 1. */
export function isPostableImage(asset: AssetLike | null | undefined): boolean {
  return kindOf(asset) === 'image' && isReady(asset);
}

/** Photos and videos the Library lists; posters and frames live inside their video record. */
export function isLibraryAsset(asset: AssetLike | null | undefined): boolean {
  return live(asset) && kindOf(asset) !== null;
}

/** The first post-role photo of a draft that can still go out with a post: the default image when scheduling it. */
export function firstPostImageId(
  media: readonly { assetId: string; kind?: string; role?: string }[] | null | undefined,
  assets: readonly (AssetLike & { id: string })[]
): string | null {
  for (const item of media ?? []) {
    if (item.role !== 'post' || (item.kind && item.kind !== 'image')) continue;
    const asset = assets.find((candidate) => candidate.id === item.assetId);
    if (asset && isPostableImage(asset)) return asset.id;
  }
  return null;
}
