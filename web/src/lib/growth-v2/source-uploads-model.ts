/**
 * Pure presentation logic for source uploads (no React, no aliases: `node --test` loads it directly).
 * Copy is English and Traditional Chinese, chosen from the person's display language. States are said truthfully:
 * nothing is called "ready" or "created" unless the server says so, and an unknown provider outcome says its cost is
 * still pending instead of inviting a retry.
 */

export type Lang = 'en' | 'zh-Hant';
export type Tone = 'progress' | 'attention' | 'done' | 'error' | 'muted';

interface LimitsLike {
  limits: { audio: { maxBytes: number; maxSeconds: number }; pdf: { maxBytes: number; maxPages: number; maxCharacters: number } };
  formats: { pdf: { supported: boolean }; audio: { supported: boolean } };
}

interface ViewLike {
  kind: string;
  state: string;
  reason: string | null;
  next: string;
  objectState?: string;
  job: { state: string; reason: string | null; attempts: number; maxAttempts: number; kind?: string } | null;
}

export function languageFor(locale: string | null | undefined): Lang {
  const value = (locale ?? '').toLowerCase();
  return /^(zh-(hant|tw|hk|mo)|yue)/.test(value) ? 'zh-Hant' : 'en';
}

const EN = {
  title: 'Upload a PDF or recording',
  intro: 'Rafii reads the text, you check it, and only then does it become a source. Nothing is posted.',
  limitsPdf: (mb: string, pages: number, chars: string) => `PDF: up to ${mb}, ${pages} pages and ${chars} characters of text.`,
  limitsAudio: (mb: string, minutes: number) => `Audio: up to ${minutes} minutes and ${mb}. Transcribing uses credits; you see the cost first.`,
  audioOff: 'Audio transcription isn’t available yet. Upload a transcript (SRT, VTT or TXT) instead.',
  audioSynthetic: 'Test transcription route: transcripts here are synthetic.',
  pdfOff: 'PDF reading isn’t available right now.',
  choose: 'Choose a file',
  chooseHint: 'PDF, M4A, MP3, WAV, Ogg/Opus, or a transcript (SRT, VTT, TXT)',
  uploading: (percent: number) => `Uploading… ${percent}%`,
  checking: 'Checking the file…',
  reading: 'Reading the text…',
  cancel: 'Cancel',
  cancelUpload: 'Stop upload',
  remove: 'Delete file and text',
  refresh: 'Check again',
  recent: 'Recent uploads',
  stillWorking: 'Still working. Check again in a minute; nothing is lost if you leave.',
  reviewTitle: 'Check the text before it becomes a source',
  reviewHelp: 'Correct anything that was read or heard wrongly. Only statements from this text are used, with your approval.',
  untrusted: 'This text is treated as data. Rafii never follows instructions written inside it.',
  injection: (n: number) => `${n} instruction-like ${n === 1 ? 'passage was' : 'passages were'} found. They stay in the text as words and never become statements.`,
  characters: (n: string, max: string) => `${n} / ${max} characters`,
  claimsCapped: (limit: number) => `Rafii keeps the first ${limit} statements from a source. Trim the text to the part that matters, or choose fewer pages.`,
  claims: (n: number) => `${n} statement${n === 1 ? '' : 's'} found.`,
  emptyPages: (pages: string) => `No readable text on page${pages.includes(',') ? 's' : ''} ${pages} (scanned?).`,
  synthetic: 'Synthetic transcript (test route) — not a real recording.',
  save: 'Save changes',
  saved: 'Changes saved.',
  useAsSource: 'Use as source',
  sourceCreated: 'Source created. Its statements are approved and it’s in your idea bank.',
  openSource: 'Open source',
  quoteTitle: 'Transcribe this recording?',
  quoteBody: (seconds: string, usual: string, ceiling: string) => `This ${seconds} recording usually uses about ${usual} credits; Rafii holds up to ${ceiling} until it finishes and charges the real cost.`,
  quoteAvailable: (available: string) => `You have ${available} credits.`,
  quoteNotEnough: 'Not enough credits for this limit.',
  transcribe: 'Transcribe',
  upgrade: 'See plans',
  pagesTitle: 'Choose pages',
  pagesBody: (total: string, max: string, pages: number) => `This PDF has ${total} characters of text over ${pages} pages; the limit is ${max}. Choose a page range.`,
  pagesTooMany: (pages: number, max: number) => `This PDF has ${pages} pages; at most ${max} can be read at once. Choose a page range.`,
  from: 'From page',
  to: 'To page',
  readPages: 'Read these pages',
  transcriptHint: 'Transcript files become text to review, like a PDF.'
};

