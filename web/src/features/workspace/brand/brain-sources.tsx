'use client';
import { useEffect, useId, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useGenUiLocale } from '@/features/agent/generative-ui/core/locale';
import { AlertDialog, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from '@/components/ui/alert-dialog';
import { departureHref } from './brain-navigation';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { StateMessage, Surface } from '@/components/rafii';
import { useModels } from '@/lib/api/hooks';
import type { ModelOption, SnapshotSource } from '@/lib/api/types';
import { OwnedPostsPicker } from './owned-posts-picker';
import { SelectField, FIELD_CLASS, TEXTAREA_CLASS } from '../rafii-parts';
import type { BrainAction, BrainTranslate, BrainView } from './brain-types';

export function analysisInputBytes(sources: SnapshotSource[], instructions: string): number {
  const scalar = (value: unknown) => JSON.stringify(value ?? null);
  const rows = sources.map(s => `{${[['id', s.id], ['text', s.text], ['platform', s.platform], ['language', s.language], ['label', s.label]].map(([k, v]) => `${scalar(k)}: ${scalar(v)}`).join(', ')}}`);
  return new TextEncoder().encode(`{"request": ${scalar(instructions)}, "samples": [${rows.join(', ')}]}`).length;
}

type Props = { sources: SnapshotSource[]; revision: number; brain: BrainView; owner: boolean; busy: boolean; run: BrainAction; t: BrainTranslate };

export function BrainSourcePicker({ sources, revision, brain, owner, busy, run, t }: Props) {
  const router = useRouter();
  const [departure, setDeparture] = useState<string | null>(null);
  const [method, setMethod] = useState<'paste' | 'posts' | 'saved'>('paste');
  const [text, setText] = useState('');
  const [title, setTitle] = useState('');
  const [platform, setPlatform] = useState('');
  const [language, setLanguage] = useState('');
  const [authorship, setAuthorship] = useState(false);
  const [retain, setRetain] = useState(false);
  const id = useId();
  useEffect(() => {
    if (!text.trim()) return;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); };
    const leave = (event: MouseEvent) => {
      if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      const anchor = event.target instanceof Element ? event.target.closest('a[href]') : null;
      if (!(anchor instanceof HTMLAnchorElement)) return;
      const next = departureHref(anchor.href, window.location.href, anchor.target, anchor.hasAttribute('download'));
      if (!next) return;
      event.preventDefault(); event.stopPropagation(); setDeparture(next);
    };
    window.addEventListener('beforeunload', warn);
    document.addEventListener('click', leave, true);
    return () => { window.removeEventListener('beforeunload', warn); document.removeEventListener('click', leave, true); };
  }, [text]);
  async function save() {
    if (await run('brand_brain_import', { format: 'pasted', text, title, platform, language, authorshipConfirmed: authorship, retentionConfirmed: retain })) {
      setText(''); setTitle(''); setAuthorship(false); setRetain(false); setMethod('saved');
    }
  }
  return <div className='space-y-5' data-testid='bb-step-sources'>
    <AlertDialog open={departure !== null} onOpenChange={open => { if (!open) setDeparture(null); }}><AlertDialogContent><AlertDialogHeader><AlertDialogTitle>{t('Leave unsaved writing?', '離開未儲存的文字？', '离开未保存的文字？')}</AlertDialogTitle><AlertDialogDescription>{t('This pasted writing has not been retained. Leaving discards it. Your saved sources and proposals stay on the server.', '貼上的文字尚未儲存，離開會捨棄。已儲存的來源及提案會保留在伺服器。', '粘贴的文字尚未保存，离开会丢弃。已保存的来源及提案将保留在服务器。')}</AlertDialogDescription></AlertDialogHeader><AlertDialogFooter><AlertDialogCancel className='min-h-11'>{t('Keep editing', '繼續編輯', '继续编辑')}</AlertDialogCancel><Button data-testid='bb-discard-unsaved' variant='destructive' className='min-h-11' onClick={() => { if (!departure) return; const href = departure; setText(''); setAuthorship(false); setRetain(false); setDeparture(null); router.push(href); }}>{t('Discard and leave', '捨棄並離開', '丢弃并离开')}</Button></AlertDialogFooter></AlertDialogContent></AlertDialog>
    <div className='flex flex-wrap gap-2' aria-label={t('Choose writing source', '選擇寫作來源', '选择写作来源')}>
      <Button className='min-h-11' variant={method === 'paste' ? 'glass' : 'quiet'} onClick={() => setMethod('paste')}>{t('Paste my writing', '貼上我的文字', '粘贴我的文字')}</Button>
      <Button className='min-h-11' variant={method === 'posts' ? 'glass' : 'quiet'} onClick={() => setMethod('posts')}>{t('Connect my posts', '連接我的貼文', '连接我的帖子')}</Button>
      {sources.length > 0 && <Button className='min-h-11' variant={method === 'saved' ? 'glass' : 'quiet'} onClick={() => setMethod('saved')}>{t('Use saved writing', '使用已儲存文字', '使用已保存文字')}</Button>}
    </div>
    {/* Keep the unsaved paste mounted when switching methods. No raw text enters browser storage. */}
    <div hidden={method !== 'paste'} className='space-y-4'>
      <label className='block space-y-2' htmlFor={`${id}-title`}><span>{t('Sample title', '範例標題', '样本标题')}</span><Input id={`${id}-title`} value={title} onChange={e => setTitle(e.target.value)} maxLength={120} className={FIELD_CLASS} /></label>
      <div className='grid gap-3 sm:grid-cols-2'>
        <label className='block space-y-2' htmlFor={`${id}-platform`}><span>{t('Platform (optional)', '平台（選填）', '平台（选填）')}</span><Input id={`${id}-platform`} value={platform} onChange={e => setPlatform(e.target.value)} maxLength={80} className={FIELD_CLASS} /></label>
        <label className='block space-y-2' htmlFor={`${id}-language`}><span>{t('Language (optional)', '語言（選填）', '语言（选填）')}</span><Input id={`${id}-language`} value={language} onChange={e => setLanguage(e.target.value)} maxLength={80} className={FIELD_CLASS} /></label>
      </div>
      <label className='block space-y-2' htmlFor={`${id}-writing`}><span>{t('Your writing', '你的文字', '你的文字')}</span><Textarea id={`${id}-writing`} data-testid='bb-sample-text' rows={6} dir='auto' value={text} onChange={e => { setText(e.target.value); setAuthorship(false); setRetain(false); }} className={TEXTAREA_CLASS} /></label>
      <p className='text-muted-foreground text-xs'>{Array.from(text).length} / {brain.limits.maxTextChars} {t('characters. Never silently truncated.', '字元。不會自動截斷。', '字符。不会自动截断。')}</p>
      <label className='flex min-h-11 items-center gap-3'><Checkbox checked={authorship} onCheckedChange={v => setAuthorship(v === true)} />{t('I wrote this or have permission to use it.', '這是我寫的文字，或我已獲准使用。', '这是我写的文字，或我已获准使用。')}</label>
      <label className='flex min-h-11 items-center gap-3'><Checkbox checked={retain} onCheckedChange={v => setRetain(v === true)} />{t('Retain this sample privately. Analysis and writer use need separate permission.', '私人儲存此範例。分析及寫作使用需要另行授權。', '私密保存此样本。分析及写作使用需要另行授权。')}</label>
      <Button data-testid='bb-save-sample' variant='action' className='min-h-11' disabled={busy || !authorship || !retain || !text.trim() || Array.from(text).length > brain.limits.maxTextChars} onClick={() => void save()}>{t('Save writing sample', '儲存寫作範例', '保存写作样本')}</Button>
    </div>
    {method === 'posts' && <OwnedPostsPicker revision={revision} isOwner={owner} />}
    {sources.length > 0 && <BrainSourceLedger {...{ sources, revision, brain, owner, busy, run, t }} selectionOnly />}
  </div>;
}

