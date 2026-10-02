/**
 * Pure Visual Pack presentation logic: English and Traditional Chinese copy, the one next step for a revision, finding
 * messages, reordering, the patch an edit sends, how unsaved edits survive a newer version, purged and cover states,
 * and server sentences in the person's language. Import-free (types only) so `node --test` loads it directly.
 */
import type { PackEditInput, PackFinding, PackSettings, PackSlide, PackState, PackWeight, SlidePatch, SourceStatus } from './visual-pack-types';

export type Lang = 'en' | 'zh-Hant';

const EN = {
  /** The copy's own language, for `lang` on the containers (and portals) that show it. */
  lang: 'en',
  title: 'Carousels',
  intro: 'Six-slide 1080×1350 carousels made from your drafts. Rafii renders the files; you post them yourself.',
  newCarousel: 'New carousel',
  chooseDraft: 'Choose a draft',
  chooseDraftHint: 'The carousel uses the draft’s own sentences: a hook, four points and a close. You can edit every slide.',
  noDrafts: 'Write a draft first: a carousel is made from its sentences.',
  make: 'Make carousel',
  making: 'Making…',
  empty: 'No carousels yet',
  emptyHint: 'Make one from a draft: six slides you can edit, render and download.',
  loadMore: 'Show more',
  loadError: 'Couldn’t load carousels',
  retry: 'Try again',
  version: 'Version {n}',
  slides: 'Slides',
  slide: 'Slide {n}',
  roles: { hook: 'Hook', point: 'Point', close: 'Close' },
  text: 'Text on the slide',
  altText: 'Alt text',
  altHint: 'Describes what the slide shows. It follows the slide’s text until you write your own.',
  image: 'Image',
  noImage: 'No image',
  moveUp: 'Move slide {n} up',
  moveDown: 'Move slide {n} down',
  dragHandle: 'Reorder slide {n}',
  palette: 'Palette',
  weight: 'Body text',
  weights: { regular: 'Regular', bold: 'Bold' },
  caption: 'Caption',
  save: 'Save as new version',
  saving: 'Saving…',
  unsaved: 'Unsaved changes. Saving makes a new version; earlier versions stay saved.',
  discard: 'Discard changes',
  render: 'Render slides',
  rendering: 'Rendering…',
  preview: 'The actual files',
  previewHint: 'These are the PNGs that will be exported, rendered on the server.',
  notRendered: 'Not rendered yet.',
  accept: 'Accept these six slides',
  acceptConfirm: 'I reviewed these six slides, their alt text and the caption.',
  export: 'Export files',
  exporting: 'Exporting…',
  download: 'Download files',
  downloading: 'Downloading…',
  confirmUsed: 'I posted these myself',
  confirmUsedHint: 'Confirm only after you posted them. Rafii can’t see or verify posts made outside it.',
  done: 'Recorded: you used these files.',
  checksOk: 'All checks passed',
  checksBlocked: '{n} to fix before rendering',
  sourceChanged: 'The draft changed after this carousel was made, so it can’t be accepted or exported until the slides match it.',
  resplit: 'Update slides from the draft',
  keep: 'Keep my slides',
  sourceGone: 'The draft this carousel came from was deleted, so it can’t be accepted or exported.',
  queueNote: 'Direct publishing isn’t available for six-image carousels yet. Export the files and post them yourself.',
  downloads: 'Downloaded {n}×',
  close: 'Close',
  purged: 'Files removed',
  purgedNote: 'An image on these slides was deleted from the Library, so the rendered files were removed. Replace or remove that image, save, and render again.',
  coverFailed: 'Couldn’t load the cover',
  conflictTitle: 'This carousel changed elsewhere: version {n} is the latest.',
  conflictBody: 'Your unsaved changes are still here. Keep them on top of version {n}, or load version {n} and discard them.',
  conflictNoMerge: 'Your unsaved changes are still here, but the slides were rebuilt from the draft, so they can’t be combined. Copy what you want to keep, then load version {n}.',
  keepMine: 'Keep my changes',
  loadLatest: 'Load version {n}',
  updatedElsewhere: 'This carousel changed elsewhere. Showing version {n}.',
  integrityTitle: 'The download didn’t match the recorded export.',
  integrityHint: 'Export again: Rafii checks the files once more from the stored slides and downloads them. If they still don’t match, edit the carousel to make a new version.',
  exportAgain: 'Export again and download',
  states: { draft: 'Draft', rendered: 'Rendered', accepted: 'Accepted', export_ready: 'Files ready', downloaded: 'Downloaded',
            user_confirmed_used: 'You posted it', queued: 'In Queue', superseded: 'Earlier version' } as Record<PackState, string>,
  /** The server's receipt for each state (English is shown as the server wrote it; see `receiptText`). */
  receipts: {
    draft: 'Draft: nothing is rendered, exported or published.',
    rendered: 'Six slides rendered for review. Nothing is exported or published.',
    accepted: 'Accepted. Export the files to post them yourself; nothing is published.',
    export_ready: 'Files ready to download. Rafii has not published anything.',
    downloaded: 'Downloaded. Rafii has not published anything; confirm here once you have posted it yourself.',
    user_confirmed_used: 'You confirmed you used these files. Rafii did not publish them and has not verified a post.',
    queued: 'Handed to Queue. Publication is confirmed only by Queue’s own receipt.',
    superseded: 'An earlier version: its acceptance and export no longer apply.'
  } as Record<PackState, string>,
  palettes: { rafii_light: 'Light', rafii_dark: 'Dark', rafii_violet: 'Violet', rafii_paper: 'Paper' } as Record<string, string>,
  findings: {
    empty_slide: 'Write text for this slide.',
    missing_glyphs: 'These characters can’t be drawn on a slide: {glyphs}. Remove or replace them.',
    needs_shorter_copy: 'Shorten this slide: it is about {lines} line(s) too long even at the smallest size (about {fit} characters fit).',
    missing_image: 'Its image was deleted from the Library. Choose another image or remove it.',
    alt_text_missing: 'Add alt text for this slide.',
    alt_text_differs: 'The alt text doesn’t include the slide’s text.',
    long_word_broken: 'A long word is split across lines with a hyphen: {words}.',
    generated_image_labelled: 'The image is labelled “{label}” on the slide.'
  } as Record<string, string>,
  dnd: {
    instructions: 'To reorder, press Space or Enter on a slide’s handle, move it with the arrow keys, then press Space or Enter again. Escape cancels.',
    picked: 'Picked up slide {n}.',
    over: 'Slide {n} is over position {to}.',
    dropped: 'Slide {n} dropped at position {to}.',
    cancelled: 'Reordering cancelled.'
  }
};

