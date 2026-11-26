/**
 * What to tell a person about each platform's routes: exactly which file of an export holds the posts, and why a
 * route that cannot work today is unavailable. The reasons are the ones recorded in the engineering spec (D4, §9).
 */
import { pick, platformName } from './labels';
import type { Language, Triple } from './labels';
import type { ExportNote, ImportRouteRow } from './types';

export interface ExportGuide {
  /** Files to pick, newest layout first, as paths inside the unzipped export. */
  files: { path: string; when?: Triple }[];
  /** One sentence on asking the platform for the export. */
  request: Triple;
}

const GUIDES: Record<string, ExportGuide> = {
  instagram: {
    request: ['Ask Instagram for an export of your information in JSON format, not HTML.', '向 Instagram 申請匯出你的資料，格式請選 JSON，不要選 HTML。', '向 Instagram 申请导出你的资料，格式请选 JSON，不要选 HTML。'],
    files: [
      { path: 'your_instagram_activity/media/posts_1.json', when: ['exports made in 2025 or later', '2025 年或之後的匯出', '2025 年或之后的导出'] },
      { path: 'your_instagram_activity/content/posts_1.json', when: ['earlier exports', '較早的匯出', '较早的导出'] },
      { path: 'content/posts_1.json', when: ['the oldest layout', '最舊的版面', '最旧的版面'] }
    ]
  },
  facebook: {
    request: ['Ask Facebook for an export of your information in JSON format, not HTML.', '向 Facebook 申請匯出你的資料，格式請選 JSON，不要選 HTML。', '向 Facebook 申请导出你的资料，格式请选 JSON，不要选 HTML。'],
    files: [
      { path: 'your_facebook_activity/posts/your_posts__check_ins__photos_and_videos_1.json' },
      { path: 'posts/your_posts_1.json', when: ['exports made before 2024', '2024 年之前的匯出', '2024 年之前的导出'] }
    ]
  },
  threads: {
    request: ['Ask for your Threads information in JSON format. Threads offers this in its mobile app and mobile site only.', '申請匯出 Threads 資料，格式請選 JSON。Threads 只在手機應用程式及手機版網站提供此功能。', '申请导出 Threads 资料，格式请选 JSON。Threads 只在手机应用及手机版网站提供此功能。'],
    files: [{ path: 'your_instagram_activity/threads/threads_and_replies.json' }]
  },
  x: {
    request: ['Download an archive of your data from X (Settings, Your account).', '在 X 下載你的資料封存（設定、你的帳戶）。', '在 X 下载你的数据存档（设置、你的账号）。'],
    files: [
      { path: 'data/tweets.js', when: ['and tweets-part1.js, tweets-part2.js … when the archive has them', '如封存內有 tweets-part1.js、tweets-part2.js 等，請一併選取', '如存档内有 tweets-part1.js、tweets-part2.js 等，请一并选取'] },
      { path: 'data/note-tweet.js', when: ['long posts; pick it together with tweets.js', '長文；請與 tweets.js 一併選取', '长文；请与 tweets.js 一并选取'] }
    ]
  },
  linkedin: {
    request: ['Ask LinkedIn for a copy of your data (Settings, Data privacy).', '向 LinkedIn 申請你的資料副本（設定、資料私隱）。', '向 LinkedIn 申请你的数据副本（设置、数据隐私）。'],
    files: [{ path: 'Shares.csv' }]
  },
  mastodon: {
    request: ['Ask your Mastodon server for an archive of your posts (Preferences, Import and export).', '向你的 Mastodon 伺服器申請貼文封存（偏好設定、匯入與匯出）。', '向你的 Mastodon 服务器申请帖子存档（偏好设置、导入与导出）。'],
    files: [{ path: 'outbox.json' }]
  }
};

/** The guide for a platform this app can read an export of, or `null`. */
export function exportGuide(provider: string): ExportGuide | null {
  return GUIDES[provider.trim().toLowerCase()] ?? null;
}

