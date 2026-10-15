'use client';

import { useCallback, useEffect, useId, useRef, useState } from 'react';
import { useBrainCopy } from './brain-copy';
import { useGenUiLocale } from '@/features/agent/generative-ui/core/locale';
import { appendOwnedPage, coverageSummary, loadedPosts, MAX_PREVIEW_PAGES, MAX_SELECTED_POSTS, selectedReceipts } from '@/lib/channels/owned-posts';
import Link from 'next/link';
import Image from 'next/image';
import { useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { Icons } from '@/components/icons';
import { StateMessage } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Band, FIELD_CLASS, SelectField } from '@/features/workspace/rafii-parts';
import { ApiError } from '@/lib/api/client';
import { keys, useChannels } from '@/lib/api/hooks';
import type { OwnedPostPage } from '@/lib/api/types';
import { historyBlocker } from '@/lib/channels/onboarding';
import { useWorkspaceApi } from '@/lib/workspace/provider';

export function OwnedPostsPicker({ revision, isOwner, preferredPlatform, autoPropose = false }: { revision: number; isOwner: boolean; preferredPlatform?: string; autoPropose?: boolean }) {
  const t = useBrainCopy();
  const { workspaceId } = useWorkspaceApi();
  if (!isOwner || !workspaceId) return <p className='text-muted-foreground text-xs'>{t('Only an owner can import posts.', '只有擁有者可匯入貼文。', '仅所有者可导入帖子。')}</p>;
  // A workspace switch destroys previews and selection receipts, not just the account dropdown.
  return <PickerSession key={workspaceId} workspaceId={workspaceId} revision={revision} preferredPlatform={preferredPlatform} autoPropose={autoPropose} />;
}