type Copy = typeof EN;

const ZH: Copy = {
  lang: 'zh-Hant',
  title: '輪播圖組',
  intro: '用你的草稿做成六張 1080×1350 的輪播圖。Rafii 產生檔案，由你自行發佈。',
  newCarousel: '新增輪播圖',
  chooseDraft: '選擇草稿',
  chooseDraftHint: '輪播圖使用草稿本身的句子：開場、四個重點和結尾。每一張都可以修改。',
  noDrafts: '請先寫一篇草稿：輪播圖會用它的句子製作。',
  make: '製作輪播圖',
  making: '製作中…',
  empty: '還沒有輪播圖',
  emptyHint: '從草稿製作：六張可編輯、可產生並下載的圖片。',
  loadMore: '顯示更多',
  loadError: '無法載入輪播圖',
  retry: '再試一次',
  version: '第 {n} 版',
  slides: '投影片',
  slide: '第 {n} 張',
  roles: { hook: '開場', point: '重點', close: '結尾' },
  text: '圖片上的文字',
  altText: '替代文字',
  altHint: '描述這張圖顯示的內容。在你自行修改前，會跟著圖上的文字更新。',
  image: '圖片',
  noImage: '不使用圖片',
  moveUp: '將第 {n} 張上移',
  moveDown: '將第 {n} 張下移',
  dragHandle: '調整第 {n} 張的順序',
  palette: '配色',
  weight: '內文字重',
  weights: { regular: '標準', bold: '粗體' },
  caption: '貼文文字',
  save: '另存為新版本',
  saving: '儲存中…',
  unsaved: '有未儲存的修改。儲存會建立新版本，舊版本會保留。',
  discard: '放棄修改',
  render: '產生圖片',
  rendering: '產生中…',
  preview: '實際檔案',
  previewHint: '這些是伺服器產生、將會匯出的 PNG 檔案。',
  notRendered: '尚未產生。',
  accept: '確認這六張圖',
  acceptConfirm: '我已檢查這六張圖、替代文字與貼文文字。',
  export: '匯出檔案',
  exporting: '匯出中…',
  download: '下載檔案',
  downloading: '下載中…',
  confirmUsed: '我已自行發佈',
  confirmUsedHint: '請在發佈後才確認。Rafii 無法看到或驗證在 Rafii 以外發佈的貼文。',
  done: '已記錄：你使用了這些檔案。',
  checksOk: '所有檢查都通過',
  checksBlocked: '產生前需要修正 {n} 項',
  sourceChanged: '這組輪播圖製作後，草稿已經改變；在投影片與草稿一致前，無法確認或匯出。',
  resplit: '依草稿更新投影片',
  keep: '保留我的投影片',
  sourceGone: '這組輪播圖的草稿已被刪除，因此無法確認或匯出。',
  queueNote: '六張圖的輪播目前無法直接發佈。請匯出檔案後自行發佈。',
  downloads: '已下載 {n} 次',
  close: '關閉',
  purged: '檔案已移除',
  purgedNote: '這組投影片用到的圖片已從媒體庫刪除，所以已產生的檔案被移除了。請更換或移除該圖片，儲存後再產生一次。',
  coverFailed: '無法載入封面',
  conflictTitle: '這組輪播圖已在別處更新：最新的是第 {n} 版。',
  conflictBody: '你未儲存的修改仍然保留。你可以把修改套用到第 {n} 版上，或載入第 {n} 版並放棄修改。',
  conflictNoMerge: '你未儲存的修改仍然保留，但投影片已依草稿重新拆分，無法合併。請先複製想保留的內容，再載入第 {n} 版。',
  keepMine: '保留我的修改',
  loadLatest: '載入第 {n} 版',
  updatedElsewhere: '這組輪播圖已在別處更新，現在顯示第 {n} 版。',
  integrityTitle: '下載的檔案與記錄的匯出不符。',
  integrityHint: '請重新匯出：Rafii 會用儲存的投影片再核對一次檔案，然後下載。如果仍然不符，請修改輪播圖以建立新版本。',
  exportAgain: '重新匯出並下載',
  states: { draft: '草稿', rendered: '已產生', accepted: '已確認', export_ready: '檔案已備妥', downloaded: '已下載',
            user_confirmed_used: '你已發佈', queued: '已排入佇列', superseded: '舊版本' },
  receipts: {
    draft: '草稿：尚未產生、匯出或發佈任何內容。',
    rendered: '六張投影片已產生，等待你檢查。尚未匯出或發佈任何內容。',
    accepted: '已確認。請匯出檔案後自行發佈；Rafii 不會發佈任何內容。',
    export_ready: '檔案已可下載。Rafii 沒有發佈任何內容。',
    downloaded: '已下載。Rafii 沒有發佈任何內容；你自行發佈後，請在這裡確認。',
    user_confirmed_used: '你已確認使用了這些檔案。Rafii 沒有發佈它們，也沒有核實任何貼文。',
    queued: '已交給佇列。只有佇列本身的回執才能確認已發佈。',
    superseded: '舊版本：它的確認和匯出已不再適用。'
  },
  palettes: { rafii_light: '淺色', rafii_dark: '深色', rafii_violet: '紫色', rafii_paper: '紙張' },
  findings: {
    empty_slide: '請為這張圖寫上文字。',
    missing_glyphs: '這些字元無法顯示在圖上：{glyphs}。請刪除或替換。',
    needs_shorter_copy: '請縮短這張圖的文字：即使用最小字級仍多出約 {lines} 行（大約可容納 {fit} 個字）。',
    missing_image: '它的圖片已從媒體庫刪除。請改選其他圖片或移除。',
    alt_text_missing: '請為這張圖加上替代文字。',
    alt_text_differs: '替代文字沒有包含圖上的文字。',
    long_word_broken: '過長的單字以連字號分行：{words}。',
    generated_image_labelled: '圖片在投影片上標示為「{label}」。'
  },
  dnd: {
    instructions: '要調整順序，請在投影片的拖曳把手上按空白鍵或 Enter，用方向鍵移動，再按一次空白鍵或 Enter。按 Esc 取消。',
    picked: '已拿起第 {n} 張。',
    over: '第 {n} 張目前在第 {to} 個位置上。',
    dropped: '第 {n} 張已放到第 {to} 個位置。',
    cancelled: '已取消調整順序。'
  }
};

