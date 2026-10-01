'use client';

import type { ReactNode } from 'react';
import { Icons } from '@/components/icons';
import { StateMessage } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { StatusChip } from '@/features/workspace/rafii-parts';
import { cn } from '@/lib/utils';
import { failureOf } from './kit/api';
import { count, stateLabel, whenDate } from './kit/format';
import { DataStateChip, RetryAction } from './kit/page-frame';
import { SimpleTable } from './kit/simple-table';
import { evidenceText, isHypothesisFlag, ruleStateText, type CustomerRiskData, type JoinedFlag, type RiskRule, type RiskWorkspace, type ServerRiskFlag } from './customer-risk';
import type { useCustomerRisk } from './use-customer-risk';

/**
 * Risk flags as the server evaluated them (PRD §7.4): chips with their trigger and evidence, the workspaces of one
 * saved view, and the versioned rules with the state each was evaluated in. Flags are listed side by side and never
 * folded into a score; the one inferred flag (At-risk) is always marked as a hypothesis.
 */

type RiskQuery = ReturnType<typeof useCustomerRisk>;

function flagTitle(flag: ServerRiskFlag, workspaces: number): string {
  return [flag.trigger, evidenceText(flag), workspaces > 1 ? `on ${count(workspaces)} workspaces` : null, flag.since ? `since ${whenDate(flag.since)}` : null, `rule ${flag.version}`].filter(Boolean).join(' · ');
}

export function RiskChips({ flags, empty = 'No flags', className }: { flags: readonly JoinedFlag[]; empty?: ReactNode; className?: string }) {
  if (flags.length === 0) return <span className='text-muted-foreground text-xs'>{empty}</span>;
  return (
    <span className={cn('flex flex-wrap gap-1', className)}>
      {flags.map(({ flag, workspaceIds }) => (
        <StatusChip key={flag.id} status={isHypothesisFlag(flag) ? 'info' : 'warning'} title={flagTitle(flag, workspaceIds.length)}>
          {flag.label}
          {isHypothesisFlag(flag) && <span className='text-muted-foreground ml-1 font-normal'>(hypothesis)</span>}
        </StatusChip>
      ))}
    </span>
  );
}

/** What a table's chip column can promise: which rules ran, which could not, and whether the flagged list was cut. */
export function FlagCoverage({ risk }: { risk: RiskQuery }) {
  if (!risk.allowed) return <p className='text-muted-foreground text-xs'>Risk flags need the customers and workspaces read permissions on your operator.</p>;
  const { query } = risk;
  if (query.isPending) return <p className='text-muted-foreground text-xs'>Checking risk flags…</p>;
  if (query.error || !query.data) return <p className='text-muted-foreground text-xs'>Risk flags could not be loaded: {failureOf(query.error).message}</p>;
  const data = query.data.data;
  if (query.data.dataState === 'unavailable') return <p className='text-muted-foreground text-xs'>Risk flags are not available yet: no rule has its source. The Risk tab says what each rule needs.</p>;
  const missing = data.rules.filter((rule) => rule.id !== 'at_risk' && (rule.state === 'unavailable' || rule.state === 'partial'));
  return (
    <p className='text-muted-foreground text-xs'>
      Flags are observed rules {data.rulesVersion} evaluated by the server ({count(data.total)} flagged {data.total === 1 ? 'workspace' : 'workspaces'}
      {data.truncated ? `; chips cover the first ${count(data.limit)}` : ''}).
      {missing.length > 0 && ` ${missing.map((rule) => `${rule.label}: ${ruleStateText(rule)}`).join(' ')}`}
    </p>
  );
}

/** The chip cell for one table row: flags of the given workspace ids, or the honest reason there are none. */
export function FlagCell({ risk, flags }: { risk: RiskQuery; flags: readonly JoinedFlag[] }) {
  if (!risk.allowed) return <span className='text-muted-foreground text-xs'>—</span>;
  if (risk.query.isPending) return <span className='text-muted-foreground text-xs'>Checking…</span>;
  if (risk.query.error || !risk.query.data || risk.query.data.dataState === 'unavailable') return <span className='text-muted-foreground text-xs'>—</span>;
  const data = risk.query.data.data;
  return <RiskChips flags={flags} empty={data.truncated ? `Not among the first ${count(data.limit)} flagged` : 'No flags'} />;
}

function flagFor(row: RiskWorkspace, rule: string | null): ServerRiskFlag | null {
  return rule ? (row.flags.find((flag) => flag.id === rule) ?? null) : null;
}

