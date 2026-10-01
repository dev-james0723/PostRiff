/**
 * Signature Series words (English and Traditional Chinese) and the small pure rules the Library panel shows them by.
 * No React and no `@/` imports, so `node --test web/tests/series.test.mjs` checks them directly.
 */
import type { DecisionKind, EpisodeState, FactReason, NextActionKind, SeriesEpisode, SeriesRole, SeriesStatus, SeriesView } from '@/lib/growth-v2/series-types';

export type SeriesLocale = 'en' | 'zh-Hant';
export type SeriesTone = 'neutral' | 'info' | 'success' | 'warning' | 'danger';

export interface SeriesCopy {
  sectionTitle: string;
  sectionIntro: string;
  newSeries: string;
  emptyTitle: string;
  emptyBody: string;
  loadError: string;
  retry: string;
  showMore: string;
  showArchived: string;
  hideArchived: string;
  open: string;
  covered: string;
  needsReview: string;
  fromPost: string;
  fromSource: string;
  originGone: string;
  followers: string;
  status: Record<SeriesStatus, string>;
  role: Record<SeriesRole, string>;
  state: Record<EpisodeState, string>;
  factOk: string;
  factNeeds: string;
  reason: Record<FactReason, string>;
  next: Record<NextActionKind, string>;
  approveNext: string;
  accept: string;
  reject: string;
  doNotRepeat: string;
  doNotRepeatRole: string;
  angleAccepted: string;
  revoke: string;
  planMore: string;
  pause: string;
  resume: string;
  complete: string;
  archive: string;
  addDraft: string;
  draftWithRafii: string;
  draftNote: string;
  copyBrief: string;
  copied: string;
  chooseDraft: string;
  noDrafts: string;
  link: string;
  unlink: string;
  candidate: string;
  gateNote: string;
  published: string;
  stillTrue: string;
  correct: string;
  removeFact: string;
  reviewBy: string;
  correctedText: string;
  save: string;
  cancel: string;
  coverageHeading: string;
  episodesHeading: string;
  factsHeading: string;
  decisionsHeading: string;
  question: string;
  angle: string;
  decision: Record<DecisionKind, string>;
  storageMemory: string;
  storageSeries: string;
  reasonOverlaysOff: string;
  reasonOwner: string;
  revoked: string;
  warning: { similar_to_original: string; similar_to_episode: string; similar_to_post: string };
  acknowledge: string;
  refused: string;
  createTitle: string;
  createIntro: string;
  sourcePost: string;
  sourceSource: string;
  audienceQuestion: string;
  audienceQuestionHint: string;
  goal: string;
  title: string;
  episodeCount: string;
  minAge: string;
  days: string;
  create: string;
  noPosts: string;
  noSources: string;
  priorUse: string;
  observed: string;
  approvedFacts: string;
  changeFailed: string;
  saved: string;
  unverified: string;
  follow: string;
  followNone: string;
  followNote: string;
  addImage: string;
  chooseImage: string;
  noImages: string;
  images: string;
  imageGone: string;
  brief: { intro: string; role: string; question: string; angle: string; facts: string; noFacts: string; rules: string };
}