/**
 * The person's formatting locale (profile or browser) decides (D-022): Traditional Chinese for zh-Hant, zh-TW, zh-HK,
 * zh-MO and Cantonese (yue), with any subtags, in any case; everything else (zh-Hans and zh-CN included) is English.
 * The same rule as the results and relationships copy, so one person sees one language across features.
 */
export function langFor(locale: string | null | undefined): Lang {
  return /^(zh-hant|zh-tw|zh-hk|zh-mo|yue)/.test((locale ?? '').toLowerCase()) ? 'zh-Hant' : 'en';
}

export function copyFor(locale: string | null | undefined): Copy {
  return langFor(locale) === 'zh-Hant' ? ZH : EN;
}

export function fill(template: string, values: Record<string, string | number>): string {
  return template.replace(/\{(\w+)\}/g, (match, key: string) => (key in values ? String(values[key]) : match));
}

export function findingMessage(finding: PackFinding, copy: Copy): string {
  const template = copy.findings[finding.code] ?? finding.code.replace(/_/g, ' ');
  return fill(template, {
    glyphs: (finding.glyphs ?? []).map((g) => (g.invisible ? g.codePoint : `${g.char} (${g.codePoint})`)).join(', '),
    lines: finding.excessLines ?? 1,
    fit: finding.suggestedMaxChars ?? 0,
    words: (finding.words ?? []).join(', '),
    label: finding.label ?? ''
  });
}

