'use client';

import { parseAsString, useQueryState } from 'nuqs';
import { StateMessage } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { Band, Panel } from '@/features/workspace/rafii-parts';
import { whenDateTime } from '../customers/kit/format';
import { DataStateChip, QueryState } from '../customers/kit/page-frame';
import { ReceiptChips } from '../shared/receipt-chip';
import { BriefingSchedules } from './briefing-schedules';
import { reportBasis, reportCoverage, reportTitle, type ReportSummary } from './comms';
import { useReport, useReports } from './comms-hooks';

/**
 * Settings → Reports (CONTRACTS §8.E): every briefing version Rafii wrote, newest first, with the receipts behind its values
 * (each chip opens the evidence drawer), its coverage and its basis — receipted metric queries, or cron observations when
 * the query service could not answer. A version never changes once written; the text is the stored one. Demo has no
 * simulated briefings. `?report=<id>` (a notice's link) opens that version when it is among the latest.
 */

function ReportBody({ id }: { id: string }) {
  const query = useReport(id);
  return (
    <div id={`briefing-${id}`} className='flex min-w-0 flex-col gap-3 pt-1'>
      <QueryState query={query} label='briefing' layout='inline'>
        {({ report, receiptIds }) => (
          <>
            {report.sections.map((section) => (
              <section key={section.id} className='flex min-w-0 flex-col gap-1' aria-label={section.title}>
                <h4 className='text-foreground text-xs font-medium'>{section.title}</h4>
                <ul className='text-muted-foreground flex list-disc flex-col gap-0.5 pl-5 text-xs'>
                  {section.lines.map((line, index) => (
                    <li key={index} className='break-words'>
                      {line}
                    </li>
                  ))}
                </ul>
              </section>
            ))}
            <details className='text-xs'>
              <summary className='rafii-focus text-muted-foreground cursor-pointer rounded'>Full text as written</summary>
              <pre className='text-foreground mt-2 font-sans text-xs break-words whitespace-pre-wrap'>{report.text}</pre>
            </details>
            <ReceiptChips receiptIds={receiptIds} max={12} />
          </>
        )}
      </QueryState>
    </div>
  );
}

function VersionItem({ report, open, onToggle }: { report: ReportSummary; open: boolean; onToggle: () => void }) {
  const receipts = report.receiptIds ?? [];
  return (
    <li className='min-w-0'>
      <Band className='gap-2'>
        <div className='flex flex-wrap items-start justify-between gap-2'>
          <div className='flex min-w-0 flex-col gap-0.5'>
            <h3 className='text-foreground text-sm font-medium'>{reportTitle(report)}</h3>
            <p className='text-muted-foreground text-xs break-words'>
              {whenDateTime(report.generatedAt)} · {reportCoverage(report.coverage)} · {reportBasis(report.coverage)}
            </p>
          </div>
          <DataStateChip state={report.coverage?.dataState} />
        </div>
        {receipts.length > 0 ? <ReceiptChips receiptIds={receipts} /> : <p className='text-muted-foreground text-xs'>No receipts: this version was written without receipted values.</p>}
        <Button type='button' variant='quiet' size='sm' className='self-start' aria-expanded={open} aria-controls={open ? `briefing-${report.id}` : undefined} onClick={onToggle}>
          {open ? 'Hide briefing' : 'Read briefing'}
        </Button>
        {open && <ReportBody id={report.id} />}
      </Band>
    </li>
  );
}

function BriefingVersions() {
  const query = useReports();
  const [selected, setSelected] = useQueryState('report', parseAsString.withOptions({ history: 'replace' }));
  return (
    <QueryState query={query} label='briefing versions' layout='inline'>
      {(data) => {
        if (data.mode === 'demo') {
          return <StateMessage kind='unsupported' layout='inline' title='Demo has no briefings' description='Briefings are written from Live receipts only, and Demo never shows them.' />;
        }
        if (data.reports.length === 0) {
          return <StateMessage kind='empty' layout='inline' title='No briefings yet' description='A version appears here after a briefing schedule below runs.' />;
        }
        // Only an id the list returned is ever fetched, so a stale or foreign link never becomes a failed request.
        const missing = selected !== null && !data.reports.some((report) => report.id === selected);
        return (
          <div className='flex flex-col gap-3'>
            {missing && <StateMessage kind='empty' layout='inline' title='That briefing is not among the latest 20' description='Older versions are kept; open the newest ones below.' />}
            <ul className='flex flex-col gap-3'>
              {data.reports.map((report) => (
                <VersionItem key={report.id} report={report} open={selected === report.id} onToggle={() => void setSelected(selected === report.id ? null : report.id)} />
              ))}
            </ul>
          </div>
        );
      }}
    </QueryState>
  );
}

export function ReportsTab() {
  return (
    <div className='flex flex-col gap-4'>
      <Panel title='Briefing versions' description='Each briefing Rafii wrote, newest first, with the receipts behind its values. A version never changes once written.'>
        <BriefingVersions />
      </Panel>
      <Panel title='Briefing schedules' description='Daily or weekly briefings composed from receipted metric queries. Versions are readable here even while delivery is off.'>
        <BriefingSchedules />
      </Panel>
    </div>
  );
}
