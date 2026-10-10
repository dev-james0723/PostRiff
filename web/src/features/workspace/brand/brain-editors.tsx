'use client';
import { useState } from 'react';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Button } from '@/components/ui/button';
import { Surface } from '@/components/rafii';
import type { SnapshotState } from '@/lib/api/types';
import { FIELD_CLASS, TEXTAREA_CLASS, SelectField } from '../rafii-parts';
import type { BrainAction, BrainTranslate } from './brain-types';

type Props = { state: SnapshotState; owner: boolean; busy: boolean; run: BrainAction; t: BrainTranslate };
export function BrainIdentityEditor({ state, owner, busy, run, t }: Props) {
  const [fields, setFields] = useState({ speakerLabel: state.speaker?.label ?? '', identitySentence: state.you?.identitySentence ?? '', purpose: state.brandHub?.purpose ?? '', audience: state.brandHub?.audience ?? '', subject: state.brandHub?.subject ?? '', speaker: state.brandHub?.speaker ?? '' });
  const labels: Record<keyof typeof fields, string> = { speakerLabel: t('Name of speaker', '發言者名稱', '发言者名称'), identitySentence: t('My identity', '我的身分', '我的身份'), purpose: t('Purpose and positioning', '目標與定位', '目标与定位'), audience: t('Audience', '受眾', '受众'), subject: t('Brand or subject', '品牌或主題', '品牌或主题'), speaker: t('Who speaks for the brand', '品牌發言者', '品牌发言者') };
  return <Surface material='quiet' className='space-y-4'><div><h2 className='text-lg font-semibold'>{t('My Identity', '我的身分', '我的身份')}</h2><p className='mt-1 text-sm text-muted-foreground'>{t('Facts you confirm. Rafii never infers your identity from writing style.', '由你確認的事實，Rafii 不會從寫作風格推斷你的身分。', '由你确认的事实，Rafii 不会从写作风格推断你的身份。')}</p></div>{(Object.keys(fields) as (keyof typeof fields)[]).map(key => <label key={key} className='block space-y-2'><span className='text-sm'>{labels[key]}</span><Textarea className={TEXTAREA_CLASS} dir='auto' rows={2} value={fields[key]} maxLength={1200} disabled={!owner || busy} onChange={e => setFields(prev => ({ ...prev, [key]: e.target.value }))} /></label>)}<p className='text-xs text-muted-foreground'>{t('Saving changes the canonical brand context and may require existing drafts to be reviewed. Memory is checked again after saving.', '儲存會更改正式品牌背景，現有草稿可能需要重新審閱，之後會重新檢查記憶。', '保存会更改正式品牌背景，现有草稿可能需要重新审阅，之后会重新检查记忆。')}</p><Button className='min-h-11' variant='glass' disabled={!owner || busy} onClick={() => void run('brand_brain_identity', { fields, confirmed: true })}>{t('Confirm identity changes', '確認身分變更', '确认身份变更')}</Button></Surface>;
}