export type NextStep = 'unavailable' | 'reconcile' | 'save' | 'fix' | 'render' | 'accept' | 'export' | 'download' | 'confirm' | 'done';

/** The single next action for the revision on screen. Unsaved edits come first; a changed or missing draft blocks. */
export function nextStep(revision: { state: PackState; sourceStatus: SourceStatus; checks: { ok: boolean }; render: { available: boolean } | null }, dirty = false): NextStep {
  if (revision.sourceStatus === 'unavailable') return 'unavailable';
  if (dirty) return 'save';
  if (revision.sourceStatus === 'changed') return 'reconcile';
  if (!revision.checks.ok || (revision.render && !revision.render.available)) return 'fix';
  switch (revision.state) {
    case 'draft':
      return 'render';
    case 'rendered':
      return 'accept';
    case 'accepted':
      return 'export';
    case 'export_ready':
      return 'download';
    case 'downloaded':
      return 'confirm';
    case 'user_confirmed_used':
    case 'queued':
      return 'done';
    default:
      return 'fix';
  }
}

/** Move one key by `delta` places (keyboard Move up/down); out-of-range moves leave the order unchanged. */
export function moveKey(order: string[], key: string, delta: number): string[] {
  const from = order.indexOf(key);
  const to = from + delta;
  if (from < 0 || to < 0 || to >= order.length) return order;
  return moveTo(order, key, order[to]);
}