type Copy = typeof EN;

const ZH: Copy = {
  title: '上載 PDF 或錄音',
  intro: 'Rafii 會讀出文字，由你檢查確認後才會成為來源。不會發佈任何內容。',
  limitsPdf: (mb, pages, chars) => `PDF：最多 ${mb}、${pages} 頁及 ${chars} 個字元的文字。`,
  limitsAudio: (mb, minutes) => `錄音：最長 ${minutes} 分鐘、最多 ${mb}。轉錄會使用點數，開始前會先顯示費用。`,
  audioOff: '暫時未能轉錄錄音。請改為上載逐字稿（SRT、VTT 或 TXT）。',
  audioSynthetic: '測試轉錄路線：這裡的逐字稿是模擬內容。',
  pdfOff: '暫時未能讀取 PDF。',
  choose: '選擇檔案',
  chooseHint: 'PDF、M4A、MP3、WAV、Ogg/Opus，或逐字稿（SRT、VTT、TXT）',
  uploading: (percent) => `上載中… ${percent}%`,
  checking: '正在檢查檔案…',
  reading: '正在讀取文字…',
  cancel: '取消',
  cancelUpload: '停止上載',
  remove: '刪除檔案及文字',
  refresh: '再檢查一次',
  recent: '最近上載',
  stillWorking: '仍在處理中。請稍後再查看；離開此頁不會遺失任何內容。',
  reviewTitle: '成為來源前，請先檢查文字',
  reviewHelp: '請更正讀錯或聽錯的地方。只會使用這段文字中的陳述，並須經你批准。',
  untrusted: '這段文字只被視為資料。Rafii 不會執行其中寫下的任何指示。',
  injection: (n) => `發現 ${n} 段類似指令的內容。它們只會作為文字保留，不會成為陳述。`,
  characters: (n, max) => `${n} / ${max} 個字元`,
  claimsCapped: (limit) => `每個來源最多保留首 ${limit} 項陳述。請刪減至重要部分，或選擇較少頁數。`,
  claims: (n) => `找到 ${n} 項陳述。`,
  emptyPages: (pages) => `第 ${pages} 頁沒有可讀文字（可能是掃描檔）。`,
  synthetic: '模擬逐字稿（測試路線）— 並非真實錄音。',
  save: '儲存更改',
  saved: '已儲存更改。',
  useAsSource: '用作來源',
  sourceCreated: '已建立來源。其陳述已獲批准，並已加入你的點子庫。',
  openSource: '打開來源',
  quoteTitle: '要轉錄這段錄音嗎？',
  quoteBody: (seconds, usual, ceiling) => `這段 ${seconds} 的錄音通常約用 ${usual} 點；完成前最多預留 ${ceiling} 點，並按實際費用收取。`,
  quoteAvailable: (available) => `你現有 ${available} 點。`,
  quoteNotEnough: '點數不足以支付這個上限。',
  transcribe: '轉錄',
  upgrade: '查看方案',
  pagesTitle: '選擇頁數',
  pagesBody: (total, max, pages) => `這份 PDF 共 ${pages} 頁、${total} 個字元，超出 ${max} 的上限。請選擇頁數範圍。`,
  pagesTooMany: (pages, max) => `這份 PDF 有 ${pages} 頁，每次最多讀取 ${max} 頁。請選擇頁數範圍。`,
  from: '由第幾頁',
  to: '至第幾頁',
  readPages: '讀取這些頁',
  transcriptHint: '逐字稿檔案會像 PDF 一樣變成待檢查的文字。'
};