export function BrainSourceLedger({ sources, brain, owner, busy, run, t, selectionOnly = false }: Props & { selectionOnly?: boolean }) {
  const locale = useGenUiLocale();
  const selectionId = useId();
  const eligible = sources.filter(s => s.active && !['guest', 'ai_generated'].includes(s.label ?? ''));
  const selected = sources.filter(s => s.active && s.selected);
  const models = useModels();
  const writers = models.data?.models.filter(m => m.qualified && m.voiceRoute) ?? [];
  async function selectAll() {
    for (const source of eligible.filter(s => !s.selected).slice(0, Math.max(0, brain.limits.maxSamples - selected.length))) {
      if (!await run('voice_sample_select', { sourceId: source.id, selected: true })) break;
    }
  }
  return <section className='space-y-3' aria-label={t('Sources and permissions', '來源與權限', '来源与权限')}>
    <div className='flex flex-wrap items-center justify-between gap-3'><p className='text-muted-foreground text-sm'>{selected.length} / {brain.limits.maxSamples} {t('selected', '已選取', '已选择')}</p><Button variant='quiet' className='min-h-11' disabled={busy || selected.length >= brain.limits.maxSamples || !eligible.some(s => !s.selected)} onClick={() => void selectAll()}>{t('Select all eligible shown', '選取所有可用範例', '选择所有可用样本')} ({Math.min(eligible.filter(s => !s.selected).length, Math.max(0, brain.limits.maxSamples - selected.length))})</Button></div>
    {!sources.length && <StateMessage kind='empty' title={t('No writing samples yet', '尚未加入寫作範例', '尚未添加写作样本')} />}
    {sources.map(source => <Surface key={source.id} material='quiet' padding='sm' data-testid={`${selectionOnly ? 'bb-source' : 'bb-ledger-source'}-${source.id}`}>
      <div className='flex min-h-11 items-center justify-between gap-3'><div className='min-w-0'><h3 className='font-medium break-words'>{source.title || t('Writing sample', '寫作範例', '写作样本')}</h3><p className='text-muted-foreground text-xs break-words'>{[source.platform, source.language, source.account, source.publishedAt ? locale.formatDateTime(source.publishedAt) : null].filter(Boolean).join(' · ') || t('User-provided writing', '使用者提供的文字', '用户提供的文字')}</p></div><label htmlFor={`${selectionId}-${source.id}`} className='flex size-11 shrink-0 cursor-pointer items-center justify-center'><span className='sr-only'>{`${t('Select', '選取', '选择')} ${source.title || source.id}`}</span><Checkbox id={`${selectionId}-${source.id}`} aria-label={`${t('Select', '選取', '选择')} ${source.title || source.id}`} checked={source.selected === true} disabled={busy || !eligible.includes(source) || (!source.selected && selected.length >= brain.limits.maxSamples)} onCheckedChange={v => void run('voice_sample_select', { sourceId: source.id, selected: v === true })} /></label></div>
      <p className='mt-2 text-xs text-muted-foreground'>{!source.active ? t('Source revoked · No future use', '來源已撤銷 · 不再使用', '来源已撤销 · 不再使用') : source.label === 'guest' || source.label === 'ai_generated' ? t('Excluded: not eligible authored evidence', '已排除：並非可用的本人作品', '已排除：并非可用的本人作品') : source.selected ? t('Selected · permission checked separately', '已選取 · 權限另行檢查', '已选择 · 权限单独检查') : t('Stored only · not selected', '僅儲存 · 尚未選取', '仅保存 · 尚未选择')}</p>
      <details className='mt-2'><summary className='rafii-focus min-h-11 cursor-pointer py-3 text-sm'>{t('Source details and exact permissions', '來源詳情與確切權限', '来源详情与具体权限')}</summary>
        {source.active && <p dir='auto' className='max-h-40 overflow-auto whitespace-pre-wrap break-words text-sm'>{source.text}</p>}
        <dl className='my-3 grid gap-2 text-xs'><div><dt className='text-muted-foreground'>{t('Origin', '來源', '来源')}</dt><dd>{source.voiceOrigin === 'official_api' ? t('Official account import', '官方帳戶匯入', '官方账户导入') : t('User-provided text', '使用者提供', '用户提供')}</dd></div><div><dt className='text-muted-foreground'>{t('Authorship and retention', '作者身分與儲存', '作者身份与保存')}</dt><dd>{source.authorshipConfirmed === true ? t('Authorship or permission confirmed', '已確認作者身分或使用權', '已确认作者身份或使用权') : t('Authorship confirmation unavailable', '未能取得作者確認紀錄', '无法获取作者确认记录')} · {source.retentionConfirmed === true ? t('Retention confirmed', '已同意儲存', '已同意保存') : t('Retention confirmation unavailable', '未能取得儲存確認紀錄', '无法获取保存确认记录')}</dd></div><div><dt className='text-muted-foreground'>{t('Last recorded analysis', '最後記錄的分析', '最后记录的分析')}</dt><dd className='break-words'>{source.lastAnalysis ? <>{locale.formatDateTime(source.lastAnalysis.at)} · {source.lastAnalysis.model || t('Local rules · no AI model', '本地規則 · 不使用 AI 模型', '本地规则 · 不使用 AI 模型')}<span className='mt-1 block break-all'>{source.lastAnalysis.provider ?? ''} · {source.lastAnalysis.route}</span><span className='mt-1 block'>{source.lastAnalysis.contentHash === source.contentHash ? t('Analysed this content revision', '分析的是目前內容版本', '分析的是当前内容版本') : t('An earlier content revision was analysed', '分析的是較早內容版本', '分析的是较早内容版本')}</span></> : t('No analysis metadata recorded', '未有分析資料紀錄', '暂无分析信息记录')}</dd></div><div><dt className='text-muted-foreground'>{t('Analysis permissions', '分析權限', '分析权限')}</dt><dd className='break-all'>{source.useGrants?.filter(g => g.purpose === 'analysis').map(g => g.route).join(', ') || t('Not allowed', '未獲授權', '未获授权')}</dd></div><div><dt className='text-muted-foreground'>{t('Writer permissions', '寫作權限', '写作权限')}</dt><dd className='break-all'>{source.useGrants?.filter(g => g.purpose === 'generation').map(g => g.route).join(', ') || t('Not allowed', '未獲授權', '未获授权')}</dd></div><div><dt className='text-muted-foreground'>{t('Source revision', '來源版本', '来源版本')}</dt><dd>{source.revision ?? t('Unavailable', '未有資料', '暂无数据')}</dd></div></dl>
        {!selectionOnly && owner && source.active && <SourcePermissions {...{ source, writers, busy, run, t }} />}
      </details>
    </Surface>)}
  </section>;
}