function PickerSession({ workspaceId, revision, preferredPlatform, autoPropose }: { workspaceId: string; revision: number; preferredPlatform?: string; autoPropose: boolean }) {
  const t = useBrainCopy();
  const locale = useGenUiLocale();
  const selectionId = useId();
  const { api } = useWorkspaceApi();
  const channels = useChannels();
  const cache = useQueryClient();
  const [chosenConnectionId, setConnectionId] = useState('');
  const [pages, setPages] = useState<OwnedPostPage[]>([]);
  const page = pages.at(-1);
  const [labels, setLabels] = useState<Record<string, string>>({});
  const [mediaType, setMediaType] = useState('');
  const autoStarted = useRef(false);
  const [selected, setSelected] = useState<string[]>([]);
  const [query, setQuery] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState<'loading' | 'importing' | null>(null);
  const [error, setError] = useState('');
  const request = useRef(0);
  useEffect(
    () => () => {
      request.current += 1;
    },
    []
  );
  const accounts = channels.data?.channels.filter((item) => ['Instagram', 'LinkedIn'].includes(item.platform) && (!preferredPlatform || item.platform === preferredPlatform)) ?? [];
  const connectionId = chosenConnectionId || (autoPropose && accounts.length === 1 ? accounts[0].id : '');
  const account = accounts.find((item) => item.id === connectionId);
  const provider = channels.data?.providers.find((item) => item.platform === account?.platform);
  const blocker = historyBlocker(account, provider);
  const posts = loadedPosts(pages);
  const skipped = pages.reduce((sum, item) => sum + item.skippedCount, 0);
  const visible = posts.filter((post) => post.text.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()) && (!mediaType || post.mediaType === mediaType));

  const load = useCallback(
    async (cursor?: string) => {
      if (!connectionId || blocker || busy) return;
      const current = ++request.current;
      setBusy('loading');
      setError('');
      try {
        const next = await api.ownedPosts(workspaceId, connectionId, cursor);
        if (request.current !== current) return;
        const combined = appendOwnedPage(pages, next, cursor);
        setPages(combined);
        if (!cursor) {
          setSelected(
            autoPropose
              ? loadedPosts(combined)
                  .filter((post) => Number.isFinite(Date.parse(post.publishedAt)))
                  .toSorted((a, b) => Date.parse(b.publishedAt) - Date.parse(a.publishedAt))
                  .slice(0, 10)
                  .map((post) => post.id)
              : []
          );
          setLabels({});
          setQuery('');
          setMediaType('');
        }
        setConfirmed(false);
      } catch (err) {
        if (request.current === current) setError(err instanceof Error ? err.message : t('Couldn’t load posts. Try again.', '未能載入貼文，請再試一次。', '无法加载帖子，请重试。'));
      } finally {
        if (request.current === current) setBusy(null);
      }
    },
    [api, workspaceId, connectionId, blocker, busy, pages, autoPropose, t]
  );

  useEffect(() => {
    if (!autoPropose || autoStarted.current || !connectionId || blocker) return;
    autoStarted.current = true;
    void load();
  }, [autoPropose, connectionId, blocker, load]);

  async function retain() {
    if (!page || !selected.length || !confirmed || busy || blocker) return;
    const current = ++request.current;
    setBusy('importing');
    setError('');
    try {
      const selections = selectedReceipts(pages, selected);
      const selectedLabels = Object.fromEntries(selected.filter((id) => labels[id]).map((id) => [id, labels[id]]));
      const snapshot = await api.importOwnedPostSelection(workspaceId, connectionId, selections, selectedLabels, revision);
      if (request.current !== current) return;
      cache.setQueryData(keys.snapshot(workspaceId), snapshot);
      void cache.invalidateQueries({ queryKey: keys.audit(workspaceId) });
      setSelected([]);
      setConfirmed(false);
      toast.success(t('Posts retained. Select them below to allow analysis.', '貼文已儲存，請在下方選取並授權分析。', '帖子已保存，请在下方选择并授权分析。'));
    } catch (err) {
      if (request.current === current) {
        setError(err instanceof Error ? err.message : t('Couldn’t retain these posts. Try again.', '未能儲存這些貼文，請再試一次。', '无法保存这些帖子，请重试。'));
        if (err instanceof ApiError && err.status === 409) void cache.invalidateQueries({ queryKey: keys.snapshot(workspaceId) });
      }
    } finally {
      if (request.current === current) setBusy(null);
    }
  }

  return (
    <Band as='section' data-tour='owned-posts-picker' aria-label={t('Import my social posts', '匯入我的社交貼文', '导入我的社交帖子')}>
      <h3 className='text-foreground text-sm font-medium'>{autoPropose ? t('Review the suggested posts', '審閱建議的貼文', '审阅建议的帖子') : t('Choose from my social posts', '從我的社交貼文選取', '从我的社交帖子选择')}</h3>
      <p className='text-muted-foreground text-xs'>
        {autoPropose ? t('Rafii picked up to 10 recent posts. Nothing is kept or analysed until you confirm.', 'Rafii 已選出最多 10 篇近期貼文，確認前不會儲存或分析。', 'Rafii 已选出最多 10 篇近期帖子，确认前不会保存或分析。') : t('Read-only. Nothing is published or analysed.', '唯讀操作，不會發佈或分析。', '只读操作，不会发布或分析。')}
      </p>
      {channels.isError && (
        <StateMessage
          kind='error'
          layout='inline'
          title={t('Couldn’t load accounts.', '未能載入帳戶。', '无法加载账户。')}
          action={
            <Button variant='glass' size='control' onClick={() => void channels.refetch()}>
              <Icons.refresh /> {t('Retry', '重試', '重试')}
            </Button>
          }
        />
      )}
      <SelectField
        label={t('Account', '帳戶', '账户')}
        aria-label={t('Account to read posts from', '讀取貼文的帳戶', '读取帖子的账户')}
        value={connectionId}
        disabled={Boolean(busy) || channels.isPending}
        onChange={(event) => {
          request.current += 1;
          setConnectionId(event.target.value);
          setPages([]);
          setSelected([]);
          setLabels({});
          setConfirmed(false);
          setError('');
        }}
      >
        <option value=''>{t('Choose an Instagram or LinkedIn account', '選擇 Instagram 或 LinkedIn 帳戶', '选择 Instagram 或 LinkedIn 账户')}</option>
        {accounts.map((item) => (
          <option key={item.id} value={item.id}>
            {item.platform} · {item.account}
          </option>
        ))}
      </SelectField>
      {blocker && (
        <p role='status' className='text-muted-foreground text-xs'>
          {blocker}{' '}
          <a href='#manual-writing-samples' className='rafii-focus text-foreground rounded-sm underline underline-offset-4'>
            {t('Add writing manually', '手動加入文字', '手动添加文字')}
          </a>
        </p>
      )}
      <div className='flex flex-wrap items-center gap-3'>
        <Button size='control' variant='glass' disabled={Boolean(busy) || Boolean(blocker)} onClick={() => void load()}>
          {busy === 'loading' ? (
            <>
              <Icons.spinner className='motion-safe:animate-spin' /> {t('Reading posts…', '正在讀取貼文…', '正在读取帖子…')}
            </>
          ) : (
            t('Load my posts', '載入我的貼文', '加载我的帖子')
          )}
        </Button>
        <Link className='rafii-focus text-foreground rounded-sm text-sm underline underline-offset-4' href='/app/channels'>
          {t('Connect or manage accounts', '連接或管理帳戶', '连接或管理账户')}
        </Link>
      </div>
      {error && <StateMessage kind='error' layout='inline' title={error} />}
      {page && (
        <div className='flex flex-col gap-3'>
          <p role='status' className='text-muted-foreground text-xs'>
            {coverageSummary(pages)}
            {skipped > 0 ? ` ${skipped} skipped.` : ''}
          </p>
          <div className='grid gap-3 sm:grid-cols-[minmax(0,1fr)_14rem]'>
            <Input aria-label={t('Search retrieved posts', '搜尋已取得的貼文', '搜索已获取的帖子')} placeholder={t('Search loaded posts', '搜尋已載入的貼文', '搜索已加载的帖子')} value={query} onChange={(event) => setQuery(event.target.value)} className={FIELD_CLASS} />
            <SelectField label={t('Media type', '媒體類型', '媒体类型')} hideLabel aria-label={t('Filter retrieved posts by media type', '按媒體類型篩選貼文', '按媒体类型筛选帖子')} value={mediaType} onChange={(event) => setMediaType(event.target.value)}>
              <option value=''>{t('All media', '所有媒體', '所有媒体')}</option>
              {[...new Set(posts.map((post) => post.mediaType).filter(Boolean))].map((type) => (
                <option key={type} value={type}>
                  {type}
                </option>
              ))}
            </SelectField>
          </div>
          <Button
            size='default'
            variant='glass'
            className='min-h-11 w-fit'
            disabled={Boolean(busy) || !visible.length}
            onClick={() => {
              setSelected((ids) => [...new Set([...ids, ...visible.map((post) => post.id)])].slice(0, MAX_SELECTED_POSTS));
              setConfirmed(false);
            }}
          >
            {t('Select all shown', '選取所有顯示的貼文', '选择所有显示的帖子')}
          </Button>
          {!visible.length && <StateMessage kind='empty' layout='inline' title={posts.length ? t('No matching posts', '沒有符合條件的貼文', '没有符合条件的帖子') : t('No captions in the loaded posts', '已載入貼文沒有文字說明', '已加载帖子没有文字说明')} />}
          <ul className='grid gap-3 sm:grid-cols-2'>
            {visible.map((post) => (
              <li key={post.id} className='rafii-glass flex min-w-0 flex-col gap-3 rounded-[var(--rafii-radius-card)] p-4'>
                {post.thumbnailUrl && <Image src={post.thumbnailUrl} alt={t('Post preview', '貼文預覽', '帖子预览')} width={480} height={320} unoptimized loading='lazy' referrerPolicy='no-referrer' className='max-h-44 w-full rounded-[var(--rafii-radius-control)] object-contain' />}
                <div className='flex items-start gap-2'>
                  <label htmlFor={`${selectionId}-${post.id}`} className='flex size-11 shrink-0 cursor-pointer items-center justify-center'><span className='sr-only'>{`${t('Choose post', '選取貼文', '选择帖子')} ${post.id}`}</span><Checkbox
                    id={`${selectionId}-${post.id}`}
                    className='mt-0.5'
                    aria-label={`${t('Choose post', '選取貼文', '选择帖子')} ${post.id}`}
                    checked={selected.includes(post.id)}
                    disabled={Boolean(busy)}
                    onCheckedChange={(checked) => {
                      setSelected((ids) => (checked === true ? [...new Set([...ids, post.id])].slice(0, MAX_SELECTED_POSTS) : ids.filter((id) => id !== post.id)));
                      setConfirmed(false);
                    }}
                  /></label>
                  <p dir='auto' className='text-foreground max-h-48 overflow-y-auto text-sm break-words whitespace-pre-wrap'>{post.text}</p>
                </div>
                <SelectField
                  label={t('Writing classification', '文字分類', '文字分类')}
                  aria-label={`${t('Classify post', '分類貼文', '分类帖子')} ${post.id}`}
                  value={labels[post.id] ?? ''}
                  disabled={Boolean(busy)}
                  onChange={(event) => {
                    setLabels((current) => ({ ...current, [post.id]: event.target.value }));
                    setConfirmed(false);
                  }}
                >
                  <option value=''>{t('Unclassified', '未分類', '未分类')}</option>
                  <option value='representative'>{t('Representative', '具代表性', '有代表性')}</option>
                  <option value='sponsored'>{t('Sponsored', '贊助內容', '赞助内容')}</option>
                  <option value='outdated'>{t('Outdated', '已過時', '已过时')}</option>
                  <option value='ai_generated'>{t('AI-generated', 'AI 生成', 'AI 生成')}</option>
                  <option value='guest'>{t('Guest writing', '他人作品', '他人作品')}</option>
                </SelectField>
                <Button
                  size='default'
                  variant='quiet'
                  className='min-h-11 w-fit'
                  disabled={Boolean(busy) || !selected.includes(post.id)}
                  onClick={() => {
                    setSelected((ids) => ids.filter((id) => id !== post.id));
                    setConfirmed(false);
                  }}
                >
                  {t('Deselect', '取消選取', '取消选择')}
                </Button>
                <div className='text-muted-foreground flex flex-wrap gap-2 text-xs'>
                  <span>{post.publishedAt ? locale.formatDateTime(post.publishedAt) : t('Date unavailable', '未有日期', '暂无日期')}</span>
                  {post.permalink && (
                    <a href={post.permalink} target='_blank' rel='noopener noreferrer' className='rafii-focus text-foreground rounded-sm underline underline-offset-4'>
                      {t('View original', '查看原文', '查看原文')}
                    </a>
                  )}
                </div>
              </li>
            ))}
          </ul>
          <label htmlFor='owned-post-authorship-consent' className='text-foreground flex min-h-11 items-center gap-2 text-xs leading-relaxed'>
            <Checkbox id='owned-post-authorship-consent' className='mt-0.5' checked={confirmed} disabled={Boolean(busy) || selected.length === 0} onCheckedChange={(checked) => setConfirmed(checked === true)} aria-label={t('Confirm selected captions are my own writing', '確認所選文字為本人作品', '确认所选文字为本人作品')} />
            {t('I wrote the selected captions and consent to retaining them as private samples. Leave out guest, quoted or unrepresentative posts. This doesn’t allow AI use.', '所選文字為本人作品，我同意私人儲存為範例。請排除他人作品、引文及不具代表性的貼文，這並不授權 AI 使用。', '所选文字为本人作品，我同意私密保存为样本。请排除他人作品、引文及不具代表性的帖子，这并不授权 AI 使用。')}
          </label>
          <div className='flex flex-wrap gap-2'>
            <Button size='control' variant='action' disabled={Boolean(busy) || !selected.length || !confirmed || Boolean(blocker)} onClick={() => void retain()}>
              {busy === 'importing' ? (
                <>
                  <Icons.spinner className='motion-safe:animate-spin' /> {t('Retaining…', '正在儲存…', '正在保存…')}
                </>
              ) : (
                `${t('Retain selected posts', '儲存所選貼文', '保存所选帖子')} (${selected.length})`
              )}
            </Button>
            <Button
              size='control'
              variant='quiet'
              disabled={Boolean(busy) || !selected.length}
              onClick={() => {
                setSelected([]);
                setConfirmed(false);
              }}
            >
              Clear selection
            </Button>
            <Button size='control' variant='glass' disabled={Boolean(busy) || !page.nextCursor || pages.length >= MAX_PREVIEW_PAGES || Boolean(blocker)} onClick={() => void load(page.nextCursor ?? undefined)}>
              Load more posts
            </Button>
          </div>
          <p className='text-muted-foreground text-xs leading-relaxed'>{selected.length} {t('selected · up to 50 at once · reload after 10 minutes', '已選取 · 每次最多 50 篇 · 10 分鐘後請重新載入', '已选择 · 每次最多 50 篇 · 10 分钟后请重新加载')}</p>
        </div>
      )}
    </Band>
  );
}
