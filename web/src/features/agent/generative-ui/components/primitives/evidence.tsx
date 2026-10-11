'use client';
import { scopedEvidence } from '@/lib/agent-runtime/evidence';
import { useGenUiLocale } from '../../core/locale';
import { EvidenceLink } from './layout';

/** Native disclosure: no network request, raw content retrieval, model call or generated facts. */
export function EvidenceDetails({ value, workspaceId }: { value: unknown; workspaceId?: string | null }) {
  const l = useGenUiLocale();
  const evidence = scopedEvidence(value, workspaceId);
  if (!evidence) return null;
  const chinese = l.language.startsWith('zh');
  const copy = chinese ? {
    evidence: '證據', source: '來源', entity: '來源項目', period: '資料收集期間', sync: '上次成功同步', definition: '定義', workspace: '工作區',
    unknown: '未有紀錄', classification: { observed: '觀察', inferred: '推論', recommended: '建議' },
  } : {
    evidence: 'Evidence', source: 'Source', entity: 'Source entity', period: 'Collection period', sync: 'Last successful sync', definition: 'Definition', workspace: 'Workspace',
    unknown: 'Not recorded', classification: { observed: 'Observed', inferred: 'Inferred', recommended: 'Recommended' },
  };
  const date = (value: string | null) => value ? <time dateTime={value} title={value}>{l.formatDateTime(value)} · {l.timeZone}</time> : copy.unknown;
  const { source, collectionPeriod, definition } = evidence;
  return <details data-evidence-mode='v1' className='mt-1 max-w-sm text-left text-xs font-normal break-words'>
    <summary className='cursor-pointer font-medium underline-offset-4 hover:underline'>{copy.evidence} · {copy.classification[evidence.classification]}</summary>
    <dl className='mt-2 grid gap-1 rounded-md border p-2'>
      <dt>{copy.source}</dt><dd><EvidenceLink props={{ label: source.document ?? source.platform ?? copy.unknown, href: source.href, source: source.provider ?? undefined }} renderNode={() => null} /></dd>
      <dt>{copy.entity}</dt><dd>{source.entityType ?? copy.unknown} · {source.entityId ?? copy.unknown}{source.connectionId ? ` · ${source.connectionId}` : ''}</dd>
      <dt>{copy.period}</dt><dd>{date(collectionPeriod.start)} – {date(collectionPeriod.end)}</dd>
      <dt>{copy.sync}</dt><dd>{date(evidence.lastSuccessfulSync)}</dd>
      <dt>{copy.definition}</dt><dd>{definition.name ?? copy.unknown} · {definition.version ?? copy.unknown}{definition.unit ? ` · ${definition.unit}` : ''}<p>{definition.description}</p></dd>
      <dt>{copy.workspace}</dt><dd>{evidence.workspaceId}</dd>
      <dt>{chinese ? '可用狀態' : 'Availability'}</dt><dd>{evidence.availability}</dd>
    </dl>
    {evidence.uncertainty.map((note, index) => <p className='mt-1 text-muted-foreground' key={index}>{note}</p>)}
  </details>;
}