/** Drop `active` where `over` is (the drag-and-drop result). */
export function moveTo(order: string[], active: string, over: string): string[] {
  const from = order.indexOf(active);
  const to = order.indexOf(over);
  if (from < 0 || to < 0 || from === to) return order;
  const next = order.slice();
  next.splice(to, 0, next.splice(from, 1)[0]);
  return next;
}

export interface LocalSlide {
  key: string;
  text: string;
  altText: string;
  altCustom: boolean;
  imageAssetId: string | null;
}

export function localSlides(slides: PackSlide[]): LocalSlide[] {
  return slides.map((s) => ({ key: s.key, text: s.text, altText: s.altText, altCustom: s.altCustom, imageAssetId: s.imageAssetId }));
}

/** Only what changed, per slide. Alt text is sent only when the person wrote it, so the server keeps it in step otherwise. */
export function slidePatches(saved: PackSlide[], local: LocalSlide[]): SlidePatch[] {
  const before = new Map(saved.map((s) => [s.key, s]));
  const patches: SlidePatch[] = [];
  for (const slide of local) {
    const was = before.get(slide.key);
    if (!was) continue;
    const patch: SlidePatch = { key: slide.key };
    if (slide.text !== was.text) patch.text = slide.text;
    if (slide.altCustom && slide.altText !== was.altText) patch.altText = slide.altText;
    if (slide.imageAssetId !== was.imageAssetId) patch.imageAssetId = slide.imageAssetId;
    if (Object.keys(patch).length > 1) patches.push(patch);
  }
  return patches;
}

export function sameOrder(saved: PackSlide[], local: LocalSlide[]): boolean {
  return saved.length === local.length && saved.every((s, i) => s.key === local[i].key);
}

// --- unsaved edits across versions ---------------------------------------------------------------------------------------

/** What the editor lets a person change, as typed: the slides, caption, palette and weight. */
export interface LocalPack {
  slides: LocalSlide[];
  caption: string;
  palette: string;
  weight: PackWeight;
}

/** The editable content of one saved revision. */
export interface RevisionContent {
  slides: PackSlide[];
  caption: string;
  settings: PackSettings;
}

export function localPack(revision: RevisionContent): LocalPack {
  return { slides: localSlides(revision.slides), caption: revision.caption, palette: revision.settings.palette, weight: revision.settings.weight };
}

/** The edit request that turns `saved` into what the person typed: only what differs. Empty when nothing does. */
export function editInput(saved: RevisionContent, local: LocalPack): PackEditInput {
  const out: PackEditInput = {};
  const patches = slidePatches(saved.slides, local.slides);
  if (patches.length) out.slides = patches;
  if (!sameOrder(saved.slides, local.slides)) out.order = local.slides.map((s) => s.key);
  if (local.caption !== saved.caption) out.caption = local.caption;
  if (local.palette !== saved.settings.palette || local.weight !== saved.settings.weight) out.settings = { palette: local.palette, weight: local.weight };
  return out;
}

export function hasEdits(input: PackEditInput): boolean {
  return Object.keys(input).length > 0;
}

function keys(slides: { key: string }[]): string[] {
  return slides.map((s) => s.key);
}

function sameKeys(a: string[], b: string[]): boolean {
  return a.length === b.length && a.toSorted().join('\n') === b.toSorted().join('\n');
}

/**
 * The person's unsaved changes (made on `base`) carried onto a newer version `latest`: every field they changed keeps
 * their value, every field they didn't takes the newer version's, so nothing someone else saved is silently reverted.
 * Null when the newer version has a different set of slides (rebuilt from the draft): those can't be combined.
 */
