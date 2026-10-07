import test from 'node:test';
import assert from 'node:assert/strict';
import {initialQueryState,queryReducer} from '../query-state.mjs';
const query={metricIds:['check_failures'],interval:{start:'2026-09-29T00:00:00Z',end:'2026-09-30T00:00:00Z',timeZone:'UTC'},groupBy:['suite','failure_class'],filters:[],comparison:'none',limit:100};
test('failed changed query retains only labeled previous evidence and clears explanation selection',()=>{
 let state=queryReducer(initialQueryState,{type:'start',revision:1,query,snapshotId:'a'});
 state=queryReducer(state,{type:'success',revision:1,query,result:{queryReceiptId:'old',rows:[],normalizedQuery:query,sourceVersions:{snapshotId:'a'}}});
 state=queryReducer(state,{type:'select',receiptId:'old'});
 state=queryReducer(state,{type:'changed'});
 assert.equal(state.selectedReceipt,null);
 const next={...query,filters:[{dimension:'suite',operator:'eq',values:['other']}]};
 state=queryReducer(state,{type:'start',revision:3,query:next,snapshotId:'a'});
 state=queryReducer(state,{type:'failed',revision:3,error:'Unavailable'});
 assert.equal(state.status,'error');assert.equal(state.lastGood.result.queryReceiptId,'old');
 assert.deepEqual(state.attempt.query,next);assert.equal(state.explanation,null);
 assert.equal(queryReducer(state,{type:'success',revision:1,query,result:{queryReceiptId:'late'}}),state);
});
test('out of order responses and explanation for cleared receipt never replace current state',()=>{
 let state=queryReducer(initialQueryState,{type:'start',revision:1,query,snapshotId:'a'});
 state=queryReducer(state,{type:'start',revision:2,query,snapshotId:'b'});
 const unchanged=queryReducer(state,{type:'success',revision:1,query,result:{queryReceiptId:'late'}});
 assert.equal(unchanged,state);
 state=queryReducer(state,{type:'success',revision:2,query,result:{queryReceiptId:'current',normalizedQuery:query,sourceVersions:{snapshotId:'b'}}});
 assert.equal(queryReducer(state,{type:'select',receiptId:'late'}),state);
 state=queryReducer(state,{type:'select',receiptId:'current'});
 state=queryReducer(state,{type:'changed'});
 assert.equal(queryReducer(state,{type:'explanation',revision:2,receiptId:'current',run:{answerText:'late'}}),state);
});
test('a response for another query or snapshot is never admitted into the visible receipt',()=>{
 let state=queryReducer(initialQueryState,{type:'start',revision:1,query,snapshotId:'a'});
 const wrong={queryReceiptId:'bad',normalizedQuery:{...query,limit:1},sourceVersions:{snapshotId:'a'}};
 const result=queryReducer(state,{type:'success',revision:1,query,result:wrong});
 assert.equal(result.lastGood,null);assert.equal(result.status,'error');
});
test('an explanation cannot substitute a different receipt than the selected evidence',()=>{
 let state=queryReducer(initialQueryState,{type:'start',revision:1,query,snapshotId:'a'});
 state=queryReducer(state,{type:'success',revision:1,query,result:{queryReceiptId:'A',normalizedQuery:query,sourceVersions:{snapshotId:'a'}}});
 state=queryReducer(state,{type:'select',receiptId:'A'});
 state=queryReducer(state,{type:'explanation',revision:1,receiptId:'A',run:{queryReceiptIds:['B'],answerText:'wrong'}});
 assert.equal(state.explanation,null);
});
