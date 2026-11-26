'use client';

import { useState } from 'react';
import { useQueryClient, type InfiniteData } from '@tanstack/react-query';
import { Icons } from '@/components/icons';
import { SegmentedControl, StateMessage } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { useGenUiLocale } from '@/features/agent/generative-ui/core/locale';
import { exclusionLabel, languageName, platformName } from '@/lib/voice-import/labels';
import type { Language } from '@/lib/voice-import/labels';
import type { PostCorrection, VoicePost, VoicePostPage } from '@/lib/voice-import/types';
import type { BrainTranslate } from '../brain-types';
import { useEvidencePosts, useInvalidateVoiceImports, useVoiceImportApi, useVoicePosts } from './use-voice-import';

type StatusFilter = 'all' | 'eligible' | 'retrieved' | 'excluded';

/** Only an https link is ever rendered as a link; anything else from a post record stays text. */
const safeLink = (url: string | null | undefined) => (typeof url === 'string' && /^https:\/\//i.test(url) ? url : null);

function PostMeta({ post, t }: { post: VoicePost; t: BrainTranslate }) {
  const locale = useGenUiLocale();
  const link = safeLink(post.permalink);
  return (
    <footer className='text-muted-foreground mt-1 flex flex-wrap gap-x-2 gap-y-1 text-xs'>
      <span>{post.publishedAt ? locale.formatDate(post.publishedAt) : t('Date unavailable', '未有日期', '暂无日期')}</span>
      <span>{platformName(post.provider)}</span>
      {link && (
        <a href={link} target='_blank' rel='noopener noreferrer' className='rafii-focus text-foreground rounded-sm underline underline-offset-4'>
          {t('View original', '查看原文', '查看原文')}
        </a>
      )}
    </footer>
  );
}

/**
 * The posts behind one trait, loaded from the posts route when the person opens the trait. Excerpts are shown to
 * workspace members and kept in the page's query cache only: nothing here writes them into workspace state.
 */
export function TraitEvidence({ postIds, count, counter, t }: { postIds: string[]; count?: number; counter?: number; t: BrainTranslate }) {
  const locale = useGenUiLocale();
  const evidence = useEvidencePosts(postIds, true);
  const facts = [
    count !== undefined && `${t('Posts that show this', '顯示此特徵的貼文', '显示此特征的帖子')}: ${locale.formatNumber(count)}`,
    counter !== undefined && `${t('Posts that do not', '不符合的貼文', '不符合的帖子')}: ${locale.formatNumber(counter)}`,
    postIds.length > 0 && `${t('Cited here', '此處引用', '此处引用')}: ${locale.formatNumber(postIds.length)}`
  ].filter(Boolean);
  return (
    <div className='flex min-w-0 flex-col gap-2' data-testid='trait-evidence'>
      {facts.length > 0 && <p className='text-muted-foreground text-xs'>{facts.join(' · ')}</p>}
      {evidence.posts.map((post) => (
        <blockquote key={post.id} className='my-1 border-s-2 ps-3 text-sm'>
          <p dir='auto' className='break-words whitespace-pre-wrap'>
            {post.excerpt}
          </p>
          <PostMeta post={post} t={t} />
        </blockquote>
      ))}
      <div role='status' aria-live='polite' className='text-muted-foreground text-xs'>
        {evidence.failed ? (
          <p>{t('The posts behind this trait could not be loaded.', '未能載入此特徵背後的貼文。', '无法加载此特征背后的帖子。')}</p>
        ) : evidence.searching ? (
          <p className='flex items-center gap-2'>
            <Icons.spinner className='size-3.5 motion-safe:animate-spin' aria-hidden /> {t('Loading the posts behind this trait…', '正在載入此特徵背後的貼文…', '正在加载此特征背后的帖子…')}
          </p>
        ) : evidence.paused ? (
          <p>
            {t('Cited posts not found yet', '尚未找到的引用貼文', '尚未找到的引用帖子')}: {locale.formatNumber(evidence.missing)}.{' '}
            <button type='button' className='rafii-focus text-foreground min-h-11 rounded-sm underline underline-offset-4' onClick={evidence.lookFurther}>
              {t('Look further back', '繼續往前尋找', '继续往前查找')}
            </button>
          </p>
        ) : evidence.missing > 0 ? (
          <p>
            {t('Cited posts no longer stored', '已不再儲存的引用貼文', '已不再保存的引用帖子')}: {locale.formatNumber(evidence.missing)}
          </p>
        ) : null}
      </div>
    </div>
  );
}

function postState(post: VoicePost, t: BrainTranslate, language: Language): string {
  if (post.status === 'eligible') return t('Can be used', '可使用', '可使用');
  if (post.status === 'excluded') return `${t('Left out', '未採用', '未采用')}: ${exclusionLabel(post.exclusionReason ?? 'manual', language)}`;
  if (post.status === 'gone') return t('No longer on the platform', '平台上已不存在', '平台上已不存在');
  return t('Waiting: author not confirmed', '等待中：尚未確認作者', '等待中：尚未确认作者');
}

/**
 * Posts of one account, 50 at a time, with the corrections a person can make: who wrote a post, whether it shows
 * their voice as it is now, and whether to leave it out. Each correction is one request and changes only that post.
 */
export function EvidenceBrowser({ provider, accountKey, canEdit, t }: { provider: string; accountKey: string; canEdit: boolean; t: BrainTranslate }) {
  const locale = useGenUiLocale();
  const client = useQueryClient();
  const { api, w } = useVoiceImportApi();
  const invalidate = useInvalidateVoiceImports();
  const [filter, setFilter] = useState<StatusFilter>('all');
  const [busy, setBusy] = useState('');
  const [failure, setFailure] = useState<{ id: string; message: string } | null>(null);
  const query = useVoicePosts({ provider, accountKey, status: filter === 'all' ? undefined : filter });
  const posts = query.data?.pages.flatMap((page) => page.posts ?? []) ?? [];

  async function correct(post: VoicePost, body: PostCorrection) {
    if (busy) return;
    setBusy(post.id);
    setFailure(null);
    try {
      const { post: next } = await api.correctPost(w, post.id, body);
      // Every cached list of this workspace's posts shows the corrected post; the receipt's counts are read again.
      client.setQueriesData<InfiniteData<VoicePostPage>>({ queryKey: ['voice-imports', w, 'posts'] }, (data) =>
        data ? { ...data, pages: data.pages.map((page) => ({ ...page, posts: (page.posts ?? []).map((item) => (item.id === next.id ? { ...item, ...next } : item)) })) } : data
      );
      void invalidate();
    } catch (error) {
      setFailure({ id: post.id, message: error instanceof Error ? error.message : '' });
    } finally {
      setBusy('');
    }
  }

  return (
    <div className='flex min-w-0 flex-col gap-3' data-testid='voice-import-evidence'>
      <SegmentedControl
        label={t('Which posts to show', '顯示哪些貼文', '显示哪些帖子')}
        widths='content'
        value={filter}
        onChange={setFilter}
        options={[
          { value: 'all', label: t('All', '全部', '全部') },
          { value: 'eligible', label: t('Can be used', '可使用', '可使用') },
          { value: 'retrieved', label: t('Waiting', '等待中', '等待中') },
          { value: 'excluded', label: t('Left out', '未採用', '未采用') }
        ]}
      />
      {query.isPending && <StateMessage kind='loading' layout='inline' title={t('Loading posts…', '正在載入貼文…', '正在加载帖子…')} />}
      {query.isError && (
        <StateMessage
          kind='error'
          layout='inline'
          title={query.error instanceof Error && query.error.message ? query.error.message : t('Posts could not be loaded.', '未能載入貼文。', '无法加载帖子。')}
          action={
            <Button variant='glass' className='min-h-11' onClick={() => void query.refetch()}>
              <Icons.refresh aria-hidden /> {t('Retry', '重試', '重试')}
            </Button>
          }
        />
      )}
      {query.isSuccess && posts.length === 0 && <StateMessage kind='empty' layout='inline' title={t('No posts here.', '這裡沒有貼文。', '这里没有帖子。')} />}
      <ul className='flex min-w-0 flex-col gap-2'>
        {posts.map((post) => {
          const mine = post.authorship === 'self' || post.authorship === 'team';
          const left = post.status === 'excluded' && post.exclusionReason === 'manual';
          const working = busy === post.id;
          return (
            <li key={post.id} className='rafii-quiet flex min-w-0 flex-col gap-2 rounded-[var(--rafii-radius-control)] p-3'>
              <p dir='auto' className='text-sm break-words whitespace-pre-wrap'>
                {post.excerpt}
              </p>
              <PostMeta post={post} t={t} />
              <p className='text-muted-foreground flex flex-wrap gap-x-2 gap-y-1 text-xs'>
                <span className='text-foreground font-medium'>{postState(post, t, locale.language)}</span>
                {post.language && <span>{languageName(post.language, locale.language)}</span>}
                {post.authorship === 'team' && <span>{t('Written by your team', '由你的團隊撰寫', '由你的团队撰写')}</span>}
                {post.label === 'representative' && <span>{t('Marked representative', '已標記為具代表性', '已标记为有代表性')}</span>}
                {post.label === 'outdated' && <span>{t('Marked old style', '已標記為舊風格', '已标记为旧风格')}</span>}
              </p>
              {canEdit && post.status !== 'gone' && (
                <div className='flex flex-wrap gap-2'>
                  {!mine && (
                    <Button variant='quiet' className='min-h-11' disabled={working} onClick={() => void correct(post, { authorship: 'self' })}>
                      {t('I wrote this', '這是我寫的', '这是我写的')}
                    </Button>
                  )}
                  <Button variant={post.authorship === 'guest' ? 'glass' : 'quiet'} className='min-h-11' aria-pressed={post.authorship === 'guest'} disabled={working || post.authorship === 'guest'} onClick={() => void correct(post, { authorship: 'guest' })}>
                    {t('Someone else wrote this', '這是別人寫的', '这是别人写的')}
                  </Button>
                  <Button variant={post.label === 'outdated' ? 'glass' : 'quiet'} className='min-h-11' aria-pressed={post.label === 'outdated'} disabled={working} onClick={() => void correct(post, { label: post.label === 'outdated' ? null : 'outdated' })}>
                    {t('Old style', '舊風格', '旧风格')}
                  </Button>
                  <Button
                    variant={post.label === 'representative' ? 'glass' : 'quiet'}
                    className='min-h-11'
                    aria-pressed={post.label === 'representative'}
                    disabled={working}
                    onClick={() => void correct(post, { label: post.label === 'representative' ? null : 'representative' })}
                  >
                    {t('Representative', '具代表性', '有代表性')}
                  </Button>
                  <Button variant={left ? 'glass' : 'quiet'} className='min-h-11' aria-pressed={left} disabled={working} onClick={() => void correct(post, { excluded: !left })}>
                    {t('Leave this post out', '不採用此貼文', '不采用此帖子')}
                  </Button>
                </div>
              )}
              {failure?.id === post.id && (
                <p role='alert' className='text-xs'>
                  {failure.message || t('That change was not saved. Try again.', '未能儲存此變更，請再試一次。', '无法保存此更改，请重试。')}
                </p>
              )}
            </li>
          );
        })}
      </ul>
      {query.hasNextPage && (
        <div>
          <Button variant='glass' className='min-h-11' disabled={query.isFetchingNextPage} onClick={() => void query.fetchNextPage()}>
            {query.isFetchingNextPage ? t('Loading…', '正在載入…', '正在加载…') : t('Show more posts', '顯示更多貼文', '显示更多帖子')}
          </Button>
        </div>
      )}
    </div>
  );
}
