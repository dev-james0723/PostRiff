import test from 'node:test';
import assert from 'node:assert/strict';
import {pendingKey,retainedEdit,recoveryLabel} from '../src/founder/runtime-state.ts';
test('offline edit keeps its original revision across changes and remains workspace scoped',()=>{
 const first=retainedEdit(undefined,{id:'variant',revision:2,text:'saved'},'local edit');
 const second=retainedEdit(first,{id:'variant',revision:3,text:'remote edit'},'continued local edit');
 assert.equal(second.variantRevision,2);assert.equal(second.idempotencyKey,first.idempotencyKey);assert.notEqual(pendingKey('one'),pendingKey('two'));
});
test('runtime recovery labels do not imply publication or provider fallback',()=>{
 assert.match(recoveryLabel('interrupted'),/partial text retained/);assert.match(recoveryLabel('completed'),/review/);assert.match(recoveryLabel('revoked'),/writes stopped/);
});