function SourcePermissions({ source, writers, busy, run, t }: { source: SnapshotSource; writers: ModelOption[]; busy: boolean; run: BrainAction; t: BrainTranslate }) {
  const [writer, setWriter] = useState('');
  const [revoke, setRevoke] = useState(false);
  return <div className='space-y-3 border-t pt-3'>
    {(source.useGrants ?? []).map(g => <div key={`${g.purpose}:${g.route}`} className='flex flex-wrap items-center justify-between gap-2'><span className='min-w-0 break-all text-xs'>{g.purpose === 'analysis' ? t('Analysis', '分析', '分析') : t('Writer', '寫作模型', '写作模型')} · {g.route}</span><Button variant='quiet' className='min-h-11' disabled={busy} onClick={() => void run('voice_sample_grant', { sourceId: source.id, grants: (source.useGrants ?? []).filter(item => !(item.purpose === g.purpose && item.route === g.route)), confirmed: true })}>{t('Remove this permission', '移除此權限', '移除此权限')}</Button></div>)}
    <SelectField label={t('Allow style for a specific writer', '允許特定寫作模型使用風格', '允许特定写作模型使用风格')} value={writer} onChange={e => setWriter(e.target.value)}><option value=''>{t('Choose a writer', '選擇寫作模型', '选择写作模型')}</option>{writers.map(m => <option key={m.id} value={m.voiceRoute}>{m.label} · {m.egress}</option>)}</SelectField>
    <p className='text-xs text-muted-foreground'>{t('This is separate from analysis. Only this route is granted. Existing cloud memory controls still apply.', '此權限與分析分開，只授權所選路徑，並繼續受雲端記憶權限限制。', '此权限与分析分开，仅授权所选路径，并继续受云端记忆权限限制。')}</p>
    <Button data-testid={`bb-writer-grant-${source.id}`} className='min-h-11' variant='glass' disabled={busy || !writer} onClick={() => void run('voice_sample_grant', { sourceId: source.id, grants: [...(source.useGrants ?? []).filter(g => !(g.purpose === 'generation' && g.route === writer)), { purpose: 'generation', route: writer }], confirmed: true })}>{t('Allow this writer', '允許此寫作模型', '允许此写作模型')}</Button>
    <div className='flex flex-wrap gap-2'><Button variant='quiet' className='min-h-11' disabled={busy} onClick={() => void run('voice_sample_exclude', { sourceId: source.id })}>{t('Exclude from selection', '從選取中排除', '从选择中排除')}</Button><Button data-testid={`bb-source-revoke-${source.id}`} variant={revoke ? 'destructive' : 'quiet'} className='min-h-11' disabled={busy} onClick={() => { if (!revoke) return setRevoke(true); void run('voice_sample_revoke', { sourceId: source.id, confirmed: true }).then(ok => { if (ok) setRevoke(false); }); }}>{revoke ? t('Confirm revoke and remove text', '確認撤銷並移除文字', '确认撤销并移除文字') : t('Revoke source', '撤銷來源', '撤销来源')}</Button>{revoke && <Button variant='quiet' className='min-h-11' onClick={() => setRevoke(false)}>{t('Cancel', '取消', '取消')}</Button>}</div>
    {revoke && <p role='alert' className='text-xs'>{t('Future analysis and writer use stop. Existing published posts and historic provider logs cannot be erased here.', '停止未來分析及寫作使用。此處無法刪除已發佈貼文或供應商歷史紀錄。', '停止未来分析及写作使用。此处无法删除已发布帖子或提供商历史记录。')}</p>}
  </div>;
}

