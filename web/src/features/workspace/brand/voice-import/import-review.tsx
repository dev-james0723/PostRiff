'use client';

import { useId, useState } from 'react';
import { StateMessage, Surface } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { useGenUiLocale } from '@/features/agent/generative-ui/core/locale';
import type { VoiceProfile } from '@/lib/api/types';
import { MIN_ELIGIBLE } from '@/lib/voice-import/coverage';
import { platformName } from '@/lib/voice-import/labels';
import { basisLabel, correctionPayload, correctionState, scopeLabels, scopePlatforms, traitEvidence } from '@/lib/voice-import/review';
import type { Correction, ReviewTrait } from '@/lib/voice-import/review';
import { TEXTAREA_CLASS } from '../../rafii-parts';
import type { BrainAction, BrainTranslate } from '../brain-types';
import { TraitEvidence } from './voice-import-evidence';

/** The existing evidence words: supported, limited, conflicting, not enough examples, and the person's own rule. Never a score. */
export function evidenceWord(level: string, t: BrainTranslate): string {
  if (level === 'supported') return t('Supported', '有證據支持', '有证据支持');
  if (level === 'limited') return t('Limited evidence', '證據有限', '证据有限');
  if (level === 'conflicting') return t('Conflicting evidence', '證據有矛盾', '证据有冲突');
  if (level === 'user-defined') return t('User-defined', '使用者自訂', '用户自定义');
  return t('Not enough examples', '範例不足', '样本不足');
}

const CHIP = 'rounded-full border px-3 py-1 text-xs';

/**
 * What a proposal built from imported posts says about itself: a summary, recurring topics, how many posts it
 * rests on, how it was worked out, and what was not analysed. The summary and topics are shown as written.
 */
export function ImportReviewHeader({ proposal, t }: { proposal: VoiceProfile; t: BrainTranslate }) {
  const locale = useGenUiLocale();
  const eligible = proposal.coverage?.eligible;
  const analysed = proposal.coverage?.analysed ?? 0;
  const receipt = proposal.analysisReceipt;
  const topics = (proposal.topics ?? []).filter((topic) => typeof topic === 'string' && topic.trim());
  const differences = proposal.differences;
  const sparse = typeof eligible === 'number' && eligible < MIN_ELIGIBLE;
  const count = (ids: string[] | undefined) => locale.formatNumber(ids?.length ?? 0);
  return (
    <Surface material='quiet' className='space-y-4' data-testid='bb-import-header'>
      <h3 className='font-semibold'>{t('What Rafii found in your posts', 'Rafii 在你的貼文中發現甚麼', 'Rafii 在你的帖子中发现什么')}</h3>
      {sparse && (
        <StateMessage
          kind='partial'
          layout='inline'
          title={t('Not enough writing yet', '文字尚未足夠', '文字尚不足够')}
          description={t(
            'Fewer than 3 posts could be used, so these traits say nothing reliable. Add posts in Sources & permissions, or write the direction you want on a trait below.',
            '可使用的貼文少於 3 篇，因此這些特徵並不可靠。請在「來源與權限」加入貼文，或在下方的特徵寫下你想要的方向。',
            '可使用的帖子少于 3 篇，因此这些特征并不可靠。请在“来源与权限”添加帖子，或在下方的特征写下你想要的方向。'
          )}
        />
      )}
      {proposal.summary && (
        <p dir='auto' className='text-sm leading-relaxed break-words'>
          {proposal.summary}
        </p>
      )}
      {topics.length > 0 && (
        <div>
          <h4 className='text-sm font-medium'>{t('Topics you return to', '你經常談及的主題', '你经常谈及的主题')}</h4>
          <ul className='mt-2 flex flex-wrap gap-2'>
            {topics.map((topic) => (
              <li key={topic} dir='auto' className={`${CHIP} break-words`}>
                {topic}
              </li>
            ))}
          </ul>
        </div>
      )}
      <dl className='grid gap-3 text-sm sm:grid-cols-2'>
        <div>
          <dt className='font-medium'>{t('Coverage', '涵蓋範圍', '涵盖范围')}</dt>
          <dd className='text-muted-foreground'>
            {typeof eligible === 'number' ? `${t('Posts measured', '已量度的貼文', '已测量的帖子')}: ${locale.formatNumber(eligible)}` : t('The number of posts measured was not recorded.', '未有記錄已量度的貼文數量。', '未记录已测量的帖子数量。')}
            {analysed > 0 ? ` · ${t('Posts read by AI', '由 AI 解讀的貼文', '由 AI 解读的帖子')}: ${locale.formatNumber(analysed)}` : ''}
          </dd>
        </div>
        <div>
          <dt className='font-medium'>{t('How this was worked out', '如何得出', '如何得出')}</dt>
          <dd className='text-muted-foreground'>
            {receipt || analysed > 0
              ? t('Measured in your posts, then read by an AI model. Each trait says which.', '先從你的貼文量度，再由 AI 模型解讀；每項特徵均有註明。', '先从你的帖子测量，再由 AI 模型解读；每项特征均有注明。')
              : t('Measured in your posts. No AI model read them.', '從你的貼文量度，沒有 AI 模型讀取。', '从你的帖子测量，没有 AI 模型读取。')}
            {receipt && <span className='mt-1 block text-xs break-all'>{[receipt.route, receipt.promptVersion].filter(Boolean).join(' · ')}</span>}
          </dd>
        </div>
      </dl>
      {differences && (differences.kept || differences.changed || differences.added) && (
        <p className='text-sm'>
          {t('Compared with your approved voice', '與已批准的風格比較', '与已批准的风格比较')}
          {typeof differences.against === 'number' ? ` v${differences.against}` : ''}: {t('kept', '保留', '保留')} {count(differences.kept)} · {t('changed', '更改', '更改')} {count(differences.changed)} · {t('new', '新增', '新增')} {count(differences.added)}
        </p>
      )}
      <p className='text-muted-foreground text-xs'>
        {t(
          'Text only: images and video in your posts were not analysed. The proposal keeps post ids, not wording; excerpts below are loaded for members of this workspace when you open a trait.',
          '只分析文字：貼文中的圖片及影片沒有分析。提案只保留貼文編號，不保留字句；下方摘錄會在你開啟特徵時為此工作區的成員載入。',
          '仅分析文字：帖子中的图片及视频没有分析。提案只保留帖子编号，不保留字句；下方摘录会在你打开特征时为此工作区的成员加载。'
        )}
      </p>
    </Surface>
  );
}

