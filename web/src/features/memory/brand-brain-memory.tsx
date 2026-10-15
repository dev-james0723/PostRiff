'use client';

import { useState } from 'react';
import Link from 'next/link';
import { Surface } from '@/components/rafii';
import { useMemory, useSnapshot } from '@/lib/api/hooks';
import type { MemoryFile } from '@/lib/api/types';
import { AccessCard } from './access-card';
import { WhatDraftsRead } from './what-drafts-read';
import { memoryFileLabel } from './memory-files';
import { useGenUiLocale } from '@/features/agent/generative-ui/core/locale';

function useMemoryCopy() {
  const locale = useGenUiLocale();
  return (en: string, hant: string, hans: string) => locale.language === 'zh-Hant' ? hant : locale.language === 'zh-Hans' ? hans : en;
}

export interface MemorySnapshot {
  workspaceRevision: number;
  renderVersion: string;
  renderDigest: string;
  activeVoiceRevision: number | null;
  preferenceSetDigest: string;
  fileDigests: Record<string, string>;
}
export interface MemoryRunReceipt {
  activeVoiceRevision: number | null;
  effectiveVoiceMode: 'approved' | 'neutral' | 'override' | 'not_supplied';
  writerRoute: string;
  cloudMemoryAllowed: boolean;
  filesIncluded: string[];
  filesWithheld: { name: string; reason: string }[];
  fragments: { name: string; digest: string | null; truncated: boolean; bytesIncluded: number; bytesAvailable: number }[];
  withheldBoundaries: number;
  preferenceSetDigest: string;
  preferencesIncludedDigest: string;
  identityContextRevision: string;
  boundaryPolicyRevision: string;
  sourceGrantDigest: string;
  renderVersion: string;
  generatedAt: string;
  execution?: string;
}
interface Diagnostics {
  snapshot?: MemorySnapshot;
  routeViews?: Record<'local' | 'cloud', { files: MemoryFile[]; shared: boolean; restrictedViewer?: boolean }>;
}