type Boundary = { id: string; label: string; value: string; privacy: 'public' | 'workspace_only' | 'private' | 'local_only' | 'excluded' };
function boundaryFields(state: SnapshotState): Boundary[] {
  type StoredField = { id?: string; key?: string; section?: string; label?: string; value?: unknown; privacy?: string };
  const profile = state.profile as { fields?: StoredField[] } | undefined;
  const active = state.speaker?.revisions.find(r => r.revision === state.speaker?.activeRevision)?.profile;
  const seen = new Set<string>();
  return [...(profile?.fields ?? []), ...(active?.fields as StoredField[] ?? [])].flatMap(f => {
    const id = f.id || f.key;
    if (!id || seen.has(id)) return [];
    seen.add(id);
    if (typeof f.value !== 'string' || !/boundar|privacy/i.test(`${f.section ?? ''} ${f.key ?? ''} ${id}`)) return [];
    return [{ id, label: f.label ?? id, value: f.value, privacy: (['public', 'workspace_only', 'private', 'local_only', 'excluded'].includes(f.privacy ?? '') ? f.privacy : 'private') as Boundary['privacy'] }];
  });
}
export function BrainBoundaryEditor({ state, owner, busy, run, t }: Props) {
  const [fields, setFields] = useState<Boundary[]>(() => boundaryFields(state));
  const [label, setLabel] = useState('');
  function edit(index: number, patch: Partial<Boundary>) { setFields(prev => prev.map((f, i) => i === index ? { ...f, ...patch } : f)); }
  return <Surface material='quiet' className='space-y-4'><div><h2 className='text-lg font-semibold'>{t('Rules & Boundaries', '規則與界線', '规则与边界')}</h2><p className='mt-1 text-sm text-muted-foreground'>{t('Describe what must not be shared. Do not paste secret values to express a prohibition.', '描述禁止分享的內容即可，請勿為表達禁令而貼上秘密資料。', '描述禁止分享的内容即可，请勿为表达禁令而粘贴秘密信息。')}</p></div>{!fields.length && <p className='text-sm text-muted-foreground'>{t('No editable boundary fields returned. Add an explicit rule below; existing system safeguards still apply.', '未有可編輯的界線欄位，可在下方加入明確規則，現有系統防護仍然有效。', '暂无可编辑的边界字段，可在下方添加明确规则，现有系统防护仍然有效。')}</p>}{fields.map((f, i) => <fieldset key={f.id} className='space-y-3 border-t pt-4'><legend className='font-medium'>{f.label}</legend><Textarea aria-label={f.label} className={TEXTAREA_CLASS} dir='auto' rows={3} maxLength={1200} value={f.value} onChange={e => edit(i, { value: e.target.value })} disabled={!owner || busy} /><SelectField label={t('Visibility', '可見範圍', '可见范围')} value={f.privacy} disabled={!owner || busy} onChange={e => edit(i, { privacy: e.target.value as Boundary['privacy'] })}><option value='private'>{t('Private · withheld from cloud', '私人 · 不傳送至雲端', '私密 · 不发送至云端')}</option><option value='local_only'>{t('Local only', '只限本地', '仅限本地')}</option><option value='excluded'>{t('Excluded from generation', '不供生成使用', '不供生成使用')}</option><option value='workspace_only'>{t('Workspace · subject to cloud consent', '工作區 · 仍需雲端授權', '工作区 · 仍需云端授权')}</option><option value='public'>{t('Public · subject to cloud consent', '公開 · 仍需雲端授權', '公开 · 仍需云端授权')}</option></SelectField></fieldset>)}{owner && <div className='flex flex-col gap-3 sm:flex-row'><Input className={FIELD_CLASS} aria-label={t('New boundary title', '新界線標題', '新边界标题')} value={label} onChange={e => setLabel(e.target.value)} maxLength={120} placeholder={t('New rule title', '新規則標題', '新规则标题')} /><Button className='min-h-11 shrink-0' variant='quiet' disabled={busy || !label.trim() || fields.length >= 50} onClick={() => { setFields(prev => [...prev, { id: `boundary_${crypto.randomUUID().replaceAll('-', '')}`, label: label.trim(), value: '', privacy: 'private' }]); setLabel(''); }}>{t('Add rule', '加入規則', '添加规则')}</Button></div>}<p className='text-xs text-muted-foreground'>{t('Cloud memory consent never overrides a private, local-only, excluded or unlabelled boundary. Changing these rules may hold existing content for review.', '雲端记憶授權不能覆蓋私人、本地、排除或未分類界線。更改規則可能暫停現有內容以供審閱。', '云端记忆授权不能覆盖私密、本地、排除或未分类边界。更改规则可能暂停现有内容以供审阅。')}</p><Button className='min-h-11' variant='glass' disabled={!owner || busy || !fields.length} onClick={() => void run('brand_brain_boundaries', { fields, confirmed: true })}>{t('Confirm boundary changes', '確認界線變更', '确认边界变更')}</Button></Surface>;
}
