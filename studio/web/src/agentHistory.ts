import {isActiveRun, type Conversation, type Run} from './agentApi.ts';

/** Keep displayed run and intake from the same conversation; cancellation wins. */
export function selectHistory(conversations:Conversation[], runs:Run[], requestId?:string) {
  const selectedRun=runs.find(isActiveRun)
    || (requestId?runs.find(run=>run.requestId===requestId):undefined)
    || runs[0] || null;
  const conversation=selectedRun
    ? conversations.find(item=>item.id===selectedRun.conversationId)||null
    : conversations[0]||null;
  return {conversation,run:selectedRun};
}

/** One finite scan of already known draft IDs. No polling, model calls or writes. */
export async function readWorkspaceRuns(
  draftIds:string[],
  readRuns:(draftId:string)=>Promise<{runs:Run[]}>,
  concurrency=3,
) {
  const queue=[...new Set(draftIds.filter(Boolean))], found:Run[]=[];
  let cursor=0;
  async function worker(){
    while(cursor<queue.length){
      const id=queue[cursor++], result=await readRuns(id);
      found.push(...result.runs.filter(run=>run.draftId===id));
    }
  }
  await Promise.all(Array.from({length:Math.min(queue.length,Math.max(1,Math.min(3,concurrency)))},()=>worker()));
  return [...new Map(found.map(run=>[run.id,run])).values()].sort((a,b)=>b.createdAt.localeCompare(a.createdAt));
}
