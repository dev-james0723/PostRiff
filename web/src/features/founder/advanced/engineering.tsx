'use client';

import { StateMessage } from '@/components/rafii';
import { StatusChip } from '@/features/workspace/rafii-parts';
import { useFounderScope } from '../customers/kit/api';
import { stateLabel, whenDateTime } from '../customers/kit/format';
import { DataStateChip, QueryState } from '../customers/kit/page-frame';
import { SimpleTable } from '../customers/kit/simple-table';
import {
  CONCLUSION_TONE,
  KIND_LABELS,
  PROVIDER_LABELS,
  STATE_LABELS,
  engineeringVerdict,
  shortRef,
  shortSha,
  verdictText,
  type CheckSnapshot,
  type EngineeringEvidenceRow,
  type EngineeringVerdict
} from './engineering-model';
import { useCheckSnapshots, useEngineeringEvidence } from './hooks';

/**
 * Advanced → Engineering (CONTRACTS §8.D): attested exact-SHA evidence and the one overall state the server's rule
 * allows. Read-only: there is no dispatch, re-run or code action on this page. Demo has no engineering evidence and
 * says so instead of asking; an operator without `engineering.read` is told which capability is missing.
 */
function Verdict({ verdict }: { verdict: EngineeringVerdict | null }) {
  if (verdict === null) return <StateMessage kind='loading' layout='inline' title='Reading the required-check manifest…' />;
  return (
    <div className='rafii-quiet flex flex-col gap-2 rounded-[var(--rafii-radius-card)] p-4'>
      <div className='flex flex-wrap items-center gap-2'>
        <span className='text-sm font-medium'>Overall</span>
        <StatusChip status={verdict.state === 'checks_passed' ? 'success' : 'warning'}>{STATE_LABELS[verdict.state]}</StatusChip>
        {verdict.sha && (
          <span className='font-mono text-xs' title={verdict.sha}>
            {shortSha(verdict.sha)}
          </span>
        )}
        {verdict.manifestProvenance && <span className='text-muted-foreground text-xs'>Manifest: {stateLabel(verdict.manifestProvenance)}</span>}
      </div>
      <p className='text-muted-foreground text-xs'>{verdictText(verdict)}</p>
    </div>
  );
}

function EvidenceTable({ rows }: { rows: EngineeringEvidenceRow[] }) {
  return (
    <SimpleTable<EngineeringEvidenceRow>
      className='relative'
      rows={rows}
      rowKey={(row) => row.id}
      caption='Attested exact-SHA engineering evidence'
      columns={[
        { key: 'kind', label: 'Kind', render: (row) => KIND_LABELS[row.kind] ?? stateLabel(row.kind) },
        { key: 'provider', label: 'Provider', render: (row) => PROVIDER_LABELS[row.provider] ?? stateLabel(row.provider) },
        {
          key: 'reference',
          label: 'Reference',
          render: (row) => {
            const ref = shortRef(row.external_id);
            return ref ? (
              <span className='font-mono text-xs' title={row.external_id ?? undefined}>
                {ref}
              </span>
            ) : (
              <span className='text-muted-foreground'>—</span>
            );
          }
        },
        {
          key: 'sha',
          label: 'SHA',
          render: (row) => {
            const sha = shortSha(row.exact_sha);
            return sha ? (
              <span className='font-mono text-xs' title={row.exact_sha ?? undefined}>
                {sha}
              </span>
            ) : (
              <span className='text-muted-foreground whitespace-nowrap'>No exact SHA</span>
            );
          }
        },
        {
          key: 'conclusion',
          label: 'Conclusion',
          render: (row) =>
            row.conclusion ? <StatusChip status={CONCLUSION_TONE[row.conclusion] ?? 'neutral'}>{stateLabel(row.conclusion)}</StatusChip> : <span className='text-muted-foreground whitespace-nowrap'>Not reported</span>
        },
        { key: 'required', label: 'Required', render: (row) => (row.required ? 'Yes' : <span className='text-muted-foreground'>No</span>) },
        { key: 'attested', label: 'Attested', render: (row) => (row.attested ? 'Yes' : <span className='text-muted-foreground'>No</span>) },
        { key: 'observed', label: 'Observed', render: (row) => <span className='whitespace-nowrap'>{whenDateTime(row.observed_at)}</span> }
      ]}
    />
  );
}

export function EngineeringChecks() {
  const scope = useFounderScope();
  const evidence = useEngineeringEvidence();
  const snapshots = useCheckSnapshots();
  if (scope.mode === 'demo') {
    return <StateMessage kind='unsupported' title='Demo has no engineering evidence' description='Attested CI evidence comes from the live environment only; Demo does not simulate it.' />;
  }
  if (scope.ready && !scope.capabilities.includes('engineering.read')) {
    return <StateMessage kind='permission' title='Engineering evidence needs engineering.read' description='Attested exact-SHA evidence is listed for operators holding the engineering.read capability.' />;
  }
  // undefined while the manifest is being read; null when it could not be read (the state then stays 'suspected').
  const manifests: readonly CheckSnapshot[] | null | undefined = snapshots.isPending ? undefined : snapshots.error ? null : (snapshots.data?.snapshots ?? []);
  return (
    <div className='flex flex-col gap-4'>
      <QueryState
        query={evidence}
        label='engineering evidence'
        isEmpty={(result) => result.evidence.length === 0}
        emptyTitle='No attested CI evidence ingested yet'
        emptyDescription='Checks, deployments and errors appear here once the attested ingest records them for this environment. Nothing is inferred from branch names.'
      >
        {(result) => (
          <div className='flex flex-col gap-3'>
            <div className='flex flex-wrap items-center gap-2'>
              <DataStateChip state={result.dataState} asOf={result.asOf} />
              <span className='text-muted-foreground text-xs'>
                Latest {result.evidence.length} {result.evidence.length === 1 ? 'row' : 'rows'}, newest first.
              </span>
            </div>
            <Verdict verdict={manifests === undefined ? null : engineeringVerdict(result.evidence, manifests)} />
            <EvidenceTable rows={result.evidence} />
          </div>
        )}
      </QueryState>
      <p className='text-muted-foreground text-xs'>
        Read-only: nothing here dispatches, re-runs or changes code. &lsquo;Checks passed&rsquo; means every check the manifest requires was attested green on one exact SHA; it never means merged, deployed or fixed.
      </p>
    </div>
  );
}