const REASONS: Record<string, Triple> = {
  'linkedin:official': [
    'LinkedIn no longer gives new apps permission to read a member’s posts, so Rafii cannot read them directly.',
    'LinkedIn 已不再向新應用程式開放讀取會員貼文的權限，Rafii 無法直接讀取。',
    'LinkedIn 已不再向新应用开放读取会员帖子的权限，Rafii 无法直接读取。'
  ],
  'facebook:official': [
    'Reading a Page’s posts needs a Facebook permission that Rafii does not have.',
    '讀取專頁貼文需要一項 Facebook 權限，Rafii 並未取得。',
    '读取主页帖子需要一项 Facebook 权限，Rafii 并未取得。'
  ],
  'x:official': [
    'X charges for each post an app reads, so Rafii does not read X posts directly.',
    'X 會就應用程式讀取的每篇貼文收費，因此 Rafii 不會直接讀取 X 貼文。',
    'X 会就应用读取的每篇帖子收费，因此 Rafii 不会直接读取 X 帖子。'
  ],
  'bluesky:export': [
    'Bluesky’s export is a repository file that Rafii cannot read yet. Connect the account instead.',
    'Bluesky 的匯出檔是一種資料庫檔案，Rafii 暫時未能讀取，請改為連接帳戶。',
    'Bluesky 的导出文件是一种仓库文件，Rafii 暂时无法读取，请改为连接账户。'
  ],
  'youtube:official': [
    'Not offered yet: YouTube returns only titles and short descriptions, which say little about how you write.',
    '暫未提供：YouTube 只提供標題及簡短說明，難以反映你的寫作風格。',
    '暂未提供：YouTube 只提供标题及简短说明，难以反映你的写作风格。'
  ],
  'tiktok:official': [
    'Not offered yet: TikTok returns only short captions of public videos, which say little about how you write.',
    '暫未提供：TikTok 只提供公開影片的簡短說明，難以反映你的寫作風格。',
    '暂未提供：TikTok 只提供公开视频的简短说明，难以反映你的写作风格。'
  ]
};

/** Reason codes the workspace sends for a connection route that is switched off on this deployment, not by the platform. */
const CODES: Record<string, (name: string) => Triple> = {
  not_enabled: (name) => [`Reading ${name} posts from a connected account is not turned on here.`, `此處未啟用從已連接帳戶讀取 ${name} 貼文。`, `此处未启用从已连接账户读取 ${name} 帖子。`],
  not_configured: (name) => [`${name} accounts cannot be connected here yet.`, `此處暫時未能連接 ${name} 帳戶。`, `此处暂时无法连接 ${name} 账户。`]
};

/**
 * Why a route is unavailable. A sentence from the workspace is shown as written; otherwise the recorded reason for
 * that platform; otherwise the sentence for the workspace's reason code; otherwise that code in plain words; otherwise
 * a plain "not available".
 */
export function routeReason(provider: string, route: 'official' | 'export', reason: string | null | undefined, language: Language): string {
  const stated = (reason ?? '').trim();
  if (/\s/.test(stated)) return stated;
  const recorded = REASONS[`${provider.trim().toLowerCase()}:${route}`];
  if (recorded) return pick(language, recorded);
  const name = platformName(provider);
  const coded = route === 'official' && Object.prototype.hasOwnProperty.call(CODES, stated) ? CODES[stated] : undefined;
  if (coded) return pick(language, coded(name));
  const generic: Triple =
    route === 'official'
      ? [`Rafii cannot read ${name} posts directly right now.`, `Rafii 暫時無法直接讀取 ${name} 貼文。`, `Rafii 暂时无法直接读取 ${name} 帖子。`]
      : [`Rafii cannot read a ${name} export yet.`, `Rafii 暫時未能讀取 ${name} 的匯出檔。`, `Rafii 暂时无法读取 ${name} 的导出文件。`];
  const words = stated.replace(/[_-]+/g, ' ');
  return words ? `${pick(language, generic)} (${words})` : pick(language, generic);
}

/** What one platform row offers, in the order the panel shows it. */
export function routeOffer(row: ImportRouteRow): { official: boolean; upload: boolean } {
  return { official: row.official?.available === true, upload: row.export?.available === true && exportGuide(row.provider) !== null };
}

const NOTES: Record<ExportNote, Triple> = {
  not_json: [
    'This file could not be read as JSON. It may be incomplete; download the export again.',
    '此檔案無法以 JSON 格式讀取，可能並不完整，請重新下載匯出檔。',
    '此文件无法以 JSON 格式读取，可能并不完整，请重新下载导出文件。'
  ],
  unknown_shape: [
    'This file has the right name but a layout Rafii has not seen, so no posts were read from it.',
    '此檔案名稱正確，但版面是 Rafii 未見過的，因此沒有從中讀取任何貼文。',
    '此文件名称正确，但版面是 Rafii 未见过的，因此没有从中读取任何帖子。'
  ]
};

export function noteText(note: ExportNote, language: Language): string {
  return pick(language, NOTES[note]);
}
