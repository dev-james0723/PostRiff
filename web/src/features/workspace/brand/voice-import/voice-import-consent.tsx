'use client';

import { useId } from 'react';
import { RadioGroup, RadioGroupItem } from '@/components/motion/radio';
import { Checkbox } from '@/components/ui/checkbox';
import type { Ownership, VoiceScope } from '@/lib/voice-import/types';
import type { BrainTranslate } from '../brain-types';

export interface ConsentValue {
  ownership: Ownership | '';
  voiceScope: VoiceScope | '';
  confirmed: boolean;
}

export const EMPTY_CONSENT: ConsentValue = { ownership: '', voiceScope: '', confirmed: false };

export function consentReady(value: ConsentValue): value is { ownership: Ownership; voiceScope: VoiceScope; confirmed: true } {
  return Boolean(value.ownership && value.voiceScope && value.confirmed);
}

/** A choice tile: quiet at rest, selected glass when chosen (the same tile the voice setup uses). */
const CHOICE = 'rafii-quiet data-[state=checked]:rafii-glass-selected min-h-11 rounded-[var(--rafii-radius-control)] p-3.5 transition-colors motion-reduce:transition-none';

/**
 * One consent for a whole account or upload, never one per post: whose writing it is, whether it blends into this
 * brand's voice, what is kept and how to delete it. Changing an answer clears the confirmation, so the tick always
 * refers to the answers on screen.
 */
export function ConsentStep({ value, onChange, disabled, t }: { value: ConsentValue; onChange: (next: ConsentValue) => void; disabled?: boolean; t: BrainTranslate }) {
  const id = useId();
  return (
    <div className='flex min-w-0 flex-col gap-5' data-testid='voice-import-consent'>
      <fieldset className='flex min-w-0 flex-col gap-2' disabled={disabled}>
        <legend id={`${id}-owner`} className='text-foreground mb-2 text-sm font-medium'>
          {t('Whose writing is this?', '這些文字是誰寫的？', '这些文字是谁写的？')}
        </legend>
        <RadioGroup aria-labelledby={`${id}-owner`} value={value.ownership} onValueChange={(next) => onChange({ ...value, ownership: next as Ownership, confirmed: false })} className='grid gap-2 sm:grid-cols-3'>
          <RadioGroupItem id={`${id}-mine`} value='mine' disabled={disabled} className={CHOICE} label={t('Mine', '我自己', '我自己')} description={t('I wrote these posts myself.', '這些貼文由我本人撰寫。', '这些帖子由我本人撰写。')} />
          <RadioGroupItem id={`${id}-org`} value='my_organisation' disabled={disabled} className={CHOICE} label={t('My organisation’s', '我的機構', '我的机构')} description={t('A team writes them for one brand.', '由團隊為同一個品牌撰寫。', '由团队为同一个品牌撰写。')} />
          <RadioGroupItem
            id={`${id}-mixed`}
            value='mixed_authors'
            disabled={disabled}
            className={CHOICE}
            label={t('Several authors', '多位作者', '多位作者')}
            description={t('Different people wrote them. No post counts as yours until you mark it.', '由不同人撰寫。在你標記之前，沒有貼文會當作是你寫的。', '由不同人撰写。在你标记之前，没有帖子会当作是你写的。')}
          />
        </RadioGroup>
      </fieldset>

      <fieldset className='flex min-w-0 flex-col gap-2' disabled={disabled}>
        <legend id={`${id}-scope`} className='text-foreground mb-2 text-sm font-medium'>
          {t('How should Rafii use it?', 'Rafii 應如何使用？', 'Rafii 应如何使用？')}
        </legend>
        <RadioGroup aria-labelledby={`${id}-scope`} value={value.voiceScope} onValueChange={(next) => onChange({ ...value, voiceScope: next as VoiceScope, confirmed: false })} className='grid gap-2 sm:grid-cols-2'>
          <RadioGroupItem
            id={`${id}-brand`}
            value='brand'
            disabled={disabled}
            className={CHOICE}
            label={t('Blend into this brand’s voice', '融入此品牌的風格', '融入此品牌的风格')}
            description={t('These posts help shape the one voice this workspace writes in.', '這些貼文會用來塑造此工作區的單一寫作風格。', '这些帖子会用来塑造此工作区的单一写作风格。')}
          />
          <RadioGroupItem
            id={`${id}-separate`}
            value='separate'
            disabled={disabled}
            className={CHOICE}
            label={t('Keep it separate', '分開保留', '分开保留')}
            description={t('Rafii learns this account on its own and never mixes it into drafts for other accounts.', 'Rafii 會獨立學習此帳戶，絕不混入其他帳戶的草稿。', 'Rafii 会独立学习此账户，绝不混入其他账户的草稿。')}
          />
        </RadioGroup>
      </fieldset>

      <dl className='text-muted-foreground flex flex-col gap-3 text-xs leading-relaxed'>
        <div>
          <dt className='text-foreground font-medium'>{t('What Rafii keeps', 'Rafii 會保留甚麼', 'Rafii 会保留什么')}</dt>
          <dd>
            {t(
              'The text of each post with its date, link and language, so every trait in your profile can show the posts behind it. Images and video are not fetched or analysed.',
              '每篇貼文的文字、日期、連結及語言，讓風格檔案中的每項特徵都能顯示背後的貼文。不會擷取或分析圖片及影片。',
              '每篇帖子的文字、日期、链接及语言，让风格档案中的每项特征都能显示背后的帖子。不会抓取或分析图片及视频。'
            )}
          </dd>
        </div>
        <div>
          <dt className='text-foreground font-medium'>{t('How to delete it', '如何刪除', '如何删除')}</dt>
          <dd>
            {t(
              'Delete the import at any time to remove every post it supplied. Disconnecting the account removes the posts read through it; posts from an uploaded file stay until you delete that import.',
              '你可隨時刪除匯入，移除它提供的所有貼文。中斷帳戶連接會移除經該連接讀取的貼文；來自上載檔案的貼文會保留，直至你刪除該次匯入。',
              '你可随时删除导入，移除它提供的所有帖子。断开账户连接会移除经该连接读取的帖子；来自上传文件的帖子会保留，直至你删除该次导入。'
            )}
          </dd>
        </div>
      </dl>

      <label className='text-foreground flex min-h-11 items-center gap-3 text-sm'>
        <Checkbox checked={value.confirmed} disabled={disabled || !value.ownership || !value.voiceScope} onCheckedChange={(checked) => onChange({ ...value, confirmed: checked === true })} />
        {t('I have the right to use this writing, and Rafii may keep the text for this purpose.', '我有權使用這些文字，並同意 Rafii 為此目的保留文字內容。', '我有权使用这些文字，并同意 Rafii 为此目的保留文字内容。')}
      </label>
    </div>
  );
}
