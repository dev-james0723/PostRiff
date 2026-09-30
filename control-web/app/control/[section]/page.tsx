import Control from '../control';
import FounderWorkspace from '../founder-workspace';
import { notFound } from 'next/navigation';
export const dynamic='force-dynamic';
export default async function Page({params,searchParams}:{params:Promise<{section:string}>;searchParams:Promise<{mode?:string;record?:string}>}) {
  const {section}=await params, query=await searchParams;
  const aliases:Record<string,string>={home:'command',revenue:'billing'};
  const destination=aliases[section]||section;
  if (['command','customers','workspaces','billing','support','product','settings','advanced'].includes(destination)) return <FounderWorkspace section={destination} mode={query.mode==='demo'?'demo':'live'} record={query.record}/>;
  if (!['infrastructure','engineering','evidence','audit','founder'].includes(section)) notFound();
  return <Control section={section==='evidence'?'command':section==='audit'?'settings':section}/>;
}