/** The workspaces of one saved view (server order, at most 200), each with every flag it carries. */
export function RiskViewTable({ data, rule, onOpenCustomer }: { data: CustomerRiskData; rule: string | null; onOpenCustomer: (customerId: string) => void }) {
  return (
    <SimpleTable<RiskWorkspace>
      rows={data.rows}
      rowKey={(row) => row.workspaceId}
      caption={`Workspaces in this saved view${data.truncated ? `, first ${data.limit} of ${data.total}` : ''}`}
      emptyTitle='No workspace matches this view'
      emptyDescription='The rule ran and flagged nobody.'
      columns={[
        {
          key: 'workspace',
          label: 'Workspace',
          render: (row) => (
            <span className='flex min-w-40 flex-col'>
              <span className='text-foreground font-medium'>{row.name ?? 'Unnamed workspace'}</span>
              <span className='text-muted-foreground truncate text-xs'>{row.workspaceId}</span>
            </span>
          )
        },
        { key: 'plan', label: 'Plan', render: (row) => <StatusChip icon={null}>{stateLabel(row.plan)}</StatusChip> },
        { key: 'flags', label: 'Flags', render: (row) => <RiskChips flags={row.flags.map((flag) => ({ flag, workspaceIds: [row.workspaceId] }))} className='min-w-48' /> },
        {
          key: 'evidence',
          label: 'Evidence',
          render: (row) => {
            const flag = flagFor(row, rule);
            if (flag) return <span className='text-muted-foreground block min-w-56 text-xs whitespace-normal'>{evidenceText(flag) || flag.trigger}</span>;
            return (
              <ul className='text-muted-foreground flex min-w-56 flex-col gap-0.5 text-xs whitespace-normal'>
                {row.flags.map((item) => (
                  <li key={item.id}>
                    <span className='text-foreground'>{item.label}</span>
                    {evidenceText(item) ? `: ${evidenceText(item)}` : ''}
                    {item.since ? ` (since ${whenDate(item.since)})` : ''}
                  </li>
                ))}
              </ul>
            );
          }
        },
        ...(rule
          ? [
              {
                key: 'since',
                label: 'Since',
                render: (row: RiskWorkspace) => {
                  const flag = flagFor(row, rule);
                  return <span className='whitespace-nowrap tabular-nums'>{flag?.since ? whenDate(flag.since) : 'Not recorded'}</span>;
                }
              }
            ]
          : []),
        {
          key: 'open',
          label: <span className='sr-only'>Open</span>,
          render: (row) =>
            row.ownerId ? (
              <Button variant='quiet' size='sm' aria-label={`Open the customer for ${row.name ?? row.workspaceId}`} onClick={() => onOpenCustomer(row.ownerId as string)}>
                Customer <Icons.chevronRight />
              </Button>
            ) : (
              <span className='text-muted-foreground text-xs'>No owner</span>
            )
        }
      ]}
    />
  );
}

/** One saved view (or every flagged workspace when `rule` is null): its rule's state, the bounded list, and the honest states around it. */
export function RiskViewPanel({ risk, rule, label, onOpenCustomer }: { risk: RiskQuery; rule: string | null; label: string; onOpenCustomer: (customerId: string) => void }) {
  if (!risk.allowed) return <StateMessage kind='permission' title={`${label} needs customer access`} description='Saved views need the customers and workspaces read permissions on your operator.' />;
  const { query } = risk;
  if (query.isPending) return <StateMessage kind='loading' title={`Loading ${label.toLowerCase()}…`} />;
  if (query.error || !query.data) {
    const failure = failureOf(query.error);
    return <StateMessage kind={failure.status === 403 ? 'permission' : 'error'} title={`Couldn't load ${label.toLowerCase()}`} description={failure.message} action={<RetryAction onRetry={() => void query.refetch()} />} />;
  }
  const data = query.data.data;
  const ruleState = rule ? (data.rules.find((entry) => entry.id === rule) ?? null) : null;
  if (ruleState?.state === 'unavailable') return <StateMessage kind='unsupported' title={`${label} cannot be evaluated yet`} description={`${ruleState.trigger} ${ruleStateText(ruleState)}`} />;
  if (!rule && query.data.dataState === 'unavailable') return <StateMessage kind='unsupported' title='No risk rule can be evaluated yet' description='Every observed rule is missing its source. The rules below say which source each one needs.' />;
  return (
    <div className='flex min-w-0 flex-col gap-3'>
      <div className='flex flex-wrap items-center gap-2 text-xs'>
        <span className='text-foreground font-medium tabular-nums'>
          {count(data.total)} {data.total === 1 ? 'workspace' : 'workspaces'}
          {data.truncated ? `, first ${count(data.limit)} shown` : ''}
        </span>
        <DataStateChip state={query.data.dataState} asOf={data.asOf} />
        {ruleState && isHypothesisFlag(ruleState) && (
          <StatusChip status='info' icon={null}>
            Hypothesis
          </StatusChip>
        )}
      </div>
      {ruleState && (
        <p className='text-muted-foreground text-xs'>
          Rule {ruleState.version}: {ruleState.trigger} {ruleStateText(ruleState)}
        </p>
      )}
      <RiskViewTable data={data} rule={rule} onOpenCustomer={onOpenCustomer} />
    </div>
  );
}

/** The versioned rules with the state each was evaluated in for the current answer. */
export function RiskRulesList({ rules }: { rules: readonly RiskRule[] }) {
  return (
    <ul className='grid min-w-0 gap-2 md:grid-cols-2' aria-label='Risk rules'>
      {rules.map((rule) => (
        <li key={rule.id} className='rafii-quiet flex min-w-0 flex-col gap-1.5 rounded-[var(--rafii-radius-control)] p-3'>
          <div className='flex flex-wrap items-center justify-between gap-2'>
            <span className='text-foreground text-sm font-medium'>{rule.label}</span>
            <span className='flex flex-wrap gap-1'>
              <StatusChip icon={null} status={rule.basis === 'hypothesis' ? 'info' : undefined} className='h-6 px-2 text-[11px]'>
                {rule.basis === 'hypothesis' ? 'Hypothesis' : 'Observed'}
              </StatusChip>
              <StatusChip icon={null} className='h-6 px-2 text-[11px]'>
                Rule {rule.version}
              </StatusChip>
            </span>
          </div>
          <p className='text-muted-foreground text-xs leading-relaxed'>{rule.trigger}</p>
          <p className='text-foreground text-xs'>
            {ruleStateText(rule)} <span className='text-muted-foreground'>Source {rule.source}.</span>
          </p>
        </li>
      ))}
    </ul>
  );
}
