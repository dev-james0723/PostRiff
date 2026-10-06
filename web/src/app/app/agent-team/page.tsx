import type { Metadata } from 'next';
import { notFound } from 'next/navigation';
import { AgentTeamReportView } from '@/features/agent-team/report-view';

export const metadata: Metadata = {
  title: 'James Agent Team',
  robots: { index: false, follow: false }
};
export const dynamic = 'force-dynamic';
export const revalidate = 0;

type SearchParams = Record<string, string | string[] | undefined>;

function validWorkday(value: string): boolean {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!match) return false;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  if (year < 1 || month < 1 || month > 12 || day < 1) return false;
  const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  return day <= [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1];
}

export default async function Page({ searchParams }: { searchParams: Promise<SearchParams> }) {
  const params = await searchParams;
  const { workday, kind, version, acceptanceId } = params;
  if (
    Object.keys(params).some((key) => !['workday', 'kind', 'version', 'acceptanceId'].includes(key)) ||
    (acceptanceId !== undefined && (typeof acceptanceId !== 'string' || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(acceptanceId) || kind !== 'half_day')) ||
    typeof workday !== 'string' || !validWorkday(workday) ||
    (kind !== 'half_day' && kind !== 'whole_day') ||
    typeof version !== 'string' || !/^[1-9]\d{0,3}$/.test(version) ||
    !Number.isSafeInteger(Number(version))
  ) notFound();

  return <AgentTeamReportView key={`${workday}:${kind}:${version}:${acceptanceId ?? ''}`} workday={workday} kind={kind} version={Number(version)} acceptanceId={acceptanceId as string | undefined} />;
}
