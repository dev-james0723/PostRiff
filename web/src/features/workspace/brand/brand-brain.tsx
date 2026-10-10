'use client';
import Link from 'next/link';
import { useEffect, useRef, useState } from 'react';
import { toast } from 'sonner';
import PageContainer from '@/components/layout/page-container';
import { StateMessage, Surface } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { Icons } from '@/components/icons';
import { useAct, useMemory, useSnapshot } from '@/lib/api/hooks';
import { ApiError } from '@/lib/api/client';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { downloadBlob } from '@/lib/download';
import { useGenUiLocale } from '@/features/agent/generative-ui/core/locale';
import { panelStore } from '@/features/site-agent/store';
import { LearningPanel } from '@/features/memory/learning-panel';
import { BrandBrainMemoryDiagnostics } from '@/features/memory/brand-brain-memory';
import { BrainAnalysis, BrainSourceLedger, BrainSourcePicker } from './brain-sources';
import { BrainImpactDialog, BrainPreview, BrainReview } from './brain-review';
import { BrainVersionCompare } from './brain-version-compare';
import { BrainBoundaryEditor, BrainIdentityEditor } from './brain-editors';
import { brainView, type BrainTranslate } from './brain-types';
import { activeProfile, canExportPackage, voiceStatus } from './voice-model';
import { BrandLoadError, BrandSkeleton, BrandStaleNotice } from './brand-states';
import { VoiceSetup } from '../voice-setup';
import { GenomePanel } from '@/features/growth/genome-panel';

type Area = 'overview' | 'teach' | 'identity' | 'preferences' | 'sources' | 'versions' | 'advanced';
type Step = 'sources' | 'analysis' | 'review' | 'preview';
const AREAS: Area[] = ['overview', 'teach', 'identity', 'preferences', 'sources', 'versions', 'advanced'];
const STEPS: Step[] = ['sources', 'analysis', 'review', 'preview'];

/** Brand Brain reads the same canonical snapshot as J04 and Memory. UI state contains only navigation and unsaved edits. */
export function BrandBrain() {
  const { workspaceId } = useWorkspaceApi();
  return <BrandBrainSession key={workspaceId} />;
}