export const COPY: Record<Lang, Copy> = { en: EN, 'zh-Hant': ZH };

export function copyFor(locale: string | null | undefined): Copy {
  return COPY[languageFor(locale)];
}

export function formatMegabytes(bytes: number): string {
  return `${(bytes / 1_000_000).toFixed(bytes >= 10_000_000 ? 0 : 1)} MB`;
}

export function formatDuration(seconds: number | null | undefined): string {
  const total = Math.max(0, Math.round(seconds ?? 0));
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`;
}

export function formatCredits(milliCredits: number | null | undefined): string {
  return ((milliCredits ?? 0) / 1000).toFixed(1);
}

export function formatCount(value: number, lang: Lang): string {
  return new Intl.NumberFormat(lang === 'zh-Hant' ? 'zh-Hant' : 'en').format(value);
}

const AUDIO_TYPES: Record<string, string> = {
  m4a: 'audio/mp4', mp4a: 'audio/mp4', mp3: 'audio/mpeg', wav: 'audio/wav', ogg: 'audio/ogg', opus: 'audio/ogg', oga: 'audio/ogg'
};
const AUDIO_ALIASES = new Set(['audio/mp4', 'audio/x-m4a', 'audio/m4a', 'audio/mpeg', 'audio/mp3', 'audio/wav', 'audio/x-wav', 'audio/wave', 'audio/vnd.wave', 'audio/ogg', 'audio/opus']);
const TRANSCRIPTS = new Set(['srt', 'vtt', 'txt']);

export type FileChoice =
  | { ok: true; kind: 'pdf'; mime: 'application/pdf' }
  | { ok: true; kind: 'audio'; mime: string }
  | { ok: true; kind: 'transcript'; format: 'srt' | 'vtt' | 'txt' }
  | { ok: false; code: 'unsupported_format' | 'webm' | 'over_limit' | 'audio_unavailable' | 'pdf_unavailable'; message: string };

/** What a chosen file is, checked against the limits the server published (the server checks again). */
export function classifyFile(file: { name: string; type?: string; size: number }, limits: LimitsLike, lang: Lang = 'en'): FileChoice {
  const copy = COPY[lang];
  const extension = (file.name.split('.').pop() ?? '').toLowerCase();
  const type = (file.type ?? '').toLowerCase();
  if (extension === 'pdf' || type === 'application/pdf') {
    if (!limits.formats.pdf.supported) return { ok: false, code: 'pdf_unavailable', message: copy.pdfOff };
    if (file.size > limits.limits.pdf.maxBytes) return { ok: false, code: 'over_limit', message: overLimit(file.size, limits.limits.pdf.maxBytes, lang) };
    return { ok: true, kind: 'pdf', mime: 'application/pdf' };
  }
  if (TRANSCRIPTS.has(extension) || type === 'text/vtt' || type === 'application/x-subrip') {
    const format = (TRANSCRIPTS.has(extension) ? extension : type === 'text/vtt' ? 'vtt' : 'srt') as 'srt' | 'vtt' | 'txt';
    return { ok: true, kind: 'transcript', format };
  }
  if (extension === 'webm' || type.includes('webm')) {
    return {
      ok: false,
      code: 'webm',
      message: lang === 'zh-Hant' ? '暫時未能量度 WebM 錄音的長度。請匯出為 M4A、MP3 或 WAV，或上載逐字稿。' : 'WebM recordings can’t be measured here yet. Export as M4A, MP3 or WAV, or upload a transcript.'
    };
  }
  const audioMime = AUDIO_ALIASES.has(type) ? type : AUDIO_TYPES[extension];
  if (audioMime) {
    if (!limits.formats.audio.supported) return { ok: false, code: 'audio_unavailable', message: copy.audioOff };
    if (file.size > limits.limits.audio.maxBytes) return { ok: false, code: 'over_limit', message: overLimit(file.size, limits.limits.audio.maxBytes, lang) };
    return { ok: true, kind: 'audio', mime: audioMime };
  }
  return {
    ok: false,
    code: 'unsupported_format',
    message: lang === 'zh-Hant' ? '請選擇 PDF、錄音（M4A、MP3、WAV、Ogg/Opus）或逐字稿（SRT、VTT、TXT）。' : 'Choose a PDF, a recording (M4A, MP3, WAV, Ogg/Opus) or a transcript (SRT, VTT, TXT).'
  };
}

export function overLimit(size: number, max: number, lang: Lang = 'en'): string {
  return lang === 'zh-Hant' ? `這個檔案有 ${formatMegabytes(size)}，上限是 ${formatMegabytes(max)}。` : `This file is ${formatMegabytes(size)}; the limit is ${formatMegabytes(max)}.`;
}

export function tooLong(seconds: number, max: number, lang: Lang = 'en'): string {
  return lang === 'zh-Hant' ? `這段錄音長 ${formatDuration(seconds)}，上限是 ${formatDuration(max)}。` : `This recording is ${formatDuration(seconds)} long; the limit is ${formatDuration(max)}.`;
}

type Said = { en: string; 'zh-Hant': string };
const REASONS: Record<string, Said> = {
  mime_mismatch: { en: 'The file isn’t the type it says it is, so it was deleted.', 'zh-Hant': '檔案內容與聲稱的類型不符，已刪除。' },
  over_limit: { en: 'Over the limit, so it was deleted.', 'zh-Hant': '超出上限，已刪除。' },
  size_mismatch: { en: 'The stored file isn’t the size that was chosen. Upload it again.', 'zh-Hant': '儲存的檔案大小與所選不同，請重新上載。' },
  duration_unreadable: { en: 'Its length couldn’t be measured, so it can’t be transcribed. Export as M4A, MP3 or WAV, or upload a transcript.', 'zh-Hant': '未能量度錄音長度，因此無法轉錄。請匯出為 M4A、MP3 或 WAV，或上載逐字稿。' },
  unsupported: { en: 'This format can’t be read here yet.', 'zh-Hant': '暫時未能讀取這個格式。' },
  no_text_layer: { en: 'No readable text: it looks scanned or image-only. Upload a PDF with selectable text, or paste the text.', 'zh-Hant': '沒有可讀文字：看來是掃描或純圖片檔。請上載文字可選取的 PDF，或直接貼上文字。' },
  encrypted: { en: 'This PDF is password-protected. Save an unprotected copy, or paste its text.', 'zh-Hant': '這份 PDF 受密碼保護。請另存未加密版本，或直接貼上文字。' },
  pdf_unreadable: { en: 'This PDF couldn’t be read. Export it again, or paste its text.', 'zh-Hant': '未能讀取這份 PDF。請重新匯出，或直接貼上文字。' },
  pdf_parser_unavailable: { en: 'PDF reading isn’t available right now.', 'zh-Hant': '暫時未能讀取 PDF。' },
  transcription_route_not_enabled: { en: 'Audio transcription isn’t available yet. Upload a transcript (SRT, VTT or TXT) instead.', 'zh-Hant': '暫時未能轉錄錄音。請改為上載逐字稿（SRT、VTT 或 TXT）。' },
  provider_limit: { en: 'This recording is longer or larger than the transcription route accepts.', 'zh-Hant': '這段錄音超出轉錄路線可接受的長度或大小。' },
  outcome_unknown: { en: 'The transcription service didn’t confirm the result. Its cost is held for review and it won’t be retried automatically.', 'zh-Hant': '轉錄服務未確認結果。相關費用會保留待核實，系統不會自動重試。' },
  transcript_empty: { en: 'The recording produced no words.', 'zh-Hant': '這段錄音沒有產生任何文字。' },
  storage_unavailable: { en: 'The file couldn’t be read from storage.', 'zh-Hant': '未能從儲存空間讀取檔案。' },
  extraction_timeout: { en: 'Reading this PDF took too long. Choose fewer pages or export a simpler copy.', 'zh-Hant': '讀取這份 PDF 太久。請選擇較少頁數或匯出較簡單的版本。' },
  attempts_exhausted: { en: 'Stopped after three attempts.', 'zh-Hant': '嘗試三次後已停止。' },
  object_missing: { en: 'The file is no longer in storage. Upload it again.', 'zh-Hant': '儲存空間中已沒有這個檔案，請重新上載。' },
  object_changed: { en: 'The stored file changed after it was checked. Upload it again.', 'zh-Hant': '檔案在檢查後有變動，請重新上載。' },
  provider_refused: { en: 'The transcription service refused the recording. Your credits were released.', 'zh-Hant': '轉錄服務拒絕處理這段錄音，點數已退回。' },
  user_cancelled: { en: 'Cancelled. Nothing from it was kept.', 'zh-Hant': '已取消，沒有保留任何內容。' },
  user_deleted: { en: 'Deleted.', 'zh-Hant': '已刪除。' },
  review_expired: { en: 'Not used within 30 days, so the file and its text were deleted.', 'zh-Hant': '30 日內未使用，檔案及文字已刪除。' },
  retention_elapsed: { en: 'The file and its text were deleted 30 days after the source was made. The source stays.', 'zh-Hant': '建立來源 30 日後，檔案及文字已刪除。來源仍會保留。' },
  source_retracted: { en: 'The source was withdrawn, so its file and text were deleted.', 'zh-Hant': '來源已撤回，其檔案及文字已刪除。' },
  upload_expired: { en: 'The upload never finished, so it was removed.', 'zh-Hant': '上載未完成，已移除。' },
  membership_revoked: { en: 'Stopped: the person who uploaded it is no longer an editor here.', 'zh-Hant': '已停止：上載者已不再是這個工作區的編輯者。' },
  account_deletion: { en: 'Stopped because the account is being deleted.', 'zh-Hant': '因帳戶正被刪除而停止。' },
  lease_expired: { en: 'The last attempt was interrupted before anything was sent; it will run again.', 'zh-Hant': '上次處理在送出前中斷，稍後會再次執行。' },
  worker_error: { en: 'Something went wrong while reading it; it will be tried again.', 'zh-Hant': '讀取時出錯，稍後會再嘗試。' },
  quote_missing: { en: 'No accepted quote was found, so nothing was transcribed.', 'zh-Hant': '找不到已接受的報價，因此沒有轉錄。' },
  unsupported_job: { en: 'This kind of file can’t be processed.', 'zh-Hant': '無法處理這類檔案。' },
  upload_missing: { en: 'The file is no longer available.', 'zh-Hant': '檔案已不存在。' }
};

export function reasonText(reason: string | null | undefined, lang: Lang): string | null {
  if (!reason) return null;
  const said = REASONS[reason];
  if (said) return said[lang];
  return reason.replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase());
}

/** Known API error codes in the person's language; anything else keeps the server's own sentence. */
export function errorText(code: string | undefined, fallback: string, lang: Lang): string {
  const mapped: Record<string, Said> = {
    feature_disabled: { en: 'Source uploads aren’t turned on here.', 'zh-Hant': '此處未開啟來源上載功能。' },
    source_upload_caps: { en: 'Finish or cancel your other uploads first.', 'zh-Hant': '請先完成或取消其他上載。' },
    insufficient_budget: { en: fallback, 'zh-Hant': '點數不足或方案不包括轉錄。請查看方案，或改為上載逐字稿。' },
    revision_conflict: { en: 'This text changed elsewhere. Reload it and try again.', 'zh-Hant': '這段文字已在別處更改。請重新載入再試。' },
    review_required: { en: 'Review the text first.', 'zh-Hant': '請先檢查文字。' },
    upload_incomplete: { en: 'The file hasn’t finished uploading. Try again in a moment.', 'zh-Hant': '檔案尚未上載完成，請稍後再試。' },
    storage_unavailable: { en: 'File storage isn’t available right now. Try again.', 'zh-Hant': '儲存空間暫時無法使用，請再試。' },
    no_usable_statements: { en: 'No complete statements were found. Edit the text into full sentences.', 'zh-Hant': '找不到完整陳述。請把文字修改成完整句子。' },
    source_duplicate: { en: 'This text is already a source in this workspace.', 'zh-Hant': '這段文字已是這個工作區的來源。' }
  };
  const said = code ? (mapped[code] ?? REASONS[code]) : undefined;
  return said ? said[lang] : fallback;
}

/** One label, a tone and an optional explanation for any upload the server returned. */
export function presentState(view: ViewLike, lang: Lang): { label: string; tone: Tone; detail: string | null } {
  const zh = lang === 'zh-Hant';
  const job = view.job;
  if (view.state === 'pending') return { label: zh ? '等待上載' : 'Waiting for the file', tone: 'progress', detail: null };
  if (view.state === 'rejected') return { label: zh ? '未被接受' : 'Not accepted', tone: 'error', detail: reasonText(view.reason, lang) };
  if (view.state === 'deleted') return { label: zh ? '已刪除' : 'Deleted', tone: 'muted', detail: reasonText(view.reason, lang) };
  if (!job) return { label: zh ? '已取消' : 'Cancelled', tone: 'muted', detail: reasonText(view.reason, lang) };
  const audio = job.kind === 'transcription';
  switch (job.state) {
    case 'queued':
      return job.attempts > 0
        ? { label: zh ? `稍後重試（第 ${job.attempts + 1} 次，共 ${job.maxAttempts} 次）` : `Retrying soon (attempt ${job.attempts + 1} of ${job.maxAttempts})`, tone: 'progress', detail: reasonText(job.reason, lang) }
        : { label: zh ? '排隊中' : 'Queued', tone: 'progress', detail: null };
    case 'running':
      return { label: audio ? (zh ? '轉錄中…' : 'Transcribing…') : (zh ? '讀取中…' : 'Reading…'), tone: 'progress', detail: null };
    case 'needs_review':
      if (job.reason === 'quote_required') return { label: zh ? '需要你確認費用' : 'Needs your OK to transcribe', tone: 'attention', detail: null };
      if (job.reason === 'page_selection_required') return { label: zh ? '請選擇頁數' : 'Choose pages', tone: 'attention', detail: null };
      return { label: zh ? '可以檢查' : 'Ready to review', tone: 'attention', detail: null };
    case 'completed':
      return { label: zh ? '已建立來源' : 'Source created', tone: 'done', detail: null };
    case 'unsupported':
      return { label: zh ? '不支援' : 'Not supported', tone: 'error', detail: reasonText(job.reason, lang) };
    case 'failed':
      return { label: zh ? '未完成' : 'Didn’t finish', tone: 'error', detail: reasonText(job.reason, lang) };
    case 'cancelled':
      return { label: zh ? '已取消' : 'Cancelled', tone: 'muted', detail: reasonText(job.reason, lang) };
    default:
      return { label: job.state, tone: 'muted', detail: null };
  }
}

/** Bounded polling: quick at first, slower after 30 s, and never past 3 minutes (the person can check again). */
export function pollDelay(view: ViewLike | undefined, elapsedMs: number): number | false {
  if (!view || !view.job || !['queued', 'running'].includes(view.job.state)) return false;
  if (elapsedMs > 180_000) return false;
  return elapsedMs < 30_000 ? 2_000 : 5_000;
}

/** A transcript file's text → what the server will see (BOM removed; nothing else changed). */
export function transcriptText(raw: string): string {
  return raw.charCodeAt(0) === 0xfeff ? raw.slice(1) : raw;
}