const EN: SeriesCopy = {
  sectionTitle: 'Signature Series',
  sectionIntro: 'Turn one strong post or source into a short series. Each episode answers one audience question from its own angle, and facts are checked again before anything is reused.',
  newSeries: 'Start a series',
  emptyTitle: 'No series yet',
  emptyBody: 'Start from a published post at least 30 days old, or from a source with approved facts.',
  loadError: 'Couldn’t load your series.',
  retry: 'Try again',
  showMore: 'Show more',
  showArchived: 'Show archived',
  hideArchived: 'Hide archived',
  open: 'Open',
  covered: '{n} of {total} questions covered',
  needsReview: '{n} need a fact check',
  fromPost: '{platform} post from {date}',
  fromSource: 'From the source “{title}”',
  originGone: 'The original is no longer available.',
  followers: '{n} automation(s) follow this series.',
  status: { active: 'Active', paused: 'Paused', completed: 'Completed', archived: 'Archived' },
  role: { explanation: 'Explanation', worked_example: 'Worked example', case_study: 'Case study', faq: 'FAQ', update: 'Update' },
  state: { planned: 'Planned', approved: 'Approved as next', drafting: 'Being drafted', drafted: 'Draft added', skipped: 'Set aside', published: 'Published' },
  factOk: 'Facts current',
  factNeeds: 'Needs a fact check',
  reason: {
    claim_expired: 'Its review date has passed',
    source_unavailable: 'Its source was deleted or withdrawn',
    missing_support: 'No approved fact supports it',
    source_changed: 'Its source changed after it was checked'
  },
  next: {
    review_facts: 'Check the flagged facts before anything is reused.',
    approve_next: 'Approve the next episode to produce.',
    add_draft: 'Add the draft for the approved episode.',
    plan_more: 'Every planned episode is done. Plan more when you’re ready.',
    resume: 'This series is paused.',
    none: 'Nothing to do right now.'
  },
  approveNext: 'Approve as next',
  accept: 'Keep this angle',
  reject: 'Not this angle',
  doNotRepeat: 'Don’t repeat this angle',
  doNotRepeatRole: 'No more episodes of this kind',
  angleAccepted: 'Angle kept',
  revoke: 'Revoke',
  planMore: 'Plan more episodes',
  pause: 'Pause',
  resume: 'Resume',
  complete: 'Mark complete',
  archive: 'Archive',
  addDraft: 'Add a draft',
  draftWithRafii: 'Draft with Rafii',
  draftNote: 'Drafting with Rafii uses your writing credits and every draft waits for your review. You can also write it yourself and add it here.',
  copyBrief: 'Copy brief',
  copied: 'Brief copied.',
  chooseDraft: 'Choose a draft',
  noDrafts: 'No drafts to add yet.',
  link: 'Add to episode',
  unlink: 'Remove',
  candidate: 'From this episode’s automation run',
  gateNote: 'Queue holds this draft until the facts are checked.',
  published: 'Published',
  stillTrue: 'Still true',
  correct: 'Correct it',
  removeFact: 'Remove fact',
  reviewBy: 'Check again by',
  correctedText: 'Corrected fact',
  save: 'Save',
  cancel: 'Cancel',
  coverageHeading: 'Audience questions',
  episodesHeading: 'Episodes',
  factsHeading: 'Facts',
  decisionsHeading: 'Angle decisions',
  question: 'Question',
  angle: 'Angle',
  decision: { accept: 'Kept', reject: 'Not used', do_not_repeat: 'Don’t repeat' },
  storageMemory: 'Saved to workspace memory for this series',
  storageSeries: 'Kept on this series',
  reasonOverlaysOff: 'Workspace memory is off, so it stays on this series.',
  reasonOwner: 'Only an owner can save to workspace memory, so it stays on this series.',
  revoked: 'Revoked',
  warning: {
    similar_to_original: 'Close to the original ({pct}% similar)',
    similar_to_episode: 'Close to episode {n} ({pct}% similar)',
    similar_to_post: 'Close to a published post ({pct}% similar)'
  },
  acknowledge: 'I checked these: it is a distinct episode',
  refused: 'This draft can’t be added',
  createTitle: 'Start a Signature Series',
  createIntro: 'Pick the original. Rafii plans 2–6 episodes without writing anything or using credits.',
  sourcePost: 'Published post',
  sourceSource: 'Source',
  audienceQuestion: 'The audience question it answers',
  audienceQuestionHint: 'For example: How should adult beginners practise?',
  goal: 'What the series is for',
  title: 'Name (optional)',
  episodeCount: 'Episodes to plan',
  minAge: 'Posts at least',
  days: 'days old',
  create: 'Plan the series',
  noPosts: 'No published post is old enough yet.',
  noSources: 'No source has approved facts yet.',
  priorUse: 'Already reused {n} time(s)',
  observed: '{value} {metric} vs a typical {typical} across {n} comparable posts — an observation, not a cause',
  approvedFacts: '{n} approved fact(s)',
  changeFailed: 'That change wasn’t saved.',
  saved: 'Saved.',
  unverified: 'Saved, but it couldn’t be read back yet. Refresh to check.',
  follow: 'Follow a series',
  followNone: 'No series: any older post',
  followNote: 'Each run drafts the series’ approved episode, once.',
  addImage: 'Add an image',
  chooseImage: 'Choose a Library image',
  noImages: 'No images in Library yet.',
  images: '{n} image(s) from Library',
  imageGone: 'An image was deleted from Library.',
  brief: {
    intro: 'Draft episode {n} of my series “{title}” for review.',
    role: 'Role: {role}.',
    question: 'It answers: {question}',
    angle: 'Angle: {angle}',
    facts: 'Use only these facts:',
    noFacts: 'There are no checked facts for this episode: share a view, not new facts.',
    rules: 'Don’t copy the original post and don’t add facts, numbers, results or quotes that aren’t listed.'
  }
};

