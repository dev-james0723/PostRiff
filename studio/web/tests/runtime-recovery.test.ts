import test from 'node:test';
import assert from 'node:assert/strict';
import {pendingKey,retainedEdit,recoveryLabel,submission,reconcileEdits} from '../src/founder/runtime-state.ts';
test('offline edit keeps its original revision across changes and remains workspace scoped',()=>{
 const first=retainedEdit(undefined,{id:'variant',revision:2,text:'saved'},'local edit');
 const second=retainedEdit(first,{id:'variant',revision:3,text:'remote edit'},'continued local edit');
 assert.equal(second.variantRevision,2);assert.notEqual(second.idempotencyKey,first.idempotencyKey);assert.notEqual(pendingKey('one'),pendingKey('two'));
});
test('runtime recovery labels do not imply publication or provider fallback',()=>{
 assert.match(recoveryLabel('interrupted'),/partial text retained/);assert.match(recoveryLabel('completed'),/review/);assert.match(recoveryLabel('revoked'),/writes stopped/);
});

test('lost response is reconciled after restart without sending a second edit',()=>{
 const edit=retainedEdit(undefined,{id:'v',revision:2,text:'saved'},'sent');
 const pending=JSON.parse(JSON.stringify({v:{...edit,submitted:submission(edit)}}));
 assert.deepEqual(reconcileEdits(pending,[{id:edit.idempotencyKey,variantId:'v',variantRevision:3}]),{});
});
test('typing while save is in flight preserves new text and detects a later remote edit',()=>{
 const sent=retainedEdit(undefined,{id:'v',revision:2,text:'saved'},'first');
 const newer=retainedEdit({...sent,submitted:submission(sent)},{id:'v',revision:4,text:'remote'},'new local words');
 assert.equal(submission(newer).text,'first');
 const recovered=reconcileEdits({v:newer},[{id:sent.idempotencyKey,variantId:'v',variantRevision:3}]).v;
 assert.equal(recovered.text,'new local words');assert.equal(recovered.variantRevision,3);
 assert.equal(recovered.submitted,undefined);assert.notEqual(recovered.variantRevision,4);
});
test('foreign or absent acknowledgements never discard local text',()=>{
 const edit=retainedEdit(undefined,{id:'v',revision:1,text:'saved'},'local');
 const pending={v:{...edit,submitted:submission(edit)}};
 assert.equal(reconcileEdits(pending,[{id:edit.idempotencyKey,variantId:'other',variantRevision:2}]),pending);
});