function BrandBrainSession() {
  const snapshot = useSnapshot();
  const memory = useMemory();
  const act = useAct();
  const access = useWorkspaceAccess();
  const locale = useGenUiLocale();
  const { api, workspaceId } = useWorkspaceApi();
  const t: BrainTranslate = (en, hant, hans) => locale.language === 'zh-Hant' ? hant : locale.language === 'zh-Hans' ? hans : en;
  const [area, setArea] = useState<Area>('overview');
  const [step, setStep] = useState<Step>('sources');
  const [fallbackSetup, setFallbackSetup] = useState(false);
  const [error, setError] = useState('');
  const [working, setWorking] = useState(false);
  const revision = useRef(snapshot.data?.revision ?? 0);
  const mutex = useRef(false);
  const latestRevision = snapshot.data?.revision ?? 0;
  useEffect(() => { revision.current = latestRevision; }, [latestRevision]);
  useEffect(() => {
    panelStore.setOpen(false);
    const section = new URL(window.location.href).searchParams.get('section');
    if (section === 'boundaries' || section === 'identity') setArea('identity');
    else if (window.location.hash === '#manual-writing-samples') { setArea('teach'); setStep('sources'); }
  }, []);
  const state = snapshot.data?.state;
  const brain = brainView(state);
  const owner = snapshot.data?.membership?.role === 'owner';
  const profile = activeProfile(state);
  const status = voiceStatus(state);
  const proposal = state?.speaker?.provisional ?? null;
  const sources = state?.sources?.filter(s => s.kind === 'voice_sample') ?? [];
  const unavailable = snapshot.isError || !brain;
  const busy = working || act.isPending || unavailable || state?.workspace?.sample === true;
  const labels: Record<Area, string> = { overview: t('Overview', '總覽', '概览'), teach: t('Teach', '教導', '教导'), identity: t('Voice & identity', '風格與身分', '风格与身份'), preferences: t('Learned Preferences', '已學習偏好', '已学习偏好'), sources: t('Sources & permissions', '來源與權限', '来源与权限'), versions: t('Versions', '版本', '版本'), advanced: t('Advanced', '進階', '高级') };
  const stepLabels: Record<Step, string> = { sources: t('Choose writing', '選取文字', '选择文字'), analysis: t('Analysis', '分析', '分析'), review: t('Review', '審閱', '审阅'), preview: t('Preview & approve', '預覽及批准', '预览及批准') };
  async function run(action: string, payload: Record<string, unknown>): Promise<boolean> {
    if (mutex.current || busy) return false;
    mutex.current = true; setWorking(true); setError('');
    try {
      const result = await act.mutateAsync({ revision: revision.current, action, payload: { ...payload, requestId: crypto.randomUUID() } });
      revision.current = result.revision;
      const fresh = await snapshot.refetch();
      if (fresh.data) revision.current = fresh.data.revision;
      await memory.refetch();
      if (!fresh.data || fresh.isError) { setError(t('Saved, but server readback is unavailable. Reload before continuing.', '已儲存，但未能重新取得伺服器資料，請重新載入後繼續。', '已保存，但无法重新获取服务器数据，请重新加载后继续。')); return false; }
      return true;
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        await snapshot.refetch(); await memory.refetch();
        setError(t('The workspace changed. Review the latest proposal and permissions before trying again.', '工作區已更改，請審閱最新提案及權限後再試。', '工作区已更改，请审阅最新提案及权限后重试。'));
      } else {
        // A failed provider attempt may still persist a claim, receipt or consumed quote. Reconcile before another user action.
        await snapshot.refetch(); await memory.refetch();
        setError(e instanceof Error ? e.message : t('The change could not be saved.', '未能儲存變更。', '无法保存更改。'));
      }
      return false;
    } finally { mutex.current = false; setWorking(false); }
  }
  function navigate(value: Area) { setArea(value); setError(''); }
  function teach(next: Step = proposal ? 'review' : 'sources') { setStep(next); setArea('teach'); }
  const memorySnapshot = (memory.data as unknown as { snapshot?: { workspaceRevision?: number; renderDigest?: string } } | undefined)?.snapshot;
  const synced = !memory.isError && !!memorySnapshot?.renderDigest && memorySnapshot.workspaceRevision === latestRevision;
  const learned = profile?.analysisMethod && (profile.evidenceSourceIds?.length ?? 0) > 0;
  return <PageContainer pageTitle='Brand Brain' pageEyebrow={t('Your creative identity', '你的創作身分', '你的创作身份')} pageDescription={t('Teach Rafii what makes your writing yours.', '教 Rafii 掌握屬於你的寫作風格。', '教 Rafii 掌握属于你的写作风格。')} access={checkAccess(access, { permission: 'edit' })} pageHeaderAction={<Button variant='quiet' className='min-h-11' onClick={() => panelStore.setOpen(true)}>{t('Ask Rafii', '詢問 Rafii', '询问 Rafii')}</Button>}>
    {snapshot.isPending ? <BrandSkeleton /> : !snapshot.data || !state ? <BrandLoadError query={snapshot} /> : <div data-testid='brand-brain' className='flex min-w-0 flex-col gap-3 md:gap-5' dir={locale.dir} lang={locale.locale}>
      {snapshot.isError && <BrandStaleNotice query={snapshot} updatedAt={snapshot.dataUpdatedAt} />}
      {state.workspace?.sample && <StateMessage kind='permission' title={t('Sample workspace · changes are not saved', '範例工作區 · 不會儲存變更', '样例工作区 · 不会保存更改')} />}
      {!brain && <StateMessage kind='error' title={t('Brand Brain is unavailable on this server', '此伺服器暫時未能提供 Brand Brain', '此服务器暂时无法提供 Brand Brain')} description={t('Your existing voice and Memory remain available. Retry when the server is ready.', '現有風格及記憶仍然可用，請在伺服器就緒後重試。', '现有风格及记忆仍然可用，请在服务器就绪后重试。')} />}
      <div role='tablist' aria-label='Brand Brain' className='flex min-w-0 flex-nowrap gap-x-1 overflow-x-auto border-b md:flex-wrap'>{AREAS.map(tab => <button key={tab} id={`bb-tab-${tab}`} type='button' role='tab' aria-selected={area === tab} aria-controls={`bb-panel-${tab}`} tabIndex={area === tab ? 0 : -1} onClick={() => navigate(tab)} onKeyDown={e => { if (['ArrowRight', 'ArrowLeft', 'Home', 'End'].includes(e.key)) { e.preventDefault(); const index = AREAS.indexOf(tab); const next = e.key === 'Home' ? AREAS[0] : e.key === 'End' ? AREAS.at(-1)! : AREAS[(index + (e.key === 'ArrowRight' ? 1 : -1) + AREAS.length) % AREAS.length]; navigate(next); document.getElementById(`bb-tab-${next}`)?.focus(); } }} className={`rafii-focus min-h-11 shrink-0 whitespace-nowrap border-b-2 px-3 py-3 text-sm transition-colors motion-reduce:transition-none ${area === tab ? 'border-primary text-foreground font-medium' : 'border-transparent text-muted-foreground hover:text-foreground'}`}>{labels[tab]}</button>)}</div>
      {error && <div role='alert' className='rounded-xl border border-destructive/30 p-4 text-sm'>{error}</div>}
      <Surface material='quiet' className='space-y-2 p-3 md:p-5' data-tour='brand-status'><div className='flex flex-wrap gap-1.5 text-xs md:gap-3 md:text-sm'><span className='rounded-full border px-3 py-1'>{status.kind === 'active' ? `${t('Approved voice', '已批准風格', '已批准风格')} · v${status.revision}` : status.kind === 'unavailable' ? t('Voice unavailable', '未能取得風格', '无法获取风格') : t('No approved voice yet', '尚未批准任何風格', '尚未批准任何风格')}</span><span className='rounded-full border px-3 py-1'>{!brain ? t('Learning unavailable', '未能取得學習狀態', '无法获取学习状态') : proposal?.status === 'stale' ? t('Source changed · analyse again', '來源已更改 · 請重新分析', '来源已更改 · 请重新分析') : proposal ? t('Suggested improvements · waiting for review', '建議改進 · 等待審閱', '建议改进 · 等待审阅') : learned ? `${t('Learning from writing', '從文字學習', '从文字学习')} · ${profile?.evidenceSourceIds?.length} ${t('sources', '項來源', '项来源')}` : t('Learning from writing · Not set up', '從文字學習 · 尚未設定', '从文字学习 · 尚未设置')}</span><span className='rounded-full border px-3 py-1'>{synced ? t('Memory synced', '記憶已同步', '记忆已同步') : t('Memory not verified', '記憶尚未驗證', '记忆尚未验证')}</span></div><p className='text-xs text-muted-foreground'>{t('New drafts can use your approved voice when Writing like me is selected. A proposal never replaces it without owner approval.', '新草稿選取「用我的風格寫作」時可使用已批准風格，提案必須經擁有者批准才會取代目前版本。', '新草稿选择“用我的风格写作”时可使用已批准风格，提案必须经所有者批准才会取代当前版本。')}</p></Surface>
      <section role='tabpanel' id={`bb-panel-${area}`} aria-labelledby={`bb-tab-${area}`} tabIndex={0} className='rafii-focus min-w-0 rounded-sm'>
        {area === 'overview' && <div className='grid gap-5 lg:grid-cols-[minmax(0,1.8fr)_minmax(16rem,1fr)]'><div className='space-y-5'><Surface material='glass' padding='lg' className='space-y-3 p-4 md:space-y-5 md:p-7'><Icons.sparkles className='hidden size-7 text-primary md:block' aria-hidden /><div><p className='text-xs font-medium uppercase tracking-widest text-muted-foreground'>{t('Your next best step', '下一步', '下一步')}</p><h2 className='mt-2 text-2xl font-semibold md:mt-3 tracking-tight md:text-3xl'>{t('Teach Rafii your voice', '教 Rafii 你的寫作風格', '教 Rafii 你的写作风格')}</h2><p className='mt-2 max-w-xl text-sm md:mt-3 leading-relaxed text-muted-foreground'>{t('Choose writing you own. Review what Rafii learns before it is used.', '選取你擁有的文字，在採用前審閱 Rafii 學到的內容。', '选择你拥有的文字，在采用前审阅 Rafii 学到的内容。')}</p></div><Button data-testid='teach-voice' variant='action' className='min-h-11' disabled={!brain} onClick={() => teach()}>{proposal ? t('Review proposed voice', '審閱風格提案', '审阅风格提案') : t('Teach Rafii your voice', '教 Rafii 你的寫作風格', '教 Rafii 你的写作风格')}<Icons.arrowRight aria-hidden /></Button><div className='flex flex-wrap gap-4 text-xs'><button className='rafii-focus min-h-11 underline underline-offset-4' onClick={() => teach('sources')}>{t('Paste my writing', '貼上我的文字', '粘贴我的文字')}</button><button className='rafii-focus min-h-11 underline underline-offset-4' onClick={() => navigate('sources')}>{t('See exactly what Rafii can access', '查看 Rafii 可存取甚麼', '查看 Rafii 可访问什么')}</button></div></Surface>{brain && <Surface material='quiet'><BrainPreview brain={brain} busy={busy} run={run} t={t} onRefine={() => teach(proposal ? 'review' : 'sources')} /></Surface>}</div><div className='space-y-5'><Surface material='quiet' className='space-y-5'><h2 className='text-lg font-semibold'>{t('What Rafii knows', 'Rafii 掌握的資料', 'Rafii 掌握的信息')}</h2>{[[t('Identity', '身分', '身份'), state.brandHub?.purpose || t('No purpose confirmed yet', '尚未確認目標', '尚未确认目标')], [t('Writing voice', '寫作風格', '写作风格'), profile?.tone || t('No core voice specified', '尚未指定核心風格', '尚未指定核心风格')], [t('Boundaries', '界線', '边界'), t('Independent rules and privacy controls', '獨立規則及私隱控制', '独立规则及隐私控制')]].map(([title, description]) => <div key={title} className='border-b pb-3 last:border-0'><h3 className='text-sm font-medium'>{title}</h3><p dir='auto' className='mt-1 line-clamp-3 text-xs text-muted-foreground'>{description}</p></div>)}<Button variant='quiet' className='min-h-11' onClick={() => navigate('identity')}>{t('View voice & identity', '查看風格與身分', '查看风格与身份')}</Button></Surface>{brain && <Surface material='quiet' className='space-y-3'><h2 className='font-semibold'>{t('Existing content', '現有內容', '现有内容')}</h2><p className='text-sm'>{brain.impact.needsReview ?? t('Unavailable', '未有資料', '暂无数据')} · {t('Needs review', '需要審閱', '需要审阅')}</p><p className='text-sm'>{brain.impact.currentlyHeld ?? t('Unavailable', '未有資料', '暂无数据')} · {t('Held scheduled / approved posts', '已暫停的排程／已批准貼文', '已暂停的排程／已批准帖子')}</p><Link className='rafii-focus me-4 inline-flex min-h-11 items-center text-sm underline' href='/app/queue'>{t('Review content', '審閱內容', '审阅内容')}</Link><Link className='rafii-focus inline-flex min-h-11 items-center text-sm underline' href='/app'>{t('Open in Create', '開啟創作', '打开创作')}</Link></Surface>}</div></div>}
        {brain && <div hidden={area !== 'teach'}><Surface material='quiet' className='space-y-6'><ol className='flex flex-wrap gap-2' aria-label={t('Teach voice progress', '風格學習進度', '风格学习进度')}>{STEPS.map((value, index) => <li key={value}><Button variant={step === value ? 'glass' : 'quiet'} className='min-h-11' aria-current={step === value ? 'step' : undefined} onClick={() => { setStep(value); setFallbackSetup(false); }}>{index + 1}. {stepLabels[value]}</Button></li>)}</ol>
          {/* Keep the source intake mounted to preserve unsaved text across wizard steps. */}
          <div hidden={step !== 'sources' || fallbackSetup}><BrainSourcePicker {...{ sources, revision: latestRevision, brain, owner, busy, run, t }} /><div className='sticky bottom-[calc(4.25rem+env(safe-area-inset-bottom))] z-10 -mx-2 mt-5 flex flex-wrap gap-3 bg-background/95 px-2 py-3 backdrop-blur-sm md:static md:bg-transparent md:backdrop-blur-none'><Button variant='action' className='min-h-11' disabled={busy || !sources.some(s => s.active && s.selected)} onClick={() => setStep('analysis')}>{t('Next: permissions & analysis', '下一步：權限及分析', '下一步：权限及分析')}</Button><Button variant='quiet' className='min-h-11' onClick={() => setFallbackSetup(true)}>{t('Set up without samples', '不使用範例設定', '不使用样本设置')}</Button></div></div>
          {fallbackSetup && <VoiceSetup candidateRun={run} proposalOnly onProposed={() => { setFallbackSetup(false); setStep('review'); }} onDone={() => { setFallbackSetup(false); void snapshot.refetch(); void memory.refetch(); }} />}
          {step === 'analysis' && <BrainAnalysis {...{ sources, revision: latestRevision, brain, owner, busy, run, t }} onReady={() => setStep('review')} />}
          {step === 'review' && <BrainReview currentIdentity={state.brandHub} key={brain.proposalDigest} {...{ brain, proposal, current: profile, sources, owner, busy, run, t }} onPreview={() => setStep('preview')} />}
          {step === 'preview' && <div className='space-y-6'><BrainPreview {...{ brain, busy, run, t }} onRefine={() => setStep(proposal ? 'review' : 'sources')} /><div className='border-t pt-5'><BrainImpactDialog {...{ brain, owner, busy, run, t }} onApplied={() => { navigate('overview'); toast.success(t('Voice approved. Check memory sync and content needing review.', '風格已批准，請檢查記憶同步及需要審閱的內容。', '风格已批准，请检查记忆同步及需要审阅的内容。')); }} />{!owner && <p className='mt-2 text-xs text-muted-foreground'>{t('Your proposal is saved for owner review. Only an owner can activate it.', '提案已儲存供擁有者審閱，只有擁有者可啟用。', '提案已保存供所有者审阅，仅所有者可启用。')}</p>}</div></div>}
        </Surface></div>}
        {area === 'identity' && <div className='grid gap-5 lg:grid-cols-2'><BrainIdentityEditor key={`identity-${latestRevision}`} {...{ state, owner, busy, run, t }} /><BrainBoundaryEditor key={`boundaries-${latestRevision}`} {...{ state, owner, busy, run, t }} /><div className='lg:col-span-2'><GenomePanel /></div></div>}
        {area === 'preferences' && <LearningPanel />}
        {area === 'sources' && brain && <BrainSourceLedger {...{ sources, revision: latestRevision, brain, owner, busy, run, t }} />}
        {area === 'versions' && brain && <div className='space-y-4'>{proposal && <Surface material='quiet'><h2 className='font-semibold'>{t('Pending proposal · Needs review', '待定提案 · 需要審閱', '待定提案 · 需要审阅')}</h2><Button variant='quiet' className='mt-2 min-h-11' onClick={() => teach('review')}>{t('Review proposal', '審閱提案', '审阅提案')}</Button></Surface>}{brain.versions.toSorted((a, b) => Number(b.revision === state.speaker?.activeRevision) - Number(a.revision === state.speaker?.activeRevision) || b.revision - a.revision).map(record => <Surface key={record.revision} material='quiet' className='space-y-3'><div className='flex flex-wrap justify-between gap-3'><h2 className='font-semibold'>v{record.revision} {record.revision === state.speaker?.activeRevision ? `· ${t('Active', '啟用中', '启用中')}` : ''}</h2><span className='text-xs text-muted-foreground'>{locale.formatDateTime(record.approvedAt)}</span></div><p className='text-xs text-muted-foreground'>{t('Approved by', '批准者', '批准者')}: {record.approvedBy || t('Unavailable', '未有資料', '暂无数据')} · {record.profile.analysisMethod === 'ai' ? t('AI-assisted analysis', 'AI 輔助分析', 'AI 辅助分析') : record.profile.analysisMethod === 'local-rules' ? t('Local writing patterns', '本地寫作模式', '本地写作模式') : t('User-defined voice', '使用者自訂風格', '用户自定义风格')} · {record.profile.evidenceSourceIds?.length ?? 0} {t('sources', '項來源', '项来源')}</p><details><summary className='rafii-focus min-h-11 cursor-pointer py-3 text-sm'>{t('Compare with current voice', '與目前風格比較', '与当前风格比较')}</summary><BrainVersionCompare current={profile} target={record.profile} sources={sources} t={t} /></details>{record.revision !== state.speaker?.activeRevision && (record.restoreEligible ? <BrainImpactDialog {...{ brain, owner, busy, run, t }} restoreRevision={record.revision} /> : <div><p role='status' className='text-sm'>{t('Restore blocked: source permissions or evidence changed. Teach a clean proposal using currently permitted writing.', '無法還原：來源權限或證據已更改，請使用目前獲准的文字建立新提案。', '无法还原：来源权限或证据已更改，请使用目前获准的文字创建新提案。')}</p><Button data-testid={`bb-clean-restore-${record.revision}`} className='mt-3 min-h-11' variant='glass' disabled={busy} onClick={() => void run('brand_brain_clean_restore', { revision: record.revision }).then(ok => { if (ok) teach('review'); })}>{t('Create a clean proposal from this version', '由此版本建立乾淨提案', '由此版本创建干净提案')}</Button></div>)}</Surface>)}{brain.versions.length === 0 && <StateMessage kind='empty' title={t('No approved versions yet', '尚未有已批准版本', '尚无已批准版本')} />}</div>}
        {area === 'advanced' && <div className='space-y-5'><BrandBrainMemoryDiagnostics /><Link href='/app/workspace/memory' className='rafii-focus inline-flex min-h-11 items-center underline'>{t('Open legacy Memory and exports', '開啟原有記憶頁面及匯出', '打开原有记忆页面及导出')}</Link>{canExportPackage(profile) && <Button variant='glass' className='min-h-11' onClick={() => void api.exportProfile(workspaceId).then(blob => downloadBlob(blob, 'rafii-voice-package.zip')).catch(e => setError(e instanceof Error ? e.message : 'Export unavailable'))}>{t('Export voice package', '匯出風格檔案', '导出风格文件')}</Button>}</div>}
      </section>
    </div>}
  </PageContainer>;
}