/**
 * One trait of an import proposal: a readable name, the evidence word, where and when it applies, the posts behind
 * it (loaded on demand), four quick corrections, and a place to write the direction the person wants instead.
 * A correction is one workspace action and applies at once; the proposal stays a proposal.
 */
export function ImportTraitCard({ trait, name, corpusPlatforms, proposalDigest, disabled, run, t }: { trait: ReviewTrait; name: string; corpusPlatforms: string[]; proposalDigest: string | null; disabled: boolean; run: BrainAction; t: BrainTranslate }) {
  const id = useId();
  const locale = useGenUiLocale();
  const own = trait.userAuthored === true || trait.evidenceLevel === 'user-defined';
  const [evidenceOpen, setEvidenceOpen] = useState(false);
  const [directing, setDirecting] = useState(false);
  const [direction, setDirection] = useState(own ? trait.observation : '');
  const state = correctionState(trait);
  const evidence = traitEvidence(trait);
  const platforms = scopePlatforms(trait, corpusPlatforms);
  const rejected = state.notMe;
  const chips = [basisLabel(trait, locale.language), ...scopeLabels(trait, locale.language)];
  const period = trait.period?.from && trait.period?.to ? `${locale.formatDate(trait.period.from)} – ${locale.formatDate(trait.period.to)}` : '';

  const correct = (correction: Correction, platform?: string) => void run('brand_brain_trait_correct', correctionPayload(trait, proposalDigest, correction, platform));
  async function saveDirection() {
    const observation = direction.trim();
    if (!observation) return;
    if (await run('brand_brain_review', { proposalDigest, decisions: [{ id: trait.id, decision: 'edit', observation }] })) setDirecting(false);
  }

  return (
    <Surface material='quiet' padding='sm' className='space-y-3' data-testid={`bb-trait-${trait.id}`}>
      <div className='flex flex-wrap justify-between gap-2'>
        <h3 id={`${id}-name`} className='font-medium'>
          {name}
        </h3>
        <span className='text-muted-foreground text-xs'>{evidenceWord(trait.evidenceLevel, t)}</span>
      </div>
      <p dir='auto' className={`text-sm break-words ${rejected || state.oldStyle ? 'text-muted-foreground' : ''} ${rejected ? 'line-through' : ''}`}>
        {trait.observation}
      </p>
      <ul className='flex flex-wrap gap-1.5' aria-label={t('Where this comes from and applies', '來源及適用範圍', '来源及适用范围')}>
        {chips.map((chip) => (
          <li key={chip} className={CHIP}>
            {chip}
          </li>
        ))}
        {period && <li className={CHIP}>{period}</li>}
        {state.oldStyle && <li className={CHIP}>{t('Old style: kept here, not used in drafts', '舊風格：保留於此，不用於草稿', '旧风格：保留于此，不用于草稿')}</li>}
        {rejected && <li className={CHIP}>{t('Not used', '不採用', '不采用')}</li>}
      </ul>

      {!own && (
        <details onToggle={(event) => setEvidenceOpen(event.currentTarget.open)}>
          <summary className='rafii-focus min-h-11 cursor-pointer py-3 text-sm'>{t('Why Rafii thinks this', 'Rafii 為何作出此判斷', 'Rafii 为何作出此判断')}</summary>
          {evidenceOpen &&
            (evidence.postIds.length > 0 ? (
              <TraitEvidence postIds={evidence.postIds} count={evidence.count} counter={evidence.counter} t={t} />
            ) : (
              <p className='text-muted-foreground text-xs'>
                {trait.evidenceLevel === 'insufficient'
                  ? t('There are not enough posts to show this either way.', '貼文數量不足，未能判斷。', '帖子数量不足，无法判断。')
                  : t('No posts are cited for this trait. Mark it as not yours, or write the direction you want.', '此特徵沒有引用任何貼文。請標記為並非你的風格，或寫下你想要的方向。', '此特征没有引用任何帖子。请标记为并非你的风格，或写下你想要的方向。')}
              </p>
            ))}
        </details>
      )}

      <div role='group' aria-labelledby={`${id}-name`} className='flex flex-wrap gap-2'>
        <Button className='min-h-11' variant={state.soundsLikeMe ? 'glass' : 'quiet'} aria-pressed={state.soundsLikeMe} disabled={disabled} onClick={() => correct('sounds_like_me')}>
          {t('This sounds like me', '這像我的風格', '这像我的风格')}
        </Button>
        <Button className='min-h-11' variant={state.notMe ? 'glass' : 'quiet'} aria-pressed={state.notMe} disabled={disabled} onClick={() => correct('not_me')}>
          {own ? t('Don’t use this rule', '不採用此規則', '不采用此规则') : t('Someone else wrote this', '這是別人寫的', '这是别人写的')}
        </Button>
        {platforms.map((platform) => {
          const only = state.onlyFor.length === 1 && state.onlyFor[0] === platform;
          return (
            <Button key={platform} className='min-h-11' variant={only ? 'glass' : 'quiet'} aria-pressed={only} disabled={disabled} onClick={() => correct('only_scope', platform)}>
              {t(`Only for ${platformName(platform)}`, `只適用於 ${platformName(platform)}`, `只适用于 ${platformName(platform)}`)}
            </Button>
          );
        })}
        <Button className='min-h-11' variant={state.oldStyle ? 'glass' : 'quiet'} aria-pressed={state.oldStyle} disabled={disabled} onClick={() => correct('old_style')}>
          {t('This is my old style', '這是我以前的風格', '这是我以前的风格')}
        </Button>
        <Button className='min-h-11' variant={directing ? 'glass' : 'quiet'} aria-expanded={directing} aria-controls={`${id}-direction`} disabled={disabled} onClick={() => setDirecting((open) => !open)}>
          {t('Direction I want', '我想要的方向', '我想要的方向')}
        </Button>
      </div>

      <div id={`${id}-direction`}>
        {directing && (
          <div className='flex min-w-0 flex-col gap-2'>
            <label htmlFor={`${id}-direction-text`} className='text-sm font-medium'>
              {t('Direction I want', '我想要的方向', '我想要的方向')}: {name}
            </label>
            <Textarea id={`${id}-direction-text`} value={direction} onChange={(event) => setDirection(event.target.value)} maxLength={240} dir='auto' className={TEXTAREA_CLASS} />
            <p className='text-muted-foreground text-xs'>
              {t(
                'Write how you want this to sound. It becomes your own rule and replaces what Rafii observed for this trait. It is not learned from your posts.',
                '寫下你希望的寫法。這會成為你自己的規則，並取代 Rafii 就此特徵的觀察；它並非從你的貼文學習得來。',
                '写下你希望的写法。这会成为你自己的规则，并取代 Rafii 就此特征的观察；它并非从你的帖子学习得来。'
              )}
            </p>
            <div className='flex flex-wrap gap-2'>
              <Button className='min-h-11' variant='glass' disabled={disabled || !direction.trim()} onClick={() => void saveDirection()}>
                {t('Save as my rule', '儲存為我的規則', '保存为我的规则')}
              </Button>
              <Button className='min-h-11' variant='quiet' onClick={() => setDirecting(false)}>
                {t('Cancel', '取消', '取消')}
              </Button>
            </div>
          </div>
        )}
      </div>
    </Surface>
  );
}
