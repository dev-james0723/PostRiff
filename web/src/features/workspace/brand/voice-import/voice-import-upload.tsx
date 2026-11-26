'use client';

import { useEffect, useId, useRef, useState } from 'react';
import { Icons } from '@/components/icons';
import { StateMessage } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Progress } from '@/components/ui/progress';
import { useGenUiLocale } from '@/features/agent/generative-ui/core/locale';
import { combineExports, fileKind, isPostFile, itemRange, parseExport } from '@/lib/voice-import';
import { exportAccountKey, planBatches, sendBatches } from '@/lib/voice-import/batches';
import type { BatchPlan, SendProgress } from '@/lib/voice-import/batches';
import type { AccountReceipt } from '@/lib/voice-import/coverage';
import { exportGuide, noteText } from '@/lib/voice-import/guides';
import { platformName } from '@/lib/voice-import/labels';
import { decodeBytes } from '@/lib/voice-import/text';
import type { CombinedExport, ExportNote, ParsedExport } from '@/lib/voice-import/types';
import { FIELD_CLASS, SelectField } from '../../rafii-parts';
import type { BrainTranslate } from '../brain-types';
import { ConsentStep, consentReady, EMPTY_CONSENT } from './voice-import-consent';
import type { ConsentValue } from './voice-import-consent';
import { useInvalidateVoiceImports, useVoiceImportApi } from './use-voice-import';

/** A post file larger than this is not opened: reading it would hold several times its size in memory. */
const MAX_FILE_BYTES = 100 * 1024 * 1024;
const NEW_ACCOUNT = '';

type FileState = 'read' | 'html' | 'archive' | 'other' | 'too_large' | 'unrecognised' | 'other_platform' | 'unreadable';
interface FileReport {
  name: string;
  state: FileState;
  posts?: number;
  notes?: ExportNote[];
  provider?: string;
}
interface Picked {
  reports: FileReport[];
  /** Files in a picked folder that are not post files: never opened. */
  unopened: number;
  combined: CombinedExport | null;
  plan: BatchPlan;
}
type Phase = 'idle' | 'reading' | 'ready' | 'sending' | 'stopped' | 'done';

async function readFiles(files: File[], fromFolder: boolean, provider: string): Promise<Picked> {
  const reports: FileReport[] = [];
  const parsed: ParsedExport[] = [];
  const seen = new Set<string>();
  let unopened = 0;
  for (const file of files) {
    const name = file.webkitRelativePath || file.name;
    if (seen.has(`${name}:${file.size}`)) continue;
    seen.add(`${name}:${file.size}`);
    if (fromFolder && !isPostFile(name)) {
      unopened++;
      continue;
    }
    const kind = fileKind(name);
    if (kind !== 'text') {
      reports.push({ name, state: kind });
      continue;
    }
    if (file.size > MAX_FILE_BYTES) {
      reports.push({ name, state: 'too_large' });
      continue;
    }
    try {
      const result = parseExport({ name, text: decodeBytes(new Uint8Array(await file.arrayBuffer())) });
      if (!result) reports.push({ name, state: 'unrecognised' });
      else if (result.provider !== provider) reports.push({ name, state: 'other_platform', provider: result.provider });
      else {
        parsed.push(result);
        reports.push({ name, state: 'read', posts: result.items.length, notes: result.notes });
      }
    } catch {
      reports.push({ name, state: 'unreadable' });
    }
  }
  const combined = combineExports(parsed)[0] ?? null;
  return { reports, unopened, combined, plan: planBatches(combined?.items ?? []) };
}

/**
 * Upload of a platform export. The files are read here, in the browser; nothing of them is uploaded. Only the posts
 * found go to the workspace, at most 200 and under 512 kB per request, after one consent for the whole upload.
 */
