import Control from '../control';
import { notFound } from 'next/navigation';
export const dynamic='force-dynamic';
export default async function Page({params}:{params:Promise<{section:string}>}) {
  const {section}=await params;
  if (!['command','customers','revenue','product','infrastructure','engineering','support','settings','workspaces','founder'].includes(section)) notFound();
  return <Control section={section}/>;
}