export function rebase(base: RevisionContent, latest: RevisionContent, local: LocalPack): LocalPack | null {
  if (!sameKeys(keys(base.slides), keys(latest.slides)) || !sameKeys(keys(base.slides), keys(local.slides))) return null;
  const was = new Map(base.slides.map((s) => [s.key, s]));
  const now = new Map(latest.slides.map((s) => [s.key, s]));
  const mine = new Map(local.slides.map((s) => [s.key, s]));
  const order = sameOrder(base.slides, local.slides) ? keys(latest.slides) : keys(local.slides);
  const slides = order.map((key): LocalSlide => {
    const before = was.get(key) as PackSlide;
    const after = now.get(key) as PackSlide;
    const typed = mine.get(key) as LocalSlide;
    const ownAlt = typed.altCustom && typed.altText !== before.altText;
    return {
      key,
      text: typed.text !== before.text ? typed.text : after.text,
      imageAssetId: typed.imageAssetId !== before.imageAssetId ? typed.imageAssetId : after.imageAssetId,
      altText: ownAlt ? typed.altText : after.altText,
      altCustom: ownAlt ? true : after.altCustom
    };
  });
  return {
    slides,
    caption: local.caption !== base.caption ? local.caption : latest.caption,
    palette: local.palette !== base.settings.palette ? local.palette : latest.settings.palette,
    weight: local.weight !== base.settings.weight ? local.weight : latest.settings.weight
  };
}