export function UploadFlow({ provider, receipts, canManage, t, onClose }: { provider: string; receipts: AccountReceipt[]; canManage: boolean; t: BrainTranslate; onClose: () => void }) {
  const id = useId();
  const locale = useGenUiLocale();
  const { api, w } = useVoiceImportApi();
  const invalidate = useInvalidateVoiceImports();
  const fileInput = useRef<HTMLInputElement>(null);
  const folderInput = useRef<HTMLInputElement>(null);
  const alive = useRef(true);
  const [phase, setPhase] = useState<Phase>('idle');
  const [picked, setPicked] = useState<Picked | null>(null);
  const [account, setAccount] = useState(NEW_ACCOUNT);
  const [label, setLabel] = useState('');
  const [consent, setConsent] = useState<ConsentValue>(EMPTY_CONSENT);
  const [progress, setProgress] = useState<SendProgress | null>(null);
  const [resume, setResume] = useState<{ importId: string; next: number } | null>(null);
  const [error, setError] = useState('');

  const name = platformName(provider);
  const guide = exportGuide(provider);
  const known = receipts.filter((receipt) => receipt.provider === provider);
  const total = picked?.plan.batches.reduce((sum, batch) => sum + batch.length, 0) ?? 0;
  const range = picked?.combined ? itemRange(picked.combined.items) : null;
  const existing = known.find((receipt) => receipt.accountKey === account);
  const accountKey = existing ? existing.accountKey : exportAccountKey(label);
  const accountLabel = existing ? existing.label : label.trim();
  const sending = phase === 'sending';
  const number = (value: number) => locale.formatNumber(value);

  // Set on every mount, not only cleared on unmount: React may mount, unmount and mount again (Strict Mode in
  // development, or a remount), and a ref left false would stop every read and send from finishing.
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  // Leaving the page mid-upload leaves a half-received import behind: ask first.
  useEffect(() => {
    if (!sending) return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [sending]);

  async function pick(list: FileList | null, fromFolder: boolean) {
    const files = [...(list ?? [])];
    if (!files.length) return;
    setPhase('reading');
    setError('');
    setResume(null);
    setProgress(null);
    const next = await readFiles(files, fromFolder, provider);
    if (!alive.current) return;
    setPicked(next);
    setPhase('ready');
  }

  async function send() {
    if (!picked?.combined || !total || !consentReady(consent) || !accountKey) return;
    setPhase('sending');
    setError('');
    let importId = resume?.importId;
    try {
      if (!importId) {
        const created = await api.request(w, { route: 'platform_export', provider, accountKey, accountLabel, consent: { ownership: consent.ownership, voiceScope: consent.voiceScope, confirmed: true } });
        importId = created.import.id;
      }
    } catch (failure) {
      if (!alive.current) return;
      setError(failure instanceof Error ? failure.message : '');
      setPhase('ready');
      void invalidate();
      return;
    }
    const run = importId;
    const from = resume?.next ?? 0;
    setResume({ importId: run, next: from });
    const result = await sendBatches(picked.plan.batches, {
      send: (body) => api.sendItems(w, run, body),
      // A post too long to store is reported with the ones the parser could not read, so the receipt accounts for it.
      skipped: { unsupported: picked.combined.skipped.unsupported + picked.plan.tooLong, empty: picked.combined.skipped.empty },
      from,
      onProgress: (state) => {
        if (alive.current) setProgress(state);
      },
      cancelled: () => !alive.current
    });
    void invalidate();
    if (!alive.current) return;
    if (result.ok) {
      setPhase('done');
      return;
    }
    setResume({ importId: run, next: result.next });
    setError(result.error instanceof Error ? result.error.message : '');
    setPhase('stopped');
  }

  async function abandon() {
    if (!resume) return;
    try {
      await api.cancel(w, resume.importId);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '');
    }
    void invalidate();
    onClose();
  }

  const reportLine = (report: FileReport) => {
    switch (report.state) {
      case 'read':
        return `${t('Posts with text', '有文字的貼文', '有文字的帖子')}: ${number(report.posts ?? 0)}`;
      case 'html':
        return t('An HTML export. Ask the platform for the export again in JSON format.', '這是 HTML 格式的匯出檔，請向平台重新申請 JSON 格式。', '这是 HTML 格式的导出文件，请向平台重新申请 JSON 格式。');
      case 'archive':
        return t('A compressed archive. Unzip it first, then choose the files inside it.', '這是壓縮檔，請先解壓縮，再選取其中的檔案。', '这是压缩包，请先解压，再选择其中的文件。');
      case 'too_large':
        return t('Larger than 100 MB, so it was not opened.', '檔案超過 100 MB，因此沒有開啟。', '文件超过 100 MB，因此没有打开。');
      case 'other_platform':
        return t(
          `This file holds ${platformName(report.provider ?? '')} posts. Upload it from that platform’s row.`,
          `此檔案載有 ${platformName(report.provider ?? '')} 貼文，請在該平台的一列上載。`,
          `此文件载有 ${platformName(report.provider ?? '')} 帖子，请在该平台的一行上传。`
        );
      case 'unreadable':
        return t('Could not be opened.', '無法開啟。', '无法打开。');
      default:
        return t('Not a post file Rafii recognises, so nothing from it is sent.', '並非 Rafii 能辨認的貼文檔案，因此不會傳送其中任何內容。', '并非 Rafii 能识别的帖子文件，因此不会发送其中任何内容。');
    }
  };

  const facts: [label: string, value: number][] = picked
    ? [
        [t('Without text', '沒有文字', '没有文字'), picked.combined?.skipped.empty ?? 0],
        [t('Could not be read', '無法讀取', '无法读取'), picked.combined?.skipped.unsupported ?? 0],
        [t('Longer than 20,000 characters (left out, not cut)', '超過 20,000 字元（略過，不會截斷）', '超过 20,000 字符（略过，不会截断）'), picked.plan.tooLong],
        [t('Not public (left on your device)', '並非公開（留在你的裝置）', '并非公开（留在你的设备）'), picked.combined?.local.notPublic ?? 0],
        [t('Boosts with no writing of yours (left on your device)', '沒有你文字的轉發（留在你的裝置）', '没有你文字的转发（留在你的设备）'), picked.combined?.local.reposts ?? 0],
        [t('Other files in the folder, not opened', '資料夾內其他檔案（沒有開啟）', '文件夹内其他文件（没有打开）'), picked.unopened]
      ]
    : [];

  return (
    <div className='flex min-w-0 flex-col gap-4' data-testid={`voice-import-upload-${provider}`}>
      <p className='text-sm leading-relaxed'>
        {t(
          'Your export is read here, in your browser, and is never uploaded. Rafii sends only the posts it finds: their text, date and link, at most 200 posts and under 512 kB per request. Messages, photos and everything else in the export stay on your device.',
          '匯出檔只會在你的瀏覽器內讀取，不會上載。Rafii 只會傳送找到的貼文：文字、日期及連結，每次請求最多 200 篇，並少於 512 kB。訊息、相片及匯出檔內的其他內容都會留在你的裝置。',
          '导出文件只会在你的浏览器内读取，不会上传。Rafii 只会发送找到的帖子：文字、日期及链接，每次请求最多 200 篇，并少于 512 kB。消息、照片及导出文件内的其他内容都会留在你的设备。'
        )}
      </p>

      {guide && (
        <div className='text-muted-foreground flex flex-col gap-2 text-xs leading-relaxed'>
          <p>{t(...guide.request)}</p>
          <p>{t('Unzip the export, then choose:', '解壓縮匯出檔後，請選取：', '解压导出文件后，请选择：')}</p>
          <ul className='flex flex-col gap-1'>
            {guide.files.map((file) => (
              <li key={file.path} className='break-all'>
                <code className='text-foreground rafii-field rounded-md px-1.5 py-0.5 font-mono'>{file.path}</code>
                {file.when && <span> · {t(...file.when)}</span>}
              </li>
            ))}
          </ul>
          <p>
            {t(
              'Or choose the whole unzipped folder: Rafii opens only the post files named above and no other file in it.',
              '你亦可選取整個已解壓縮的資料夾：Rafii 只會開啟上述貼文檔案，不會開啟其中任何其他檔案。',
              '你也可以选择整个已解压的文件夹：Rafii 只会打开上述帖子文件，不会打开其中任何其他文件。'
            )}
          </p>
        </div>
      )}

      <input
        ref={fileInput}
        id={`${id}-files`}
        type='file'
        multiple
        accept='.json,.js,.csv,application/json,text/csv,text/javascript'
        className='sr-only'
        tabIndex={-1}
        aria-label={`${name}: ${t('choose export files', '選取匯出檔案', '选择导出文件')}`}
        onChange={(event) => {
          void pick(event.currentTarget.files, false);
          event.currentTarget.value = '';
        }}
      />
      <input
        ref={folderInput}
        id={`${id}-folder`}
        type='file'
        multiple
        className='sr-only'
        tabIndex={-1}
        aria-label={`${name}: ${t('choose the export folder', '選取匯出資料夾', '选择导出文件夹')}`}
        {...({ webkitdirectory: '' } as Record<string, string>)}
        onChange={(event) => {
          void pick(event.currentTarget.files, true);
          event.currentTarget.value = '';
        }}
      />
      {phase !== 'done' && (
        <div className='flex flex-wrap gap-2'>
          <Button variant='glass' className='min-h-11' disabled={sending || phase === 'reading' || phase === 'stopped'} onClick={() => fileInput.current?.click()}>
            <Icons.upload aria-hidden /> {t('Choose files', '選取檔案', '选择文件')}
          </Button>
          <Button variant='glass' className='min-h-11' disabled={sending || phase === 'reading' || phase === 'stopped'} onClick={() => folderInput.current?.click()}>
            <Icons.folderOpen aria-hidden /> {t('Choose folder', '選取資料夾', '选择文件夹')}
          </Button>
          {(phase === 'idle' || phase === 'ready') && (
            <Button variant='quiet' className='min-h-11' onClick={onClose}>
              {t('Close', '關閉', '关闭')}
            </Button>
          )}
        </div>
      )}

      <div role='status' aria-live='polite' className='flex min-w-0 flex-col gap-2 text-sm'>
        {phase === 'reading' && (
          <p className='flex items-center gap-2'>
            <Icons.spinner className='size-4 motion-safe:animate-spin' aria-hidden /> {t('Reading the files in your browser…', '正在瀏覽器內讀取檔案…', '正在浏览器内读取文件…')}
          </p>
        )}
        {picked && phase !== 'reading' && (
          <>
            <p className='font-medium'>
              {total
                ? `${t('Posts ready to send', '可以傳送的貼文', '可以发送的帖子')}: ${number(total)}`
                : t('No posts with text were found, so there is nothing to import.', '找不到有文字的貼文，因此沒有可匯入的內容。', '找不到有文字的帖子，因此没有可导入的内容。')}
            </p>
            {range && (
              <p className='text-muted-foreground'>
                {locale.formatDate(range.oldest)} – {locale.formatDate(range.newest)}
              </p>
            )}
            <dl className='text-muted-foreground flex flex-col gap-1'>
              {facts
                .filter(([, value]) => value > 0)
                .map(([fact, value]) => (
                  <div key={fact} className='flex flex-wrap gap-x-2'>
                    <dt>{fact}:</dt>
                    <dd className='text-foreground tabular-nums'>{number(value)}</dd>
                  </div>
                ))}
            </dl>
            <ul className='text-muted-foreground flex flex-col gap-1 text-xs'>
              {picked.reports.map((report) => (
                <li key={report.name} className='break-all'>
                  <span className='text-foreground font-medium'>{report.name}</span> · {reportLine(report)}
                  {report.notes?.map((note) => (
                    <span key={note}> {noteText(note, locale.language)}</span>
                  ))}
                </li>
              ))}
            </ul>
          </>
        )}
        {progress && phase !== 'ready' && phase !== 'reading' && (
          <Progress value={(progress.sent / Math.max(1, progress.total)) * 100} aria-label={t('Posts sent', '已傳送的貼文', '已发送的帖子')}>
            <span className='text-sm tabular-nums'>
              {t('Posts sent', '已傳送的貼文', '已发送的帖子')}: {number(progress.sent)} / {number(progress.total)}
            </span>
          </Progress>
        )}
        {sending && !progress && (
          <p className='flex items-center gap-2'>
            <Icons.spinner className='size-4 motion-safe:animate-spin' aria-hidden /> {t('Sending the first posts…', '正在傳送第一批貼文…', '正在发送第一批帖子…')}
          </p>
        )}
        {phase === 'done' && <p className='font-medium'>{t('All posts were sent. The receipt now counts them.', '所有貼文已傳送，收據已計算在內。', '所有帖子已发送，回执已计算在内。')}</p>}
      </div>

      {error && <StateMessage kind='error' layout='inline' title={error} />}

      {phase === 'ready' && total > 0 && (
        <>
          <div className='flex min-w-0 flex-col gap-3'>
            {known.length > 0 && (
              <SelectField label={t('Which account are these posts from?', '這些貼文來自哪個帳戶？', '这些帖子来自哪个账户？')} value={account} onChange={(event) => setAccount(event.target.value)}>
                <option value={NEW_ACCOUNT}>{t('Another account', '另一個帳戶', '另一个账户')}</option>
                {known.map((receipt) => (
                  <option key={receipt.accountKey} value={receipt.accountKey}>
                    {receipt.label}
                  </option>
                ))}
              </SelectField>
            )}
            {!existing && (
              <label htmlFor={`${id}-account`} className='flex min-w-0 flex-col gap-2 text-sm'>
                <span className='text-foreground font-medium'>{t('Account name', '帳戶名稱', '账户名称')}</span>
                <Input id={`${id}-account`} value={label} onChange={(event) => setLabel(event.target.value)} maxLength={120} autoComplete='off' placeholder={t('The name or handle on this platform', '此平台上的名稱或帳號', '此平台上的名称或账号')} className={FIELD_CLASS} />
              </label>
            )}
          </div>
          <ConsentStep value={consent} onChange={setConsent} disabled={!canManage} t={t} />
          {!canManage && <p className='text-muted-foreground text-xs'>{t('Only a member who can manage connections can start an import.', '只有可管理連接的成員才可開始匯入。', '只有可管理连接的成员才可开始导入。')}</p>}
          <div>
            <Button variant='action' className='min-h-11' data-testid={`voice-import-send-${provider}`} disabled={!canManage || !consentReady(consent) || !accountKey} onClick={() => void send()}>
              {t('Import these posts', '匯入這些貼文', '导入这些帖子')}
            </Button>
          </div>
        </>
      )}

      {phase === 'stopped' && (
        <div className='flex flex-wrap gap-2'>
          <Button variant='action' className='min-h-11' onClick={() => void send()}>
            {t('Resume sending', '繼續傳送', '继续发送')}
          </Button>
          <Button variant='quiet' className='min-h-11' onClick={() => void abandon()}>
            {t('Cancel this import', '取消此次匯入', '取消此次导入')}
          </Button>
        </div>
      )}
      {phase === 'done' && (
        <div>
          <Button variant='glass' className='min-h-11' onClick={onClose}>
            {t('Done', '完成', '完成')}
          </Button>
        </div>
      )}
    </div>
  );
}