const ZH: SeriesCopy = {
  sectionTitle: '招牌系列',
  sectionIntro: '把一篇好帖文或一份資料延伸成短系列。每一集從自己的角度回答一個受眾問題，重用前會再核對事實。',
  newSeries: '開始系列',
  emptyTitle: '還沒有系列',
  emptyBody: '可以從已發布至少 30 天的帖文，或已核准事實的資料開始。',
  loadError: '無法載入系列。',
  retry: '再試一次',
  showMore: '顯示更多',
  showArchived: '顯示已封存',
  hideArchived: '隱藏已封存',
  open: '打開',
  covered: '已回答 {n}／{total} 個問題',
  needsReview: '{n} 集需要核對事實',
  fromPost: '{date} 的 {platform} 帖文',
  fromSource: '來自資料「{title}」',
  originGone: '原文已無法使用。',
  followers: '有 {n} 個自動化跟隨這個系列。',
  status: { active: '進行中', paused: '已暫停', completed: '已完成', archived: '已封存' },
  role: { explanation: '解說', worked_example: '實例示範', case_study: '個案', faq: '常見問題', update: '更新' },
  state: { planned: '已規劃', approved: '已批准為下一集', drafting: '草擬中', drafted: '已加入草稿', skipped: '已擱置', published: '已發布' },
  factOk: '事實已核對',
  factNeeds: '需要核對事實',
  reason: {
    claim_expired: '已過核對日期',
    source_unavailable: '來源已刪除或撤回',
    missing_support: '沒有已核准的事實支持',
    source_changed: '核對後來源有變'
  },
  next: {
    review_facts: '重用前，請先核對標示的事實。',
    approve_next: '請批准下一集。',
    add_draft: '請為已批准的一集加入草稿。',
    plan_more: '已規劃的集數都完成了，準備好再規劃更多。',
    resume: '這個系列已暫停。',
    none: '目前沒有要處理的事。'
  },
  approveNext: '批准為下一集',
  accept: '保留這個角度',
  reject: '不用這個角度',
  doNotRepeat: '不要重複這個角度',
  doNotRepeatRole: '不再規劃這類集數',
  angleAccepted: '已保留角度',
  revoke: '撤回',
  planMore: '規劃更多集',
  pause: '暫停',
  resume: '恢復',
  complete: '標示完成',
  archive: '封存',
  addDraft: '加入草稿',
  draftWithRafii: '請 Rafii 草擬',
  draftNote: '請 Rafii 草擬會使用寫作點數，每份草稿都要經你審閱。你也可以自己寫好再加入。',
  copyBrief: '複製簡介',
  copied: '已複製簡介。',
  chooseDraft: '選擇草稿',
  noDrafts: '暫時沒有可加入的草稿。',
  link: '加入這一集',
  unlink: '移除',
  candidate: '來自這一集的自動化',
  gateNote: '事實核對前，佇列會暫停這份草稿。',
  published: '已發布',
  stillTrue: '仍然正確',
  correct: '更正',
  removeFact: '移除事實',
  reviewBy: '下次核對日期',
  correctedText: '更正後的事實',
  save: '儲存',
  cancel: '取消',
  coverageHeading: '受眾問題',
  episodesHeading: '集數',
  factsHeading: '事實',
  decisionsHeading: '角度決定',
  question: '問題',
  angle: '角度',
  decision: { accept: '保留', reject: '不用', do_not_repeat: '不要重複' },
  storageMemory: '已存入這個系列的工作區記憶',
  storageSeries: '只記在這個系列',
  reasonOverlaysOff: '工作區記憶未開啟，所以只記在這個系列。',
  reasonOwner: '只有擁有者可以存入工作區記憶，所以只記在這個系列。',
  revoked: '已撤回',
  warning: {
    similar_to_original: '與原文相近（{pct}% 相似）',
    similar_to_episode: '與第 {n} 集相近（{pct}% 相似）',
    similar_to_post: '與已發布帖文相近（{pct}% 相似）'
  },
  acknowledge: '我已檢查：這是不同的一集',
  refused: '這份草稿不能加入',
  createTitle: '開始招牌系列',
  createIntro: '選擇原文。Rafii 會規劃 2 至 6 集，不會撰寫內容，也不會使用點數。',
  sourcePost: '已發布帖文',
  sourceSource: '資料',
  audienceQuestion: '系列回答的受眾問題',
  audienceQuestionHint: '例如：成人初學者應該怎樣練習？',
  goal: '系列的目的',
  title: '名稱（選填）',
  episodeCount: '規劃集數',
  minAge: '帖文至少',
  days: '天前發布',
  create: '規劃系列',
  noPosts: '暫時沒有發布夠久的帖文。',
  noSources: '暫時沒有已核准事實的資料。',
  priorUse: '已重用 {n} 次',
  observed: '{value} {metric}，相比 {n} 篇可比較帖文的一般 {typical}——只是觀察，不代表原因',
  approvedFacts: '{n} 項已核准事實',
  changeFailed: '這項更改未能儲存。',
  saved: '已儲存。',
  unverified: '已儲存，但暫時未能讀回確認，請重新整理查看。',
  follow: '跟隨系列',
  followNone: '不跟隨：任何較舊的帖文',
  followNote: '每次執行只草擬系列中已批准的一集，不會重複。',
  addImage: '加入圖片',
  chooseImage: '選擇媒體庫圖片',
  noImages: '媒體庫暫時沒有圖片。',
  images: '{n} 張媒體庫圖片',
  imageGone: '有圖片已從媒體庫刪除。',
  brief: {
    intro: '請為我的系列「{title}」草擬第 {n} 集，供我審閱。',
    role: '類型：{role}。',
    question: '回答的問題：{question}',
    angle: '角度：{angle}',
    facts: '只可使用以下事實：',
    noFacts: '這一集沒有已核對的事實：只分享觀點，不要加入新事實。',
    rules: '不要照抄原文，也不要加入清單以外的事實、數字、成果或引述。'
  }
};