/** Server-derived diagnostics; never an editable Markdown store or proof of a completed model call. */
export function BrandBrainMemoryDiagnostics() {
  const t = useMemoryCopy();
  const memory = useMemory();
  const snapshot = useSnapshot();
  const [file, setFile] = useState('VOICE.md');
  const [route, setRoute] = useState<'local' | 'cloud'>('local');
  const diagnostics = memory.data as (typeof memory.data & Diagnostics);
  const metadata = diagnostics?.snapshot;
  const verified = metadata && snapshot.data && metadata.workspaceRevision === snapshot.data.revision && !memory.isRefetchError && !snapshot.isRefetchError;
  const projection = diagnostics?.routeViews?.[route];
  return (
    <section aria-label={t('What Rafii knows and uses', 'Rafii 知道及使用的內容', 'Rafii 知道及使用的内容')} className='flex min-w-0 flex-col gap-4'>
      <div className='flex flex-col gap-2'>
        <h2 className='text-base font-semibold'>{t('What Rafii knows and uses', 'Rafii 知道及使用的內容', 'Rafii 知道及使用的内容')}</h2>
        <p className='text-muted-foreground text-sm' role='status'>
          {memory.isLoading || snapshot.isLoading ? t('Checking memory…', '正在核對記憶…', '正在核对记忆…') : verified ? `${t('Synced · workspace revision', '已同步 · 工作區版本', '已同步 · 工作区版本')} ${metadata.workspaceRevision}` : t('Not verified — refresh the current workspace and memory before relying on this view.', '尚未核實，請重新整理工作區與記憶。', '尚未核实，请刷新工作区与记忆。')}
        </p>
        <p className='text-muted-foreground text-sm'>{t('These five files are rendered from your approved settings. Edit the fields in Brand Brain. The raw files are read-only.', '這五個檔案由已批准的設定產生。請在 Brand Brain 編輯相關欄位，原始檔案僅供閱讀。', '这五个文件由已批准的设置生成。请在 Brand Brain 编辑相关字段，原始文件仅供阅读。')}</p>
      </div>
      <AccessCard memoryOnly />
      <label className='flex min-w-0 flex-col gap-2 text-sm font-medium'>
        {t('View derived file', '查看衍生檔案', '查看派生文件')}
        <select value={file} onChange={(event) => setFile(event.target.value)} className='rafii-focus bg-background min-h-11 w-full rounded-md border px-3'>
          {(memory.data?.files ?? []).map((item) => <option key={item.name} value={item.name}>{memoryFileLabel(item.name)} · {item.name}</option>)}
        </select>
      </label>
      <WhatDraftsRead selected={file} />
      <Surface material='quiet' className='flex min-w-0 flex-col gap-3'>
        <h3 className='text-sm font-medium'>{t('What the writer would receive', '寫作模型可接收的內容', '写作模型可接收的内容')}</h3>
        <label className='flex flex-col gap-2 text-sm'>
          {t('Route projection', '處理路徑', '处理路径')}
          <select value={route} onChange={(event) => setRoute(event.target.value as 'local' | 'cloud')} className='rafii-focus bg-background min-h-11 rounded-md border px-3'>
            <option value='local'>{t('Workspace writer · local-cli', '工作區寫作 · local-cli', '工作区写作 · local-cli')}</option>
            <option value='cloud'>{t('Cloud · no named sample grant assumed', '雲端 · 不假定樣本已有指定授權', '云端 · 不假定样本已有指定授权')}</option>
          </select>
        </label>
        <p className='text-muted-foreground text-xs'>{t('Eligible context before a call. The actual draft receipt records the selected route, neutral override, and any prompt omissions. Sending context does not prove the model followed it.', '這是呼叫前可用的內容。草稿收據會記錄實際路徑、中性覆寫及省略項目。送出內容不代表模型必定遵從。', '这是调用前可用的内容。草稿回执会记录实际路径、中性覆盖及省略项目。发送内容不代表模型必定遵从。')}</p>
        {!projection || memory.isRefetchError ? <p role='status'>{t('Projection unavailable.', '暫時無法核實。', '暂时无法核实。')}</p> : !projection.files.length ? <p>{t('No memory files eligible for this route.', '此路徑沒有可用的記憶檔案。', '此路径没有可用的记忆文件。')}</p> : projection.files.map((item) => (
          <details key={item.name} className='min-w-0 rounded-md border p-3'>
            <summary className='rafii-focus min-h-11 cursor-pointer py-3 text-sm'>{item.name}</summary>
            <pre className='mt-2 max-h-72 overflow-auto whitespace-pre-wrap break-words text-xs' dir='auto'>{item.body}</pre>
          </details>
        ))}
        {projection?.restrictedViewer && <p className='text-muted-foreground text-xs'>{t('Private boundary values are visible only to the workspace owner.', '只有工作區擁有者可查看私人界線內容。', '只有工作区所有者可查看私人边界内容。')}</p>}
        {metadata && <details className='min-w-0 text-xs'>
          <summary className='rafii-focus min-h-11 cursor-pointer py-3'>{t('Render and preference fingerprints', '檔案與偏好指紋', '文件与偏好指纹')}</summary>
          <dl className='space-y-2 break-all'>
            <dt>{t('Renderer', '產生器版本', '生成器版本')}</dt><dd>{metadata.renderVersion}</dd>
            <dt>{t('Render digest', '檔案摘要', '文件摘要')}</dt><dd>{metadata.renderDigest}</dd>
            <dt>{t('Preference set (separate from voice version)', '偏好集合（與語氣版本獨立）', '偏好集合（与语气版本独立）')}</dt><dd>{metadata.preferenceSetDigest}</dd>
          </dl>
        </details>}
      </Surface>
      <Link href='/app/workspace/memory' className='rafii-focus min-h-11 py-3 text-sm underline underline-offset-4'>{t('Open Memory files, preferences and export', '開啟記憶檔案、偏好與匯出', '打开记忆文件、偏好与导出')}</Link>
    </section>
  );
}