// Python's str.strip() whitespace once control characters are gone: what the server trims from both ends.
const EDGE_SPACE = /^[\n \u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+|[\n \u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+$/g;
// oxlint-disable-next-line no-control-regex -- matching control characters is the point: the server removes them (Unicode Cc but the newline)
const CONTROL = /[\u0000-\u0009\u000b-\u001f\u007f-\u009f]/g;

/**
 * The server's text normalization for slide text, alt text and captions (`visual_pack/checks.py normalize_text`, without
 * its length check): NFC, Unix newlines, tabs as spaces, no other control characters, no spaces before a line break, at
 * most one blank line in a row, trimmed. What the person typed is saved as this.
 */
export function normalizeText(value: string): string {
  return value
    .normalize('NFC')
    .replace(/\r\n/g, '\n')
    .replace(/\r/g, '\n')
    .replace(/\t/g, ' ')
    .replace(CONTROL, '')
    .replace(/[ \u00a0]+\n/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .replace(EDGE_SPACE, '');
}

function normalized<T extends { slides: { text: string; altText: string }[]; caption: string }>(content: T): T {
  return { ...content, slides: content.slides.map((s) => ({ ...s, text: normalizeText(s.text), altText: normalizeText(s.altText) })), caption: normalizeText(content.caption) };
}

/** Whether `saved` already holds what the person typed, once the server's normalization is applied to both (M5). */
export function sameAsSaved(saved: RevisionContent, local: LocalPack): boolean {
  return !hasEdits(editInput(normalized(saved), normalized(local)));
}

export type Reconcile =
  | { kind: 'ignore' }
  | { kind: 'refresh' }
  | { kind: 'adopt'; notice: boolean }
  | { kind: 'conflict' };

/**
 * What the editor does when the server's view of the pack changes while it is open. An older version is ignored; the
 * same version (a new state) refreshes in place; a newer version is adopted when there are no unsaved edits (with a
 * notice unless it is the version this editor just saved) or when it already holds exactly what the person typed (their
 * own save landed). Otherwise it is a conflict: the edits stay and the person decides. "What the person typed" is
 * compared as the server saves it (trimmed, NFC, …), so their own save is never mistaken for a change made elsewhere.
 */
export function reconcile(base: RevisionContent & { revision: number }, next: RevisionContent & { revision: number }, local: LocalPack, ownRevision: number | null): Reconcile {
  if (next.revision < base.revision) return { kind: 'ignore' };
  if (next.revision === base.revision) return { kind: 'refresh' };
  if (sameAsSaved(base, local)) return { kind: 'adopt', notice: next.revision !== ownRevision };
  if (sameAsSaved(next, local)) return { kind: 'adopt', notice: false };
  return { kind: 'conflict' };
}

// --- purged files, covers, receipts --------------------------------------------------------------------------------------

/** A list item whose revision was rendered but whose files were removed (an image it used was deleted). */
export function isPurged(item: { state: PackState; rendered: boolean }): boolean {
  return !item.rendered && item.state !== 'draft' && item.state !== 'superseded';
}

/** The same for an open revision: its render exists but is no longer available. */
export function revisionPurged(revision: { facts: { purgedAt: number | null }; render: { available: boolean } | null }): boolean {
  return revision.facts.purgedAt !== null || (revision.render !== null && !revision.render.available);
}

/** The label a list item or revision shows: never "Files ready" once its files are gone. */
export function stateLabel(state: PackState, purged: boolean, copy: Copy): string {
  return purged ? copy.purged : copy.states[state];
}

export type CoverState = 'image' | 'loading' | 'failed' | 'purged' | 'not_rendered';

/** What a list item's cover shows: a removed or never-rendered cover is not a loading failure, and a failure is not "not rendered". */
export function coverState(item: { state: PackState; rendered: boolean; cover: string | null }, file: { hasUrl: boolean; failed: boolean }): CoverState {
  if (isPurged(item)) return 'purged';
  if (!item.cover) return 'not_rendered';
  if (file.failed) return 'failed';
  return file.hasUrl ? 'image' : 'loading';
}

/** The server's receipt for a state, in the person's language (English stays exactly as the server wrote it). */
export function receiptText(state: PackState, server: string, lang: Lang): string {
  return lang === 'en' ? server : ZH.receipts[state] ?? server;
}

export function paletteLabel(id: string, server: string, lang: Lang): string {
  return lang === 'en' ? server : ZH.palettes[id] ?? server;
}

// --- server sentences ----------------------------------------------------------------------------------------------------

/** The visual pack service's fixed sentences, in Traditional Chinese (keyed by the exact English the server sends). */
const ZH_SERVER: Record<string, string> = {
  'A Library image changed in storage. Replace it on the slide and render again.': '媒體庫中的一張圖片在儲存空間裡被更改了。請在投影片上更換它，再產生一次。',
  'A new order lists each of the six slides once.': '新的順序必須列出六張投影片各一次。',
  'A rendered slide no longer matches its recorded hash. Render the pack again.': '一張已產生的投影片與記錄的雜湊值不符。請重新產生這組投影片。',
  'A rendered slide file is missing or changed in storage. Edit the carousel to make a new version, then render, accept and export that version.':
    '儲存空間中有一張已產生的投影片遺失或被更改。請修改輪播圖以建立新版本，然後產生、確認並匯出該版本。',
  "These files can't be rebuilt exactly as they were exported. Edit the carousel to make a new version, then render, accept and export that version.":
    '這些檔案無法完全照匯出時的樣子重建。請修改輪播圖以建立新版本，然後產生、確認並匯出該版本。',
  'Accept this exact revision before exporting it.': '請先確認這個版本，再匯出。',
  'An image on these slides was deleted from the Library. Replace it and render again.': '這組投影片用到的圖片已從媒體庫刪除。請更換後再產生一次。',
  'An image on these slides was deleted from the Library. Replace or remove it.': '這組投影片用到的圖片已從媒體庫刪除。請更換或移除它。',
  'Choose a draft in this workspace.': '請選擇這個工作區中的草稿。',
  "Choose an image from this workspace's Library.": '請從這個工作區的媒體庫選擇圖片。',
  'Choose one of the offered palettes and weights.': '請從提供的配色和字重中選擇。',
  'Choose to keep the slides or update them from the draft.': '請選擇保留投影片，或依草稿更新。',
  'Confirm that you accept this exact revision.': '請確認你接受這個版本。',
  'Confirm that you posted these files yourself.': '請確認你已自行發佈這些檔案。',
  'Download the files before confirming you used them.': '請先下載檔案，再確認已使用。',
  "Each slide change names one of this pack's slides.": '每項修改都必須指向這組投影片中的一張。',
  'Every slide needs alt text.': '每張投影片都需要替代文字。',
  'Every slide needs text.': '每張投影片都需要文字。',
  'Export this revision before downloading it.': '請先匯出這個版本，再下載。',
  "Private media storage is not configured, so slides can't be rendered or exported here.": '這裡尚未設定私人媒體儲存空間，因此無法產生或匯出投影片。',
  'Render the slides before accepting them.': '請先產生投影片，再確認。',
  'Send at most six slide changes.': '最多只能修改六張投影片。',
  'Some slides have more text than fits at the smallest allowed size. Shorten those slides.': '有些投影片的文字即使用最小字級也放不下。請縮短這些投影片。',
  "Some slides use characters the slide font can't draw (for example emoji). Remove or replace them.": '有些投影片使用了字型無法顯示的字元（例如表情符號）。請刪除或替換。',
  'That pack revision does not exist.': '這個版本不存在。',
  'That slide does not exist.': '這張投影片不存在。',
  'That slide has no rendered file.': '這張投影片沒有已產生的檔案。',
  'That visual pack is not in this workspace.': '這組輪播圖不在這個工作區。',
  'The draft changed after this pack was made. Update the slides from the draft (or keep them) first.': '這組輪播圖製作後，草稿已經改變。請先依草稿更新投影片（或保留它們）。',
  "The draft this pack came from is gone, so the pack can't be accepted or exported.": '這組輪播圖的草稿已不存在，因此無法確認或匯出。',
  'The draft this pack came from is gone.': '這組輪播圖的草稿已不存在。',
  'The export no longer matches what was recorded. Export the pack again.': '匯出的檔案與記錄不符。請重新匯出。',
  'This draft has no text to turn into slides.': '這篇草稿沒有可以做成投影片的文字。',
  'This export belongs to an earlier version of the pack. Export the latest version.': '這份匯出屬於較舊的版本。請匯出最新版本。',
  'This feature is not available.': '此功能目前無法使用。',
  'This pack changed since you loaded it. Reload it and try again.': '載入後這組輪播圖已有更改。請重新載入再試。',
  'This pack changed while it was exporting. Reload it and try again.': '匯出期間這組輪播圖已有更改。請重新載入再試。',
  'This pack changed while it was rendering. Reload it and render the latest version.': '產生期間這組輪播圖已有更改。請重新載入，並產生最新版本。',
  'This request key was already used for a different edit.': '這個請求代碼已用於另一項修改。請再試一次。',
  'This request key was already used for a different pack.': '這個請求代碼已用於另一組輪播圖。請再試一次。',
  // The shared transport's own fallbacks (growth-v2/request.ts).
  'That did not work. Try again.': '操作未能完成，請再試一次。',
  'The workspace could not complete that request.': '工作區未能完成這個請求。',
  'Your session ended. Sign in again.': '你的登入已過期，請重新登入。'
};

/** Codes whose meaning is the same whatever sentence carries them (used when the sentence itself is not known). */
const ZH_CODES: Record<string, string> = {
  feature_disabled: '此功能目前無法使用。',
  revision_conflict: '這組輪播圖已有更改。請重新載入再試。',
  approval_expired: '這份匯出屬於較舊的版本。請匯出最新版本。',
  render_required: '請先產生投影片，再確認。',
  media_storage_not_configured: '這裡尚未設定私人媒體儲存空間，因此無法產生或匯出投影片。',
  idempotency_conflict: '這個請求代碼已被使用。請再試一次。',
  needs_shorter_copy: '有些投影片的文字放不下。請縮短這些投影片。',
  integrity_failed: '檔案與記錄的內容不符。'
};

/** A server error in the person's language: English exactly as sent; Chinese from the known sentences, then known codes,
 *  else the server's own sentence (a detail such as a render error is never replaced by a vaguer line). */
export function serverText(code: string | undefined, message: string, lang: Lang): string {
  if (lang === 'en') return message;
  return ZH_SERVER[message] ?? (code ? ZH_CODES[code] : undefined) ?? message;
}