export const COPY: Record<SeriesLocale, SeriesCopy> = { en: EN, 'zh-Hant': ZH };

/** Traditional Chinese for any Chinese or Cantonese preference; English otherwise. */
export function seriesLocale(locale: string | null | undefined): SeriesLocale {
  const tag = (locale ?? '').toLowerCase();
  return tag.startsWith('zh') || tag.startsWith('yue') ? 'zh-Hant' : 'en';
}

export function fill(template: string, values: Record<string, string | number>): string {
  return template.replace(/\{(\w+)\}/g, (match, key: string) => (key in values ? String(values[key]) : match));
}

export function stateTone(state: EpisodeState, factState: 'ok' | 'needs_fact_review'): SeriesTone {
  if (factState === 'needs_fact_review' && state !== 'skipped' && state !== 'published') return 'warning';
  if (state === 'published') return 'success';
  if (state === 'drafted' || state === 'approved' || state === 'drafting') return 'info';
  return 'neutral';
}

export function coverageLine(copy: SeriesCopy, covered: number, total: number): string {
  return fill(copy.covered, { n: covered, total });
}

/** The one next action, in words, with the episode number when it points at one. */
export function nextActionText(copy: SeriesCopy, series: Pick<SeriesView, 'nextAction' | 'episodes'>): string {
  const target = series.nextAction.episodeId ? series.episodes.find((episode) => episode.id === series.nextAction.episodeId) : undefined;
  const text = copy.next[series.nextAction.kind] ?? copy.next.none;
  return target ? `${text} (${target.index})` : text;
}

export function addDays(today: Date, days: number): string {
  const next = new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate() + days));
  return next.toISOString().slice(0, 10);
}

/**
 * What "Draft with Rafii" hands to the Rafii panel (the existing writer path, with its own credit check and review):
 * the episode's role, question and angle and only its current, supported facts. The person sends it themselves.
 */
export function episodeBrief(copy: SeriesCopy, series: Pick<SeriesView, 'title' | 'claims'>, episode: Pick<SeriesEpisode, 'index' | 'role' | 'question' | 'angle' | 'claimIds'>): string {
  const facts = series.claims.filter((claim) => episode.claimIds.includes(claim.id) && claim.status !== 'removed' && claim.freshness.state === 'ok');
  const lines = [
    fill(copy.brief.intro, { n: episode.index, title: series.title }),
    fill(copy.brief.role, { role: copy.role[episode.role] }),
    fill(copy.brief.question, { question: episode.question }),
    fill(copy.brief.angle, { angle: episode.angle.text }),
    facts.length ? [copy.brief.facts, ...facts.map((fact) => `- ${fact.text}`)].join('\n') : copy.brief.noFacts,
    copy.brief.rules
  ];
  return lines.join('\n');
}

/** The series episode an automation run drafted, read from the run's evergreen record (absent for a plain refresh). */
export function seriesEpisodeOf(evergreen: unknown): { index: number; role: string } | null {
  const episode = evergreen && typeof evergreen === 'object' ? (evergreen as { episode?: { index?: unknown; role?: unknown } }).episode : undefined;
  return episode && typeof episode.index === 'number' && typeof episode.role === 'string' ? { index: episode.index, role: episode.role } : null;
}

export function percent(similarity: number): number {
  return Math.round(Math.max(0, Math.min(1, similarity)) * 100);
}