export function MemoryReceiptDetails({ receipt }: { receipt: MemoryRunReceipt }) {
  const t = useMemoryCopy();
  const mode = receipt.effectiveVoiceMode === 'approved' ? `${t('Approved voice', '已批准語氣', '已批准语气')} v${receipt.activeVoiceRevision}` : receipt.effectiveVoiceMode === 'neutral' ? t('Neutral override (approved voice was not used)', '中性覆寫（未使用已批准語氣）', '中性覆盖（未使用已批准语气）') : receipt.effectiveVoiceMode === 'override' ? t('Permitted sample style override', '已授權樣本風格覆寫', '已授权样本风格覆盖') : t('Voice not supplied', '未提供語氣', '未提供语气');
  return <section aria-label={t('Actual writer memory receipt', '實際寫作記憶收據', '实际写作记忆回执')} className='flex min-w-0 flex-col gap-1 break-words text-xs'>
    <p className='font-medium'>{t('Used to draft', '草稿使用', '草稿使用')}: {mode}</p>
    {receipt.execution === 'fixture' && <p>{t('Fixture execution — no real model call.', '測試執行，沒有呼叫真實模型。', '测试执行，没有调用真实模型。')}</p>}
    <p>{t('Actually sent', '實際送出', '实际发送')}: {receipt.filesIncluded.length ? receipt.filesIncluded.join(', ') : t('No memory files', '沒有記憶檔案', '没有记忆文件')}</p>
    {receipt.filesWithheld.length > 0 && <p>{t('Withheld', '已保留不送出', '已保留不发送')}: {receipt.filesWithheld.map((item) => `${item.name} (${item.reason === 'cloud_memory_denied' ? t('cloud memory denied', '未授權雲端記憶', '未授权云端记忆') : item.reason === 'neutral_override' ? t('neutral override', '中性覆寫', '中性覆盖') : t('prompt budget', '提示內容上限', '提示内容上限')})`).join(', ')}</p>}
    {receipt.withheldBoundaries > 0 && <p>{receipt.withheldBoundaries} {t('private or restricted boundaries withheld.', '項私人或受限界線未送出。', '项私人或受限边界未发送。')}</p>}
    {receipt.fragments.filter((item) => item.truncated).map((item) => <p key={item.name}>{item.name}: {t('partial context', '部分內容', '部分内容')} · {item.bytesIncluded}/{item.bytesAvailable} bytes</p>)}
    <p>{t('Route', '路徑', '路径')}: <span className='break-all'>{receipt.writerRoute}</span></p>
    <p>{t('Context was supplied to the writer. This does not verify the model followed it.', '內容已提供給寫作模型，但不代表已核實模型遵從。', '内容已提供给写作模型，但不代表已核实模型遵从。')}</p>
    <details className='min-w-0'>
      <summary className='rafii-focus min-h-11 cursor-pointer py-3'>{t('Memory receipt fingerprints', '記憶收據指紋', '记忆回执指纹')}</summary>
      <dl className='space-y-1 break-all'>
        <dt>{t('Preference set', '偏好集合', '偏好集合')}</dt><dd>{receipt.preferenceSetDigest}</dd>
        <dt>{t('Included preferences', '實際送出的偏好', '实际发送的偏好')}</dt><dd>{receipt.preferencesIncludedDigest}</dd>
        <dt>{t('Identity', '身分', '身份')}</dt><dd>{receipt.identityContextRevision}</dd>
        <dt>{t('Boundary policy', '界線政策', '边界政策')}</dt><dd>{receipt.boundaryPolicyRevision}</dd>
        <dt>{t('Source grants', '來源授權', '来源授权')}</dt><dd>{receipt.sourceGrantDigest}</dd>
        <dt>{t('Renderer', '產生器版本', '生成器版本')}</dt><dd>{receipt.renderVersion}</dd>
        <dt>{t('Generated', '產生時間', '生成时间')}</dt><dd>{receipt.generatedAt}</dd>
      </dl>
    </details>
  </section>;
}
