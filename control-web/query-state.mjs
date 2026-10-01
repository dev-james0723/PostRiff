// Independent query identity governs result, receipt selection and explanation.
export const initialQueryState = {revision:0,status:'idle',attempt:null,lastGood:null,selectedReceipt:null,explanation:null,error:''};
export const signature = value => JSON.stringify(value,(_,item)=>item&&typeof item==='object'&&!Array.isArray(item)?Object.fromEntries(Object.entries(item).sort(([a],[b])=>a.localeCompare(b))):item);
export function queryReducer(state,event){
  if(event.type==='changed')return {...state,revision:state.revision+1,status:state.lastGood?'previous':'idle',attempt:null,selectedReceipt:null,explanation:null,error:''};
  if(event.type==='start')return {...state,revision:event.revision,status:'loading',attempt:{revision:event.revision,query:event.query,snapshotId:event.snapshotId},selectedReceipt:null,explanation:null,error:''};
  if(event.type==='success'){
    if(event.revision!==state.revision||!state.attempt||signature(event.query)!==signature(state.attempt.query))return state;
    if(signature(event.result.normalizedQuery)!==signature(state.attempt.query)||event.result.sourceVersions?.snapshotId!==state.attempt.snapshotId)return {...state,status:'error',error:'Response did not match the selected query and snapshot.',selectedReceipt:null,explanation:null};
    return {...state,status:'ready',lastGood:{result:event.result,query:event.query,snapshotId:state.attempt.snapshotId,revision:event.revision},error:''};
  }
  if(event.type==='failed'){
    if(event.revision!==state.revision||!state.attempt)return state;
    return {...state,status:'error',error:event.error,selectedReceipt:null,explanation:null};
  }
  if(event.type==='select'){
    if(event.receiptId!==state.lastGood?.result.queryReceiptId)return state;
    return {...state,selectedReceipt:event.receiptId,explanation:null};
  }
  if(event.type==='close')return {...state,selectedReceipt:null,explanation:null};
  if(event.type==='explanation'){
    if(event.revision!==state.revision||event.receiptId!==state.selectedReceipt||event.run?.queryReceiptIds?.length!==1||event.run.queryReceiptIds[0]!==state.selectedReceipt)return state;
    return {...state,explanation:event.run};
  }
  return state;
}
