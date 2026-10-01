/**
 * Pure Visual Pack presentation logic: English and Traditional Chinese copy, the one next step for a revision, finding
 * messages, reordering and the patch an edit sends. Import-free (types only) so `node --test` loads it directly.
 */
import type { PackFinding, PackSlide, PackState, SlidePatch, SourceStatus } from './visual-pack-types';

export type Lang = 'en' | 'zh-Hant';

const EN = {
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
  states: { draft: 'Draft', rendered: 'Rendered', accepted: 'Accepted', export_ready: 'Files ready', downloaded: 'Downloaded',
            user_confirmed_used: 'You posted it', queued: 'In Queue', superseded: 'Earlier version' } as Record<PackState, string>,
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
  states: { draft: '草稿', rendered: '已產生', accepted: '已確認', export_ready: '檔案已備妥', downloaded: '已下載',
            user_confirmed_used: '你已發佈', queued: '已排入佇列', superseded: '舊版本' },
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

/** The person's formatting locale (profile or browser) decides; Traditional Chinese for zh-Hant, zh-TW, zh-HK and zh-MO. */
export function langFor(locale: string | null | undefined): Lang {
  const value = (locale ?? '').toLowerCase();
  return /^zh-(hant|tw|hk|mo)\b/.test(value) || value === 'zh-hant' ? 'zh-Hant' : 'en';
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