export function BrainAnalysis({ sources, brain, owner, busy, run, t, onReady }: Props & { onReady: () => void }) {
  const models = useModels();
  const locale = useGenUiLocale();
  const [modelId, setModelId] = useState('');
  const [instructions, setInstructions] = useState('');
  const [consent, setConsent] = useState(false);
  const [paidConsentFor, setPaidConsentFor] = useState('');
  const selected = sources.filter(s => s.active && s.selected);
  const aiModels = models.data?.models.filter(m => m.qualified && m.voiceAnalysisAvailable && m.voiceRoute) ?? [];
  const model = aiModels.find(m => m.id === modelId);
  const route = model?.voiceRoute ?? 'local-rules';
  const bytes = analysisInputBytes(selected, instructions);
  const withinLimits = selected.length > 0 && selected.length <= brain.limits.maxSamples && bytes <= brain.limits.maxInputBytes;
  const allAllowed = selected.every(s => s.useGrants?.some(g => g.purpose === 'analysis' && g.route === route));
  const quote = brain.analysisQuote;
  const confirmationKey = JSON.stringify([quote?.id, quote?.creditLimit, modelId, route, instructions, selected.map(s => [s.id, s.revision, s.useGrants])]);
  const paidConsent = paidConsentFor === confirmationKey;
  const setPaidConsent = (value: boolean) => setPaidConsentFor(value ? confirmationKey : '');
  const quoteValid = quote?.status === 'quoted' && quote.route === route && quote.model === modelId && Math.min(quote.expiresAt, quote.creditLimit?.expiresAt ?? quote.expiresAt) * 1000 > Date.now();
  async function grant() {
    for (const source of selected) {
      if (source.useGrants?.some(g => g.purpose === 'analysis' && g.route === route)) continue;
      if (!await run('voice_sample_grant', { sourceId: source.id, grants: [...(source.useGrants ?? []), { purpose: 'analysis', route }], confirmed: true })) return;
    }
    setConsent(false);
  }
  async function analyse() {
    const ok = await run('brand_brain_analyze', { sourceIds: selected.map(s => s.id), route, ...(model ? { model: model.id, instructions, confirmed: paidConsent, quoteId: quote?.id } : {}) });
    setPaidConsent(false); if (ok) onReady();
  }
  return <section data-testid='bb-step-analysis' className='space-y-4'>
    <h2 className='text-lg font-semibold'>{t('Choose how Rafii analyses your writing', '選擇 Rafii 如何分析你的文字', '选择 Rafii 如何分析你的文字')}</h2>
    <SelectField label={t('Processing choice', '處理方式', '处理方式')} value={modelId} onChange={e => { setModelId(e.target.value); setConsent(false); setPaidConsent(false); }}><option value=''>{t('Local writing patterns · no AI model', '本地寫作模式 · 不使用 AI 模型', '本地写作模式 · 不使用 AI 模型')}</option>{aiModels.map(m => <option key={m.id} value={m.id}>{m.label} · {m.provider}</option>)}</SelectField>
    <p className='text-sm text-muted-foreground'>{model ? t('The selected texts are sent to this named model for style analysis. Nothing becomes active.', '所選文字會傳送至此模型作風格分析，不會自動啟用。', '所选文字将发送至此模型进行风格分析，不会自动启用。') : t('Rules run on this workspace server, without an AI model. They measure writing patterns and may miss nuance.', '規則在工作區伺服器執行，不使用 AI 模型，可量度寫作模式但未必理解細節。', '规则在工作区服务器执行，不使用 AI 模型，可测量写作模式但未必理解细节。')}</p>
    <p className='text-sm'>{selected.length} / {brain.limits.maxSamples} {t('samples', '範例', '样本')} · {bytes.toLocaleString()} / {brain.limits.maxInputBytes.toLocaleString()} bytes</p>
    {!withinLimits && <p role='alert'>{t('Choose 1–50 eligible samples within the input limit. Remove large samples before continuing.', '請在輸入上限內選取 1–50 個可用範例，移除過大的範例再繼續。', '请在输入上限内选择 1–50 个可用样本，移除过大的样本再继续。')}</p>}
    <details><summary className='rafii-focus min-h-11 cursor-pointer py-3'>{t('Exactly what Rafii will read', 'Rafii 將讀取的確切內容', 'Rafii 将读取的具体内容')}</summary>{selected.map(s => <blockquote key={s.id} dir='auto' className='my-3 max-h-32 overflow-auto whitespace-pre-wrap break-words border-s-2 ps-3 text-sm'><strong>{s.title || s.id}</strong><br />{s.text}</blockquote>)}</details>
    {!allAllowed && <div className='space-y-3'><label className='flex min-h-11 items-center gap-3'><Checkbox checked={consent} onCheckedChange={v => setConsent(v === true)} disabled={!owner || busy || !withinLimits} />{t('Allow selected samples for this analysis', '允許所選範例用於此分析', '允许所选样本用于此分析')}</label><Button variant='glass' className='min-h-11' disabled={!owner || busy || !consent || !withinLimits} onClick={() => void grant()}>{t('Save analysis permission', '儲存分析權限', '保存分析权限')}</Button></div>}
    {!owner && <p className='text-xs text-muted-foreground'>{t('Only an owner can grant source access or authorize paid analysis.', '只有擁有者可授權來源存取或付費分析。', '仅所有者可授权来源访问或付费分析。')}</p>}
    {model && <div className='space-y-3'><label className='block space-y-2'><span>{t('Analysis guidance (optional)', '分析指引（選填）', '分析指引（选填）')}</span><Textarea value={instructions} onChange={e => { setInstructions(e.target.value); setPaidConsent(false); }} maxLength={1500} className={TEXTAREA_CLASS} /></label><Button variant='glass' className='min-h-11' disabled={!owner || busy || !allAllowed || !withinLimits} onClick={() => void run('brand_brain_quote', { sourceIds: selected.map(s => s.id), route, model: model.id, instructions })}>{t('Get cost estimate', '取得費用估算', '获取费用估算')}</Button><p className='text-xs'>{quoteValid ? `${t('Estimated cost', '估計費用', '预计费用')}: US$${((quote?.estimatedMicroUsd ?? 0) / 1000000).toFixed(6)}` : t('Cost unavailable — choose local analysis or request a verified quote.', '費用未確認，可選擇本地分析或索取有效報價。', '费用未确认，可选择本地分析或索取有效报价。')}</p>{quoteValid && quote && <div className='space-y-1 text-xs' data-testid='bb-analysis-quote-disclosure'>{quote.creditLimit && <p>{t('Maximum credits for this analysis', '此次分析最高點數', '此次分析最高点数')}: {locale.formatNumber(quote.creditLimit.maxMilliCredits / 1000, { maximumFractionDigits: 3 })}</p>}<p>{t('Quote expires', '報價到期時間', '报价到期时间')}: {locale.formatDateTime(Math.min(quote.expiresAt, quote.creditLimit?.expiresAt ?? quote.expiresAt))}</p><p>{model.label} · {model.provider} · {locale.formatNumber(selected.length)} {t('selected samples, including the analysis guidance shown above', '個所選範例，包括上方顯示的分析指引', '个所选样本，包括上方显示的分析指引')}</p></div>}<label className='flex min-h-11 items-center gap-3'><Checkbox checked={paidConsent} onCheckedChange={v => setPaidConsent(v === true)} disabled={!quoteValid || busy} />{t('Approve one analysis using this quote and these exact texts.', '按此報價及確切文字批准一次分析。', '按此报价及具体文字批准一次分析。')}</label></div>}
    <div className='sticky bottom-[calc(4.25rem+env(safe-area-inset-bottom))] z-10 -mx-2 bg-background/95 px-2 py-3 backdrop-blur-sm md:static md:bg-transparent md:backdrop-blur-none'><Button data-testid='bb-analyse-local' variant='action' className='min-h-11' disabled={busy || !withinLimits || !allAllowed || (!!model && (!owner || !quoteValid || !paidConsent))} onClick={() => void analyse()}>{busy ? t('Analysing selected samples…', '正在分析所選範例…', '正在分析所选样本…') : model ? t('Analyse with AI', '使用 AI 分析', '使用 AI 分析') : t('Analyse local writing patterns', '分析本地寫作模式', '分析本地写作模式')}</Button></div>
    <p role='status' aria-live='polite' className='text-xs text-muted-foreground'>{busy ? t('Creating a voice proposal. Your current voice stays active.', '正在建立風格提案，目前的風格保持啟用。', '正在创建风格提案，目前的风格保持启用。') : t('Storage, analysis, writer access and future re-analysis are separate. Periodic analysis is off.', '儲存、分析、寫作存取及未來重新分析權限互相獨立，定期分析已關閉。', '保存、分析、写作访问及未来重新分析权限互相独立，定期分析已关闭。')}</p>
  </section>;
}
