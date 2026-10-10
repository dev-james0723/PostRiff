'use client';
import type { SnapshotSource, VoiceProfile } from '@/lib/api/types';
import type { BrainTranslate } from './brain-types';

type BoundProfile = VoiceProfile & { sourceBindings?: { id: string; revision: number; contentHash: string }[] };
/** Compare immutable writing snapshots; current permissions remain separate and never restore with a voice. */
export function BrainVersionCompare({ current, target, sources, t }: { current: BoundProfile | null; target: BoundProfile; sources: SnapshotSource[]; t: BrainTranslate }) {
  const before = new Map((current?.dimensions ?? []).map(d => [d.id, d]));
  const after = new Map((target.dimensions ?? []).map(d => [d.id, d]));
  const ids = [...new Set([...before.keys(), ...after.keys()])];
  const changes = ids.filter(id => JSON.stringify(before.get(id)) !== JSON.stringify(after.get(id)));
  const added = (target.observations ?? []).filter(o => !current?.observations?.includes(o));
  const removed = (current?.observations ?? []).filter(o => !target.observations?.includes(o));
  return <div className='space-y-4 text-sm'>
    <p>{t('Core voice', '核心風格', '核心风格')}: <span dir='auto'>{current?.tone || t('Not set', '未設定', '未设置')}</span> → <span dir='auto'>{target.tone || t('Not set', '未設定', '未设置')}</span></p>
    <section><h3 className='font-medium'>{t('Changed traits', '已更改的風格項目', '已更改的风格项目')}</h3>{changes.length ? <ul className='mt-2 space-y-3'>{changes.map(id => <li key={id}><span className='text-xs font-medium'>{!before.has(id) ? t('Added', '新增', '新增') : !after.has(id) ? t('Removed', '移除', '移除') : t('Changed', '更改', '更改')} · {id.replaceAll('_', ' ')}</span>{before.get(id) && <p dir='auto' className='text-muted-foreground'>{t('Current', '目前', '当前')}: {before.get(id)?.observation}</p>}{after.get(id) && <p dir='auto'>{t('This version', '此版本', '此版本')}: {after.get(id)?.observation}</p>}</li>)}</ul> : <p className='mt-2 text-xs text-muted-foreground'>{t('No trait changes recorded', '未記錄風格項目變更', '未记录风格项目更改')}</p>}</section>
    {(added.length > 0 || removed.length > 0) && <section><h3 className='font-medium'>{t('Writing guidance', '寫作指引', '写作指引')}</h3><ul className='mt-2 space-y-2'>{added.map((o, i) => <li key={`add-${i}`} dir='auto'>{t('Added', '新增', '新增')}: {o}</li>)}{removed.map((o, i) => <li key={`remove-${i}`} dir='auto'>{t('Removed', '移除', '移除')}: {o}</li>)}</ul></section>}
    <section><h3 className='font-medium'>{t('Unknowns in this version', '此版本的未知項目', '此版本的未知项目')}</h3><ul className='mt-2 space-y-2'>{target.unknowns?.map((u, i) => <li key={i} dir='auto'>{u}</li>)}</ul></section>
    <section><h3 className='font-medium'>{t('Evidence and current permissions', '證據及目前權限', '证据及当前权限')}</h3><p className='mt-2 text-xs text-muted-foreground'>{t('Restoring writing style does not restore old permissions, identity facts or boundaries.', '還原寫作風格不會還原舊權限、身分事實或界線。', '还原写作风格不会还原旧权限、身份事实或边界。')}</p>{(target.sourceBindings ?? []).length ? <ul className='mt-3 space-y-3'>{target.sourceBindings!.map(binding => { const source = sources.find(s => s.id === binding.id); const valid = source?.active && source.contentHash === binding.contentHash && source.revision === binding.revision; return <li key={binding.id}><p className='break-words'>{source?.title || binding.id} · v{binding.revision} · {valid ? t('Source unchanged', '來源未有更改', '来源未更改') : t('Source changed or revoked', '來源已更改或撤銷', '来源已更改或撤销')}</p><p className='mt-1 break-all text-xs text-muted-foreground'>{t('Current grants', '目前授權', '当前授权')}: {source?.useGrants?.map(g => `${g.purpose}: ${g.route}`).join(' · ') || t('None', '沒有', '无')}</p></li>; })}</ul> : <p className='mt-2 text-xs text-muted-foreground'>{t('No source bindings recorded', '未記錄來源連結', '未记录来源绑定')}</p>}</section>
  </div>;
}
