import {test} from 'node:test';
import assert from 'node:assert/strict';
import {assertPreviewEnvironment} from '../src/lib/deployment-env.mjs';
const good={VERCEL_ENV:'preview',POSTRIFF_ENVIRONMENT:'staging',POSTRIFF_STAGING_PROJECT_REF:'s'.repeat(20),POSTRIFF_PRODUCTION_PROJECT_REF:'p'.repeat(20),NEXT_PUBLIC_SUPABASE_URL:'https://'+'s'.repeat(20)+'.supabase.co',NEXT_PUBLIC_APP_URL:'https://staging.example',POSTRIFF_STAGING_PUBLIC_BASE_URL:'https://staging.example'};
test('preview build refuses production identity or cross-deployment API',()=>{
 assert.doesNotThrow(()=>assertPreviewEnvironment(good));
 assert.doesNotThrow(()=>assertPreviewEnvironment({VERCEL_ENV:'production'}));
 for(const [key,value] of [['POSTRIFF_ENVIRONMENT','production'],['POSTRIFF_PRODUCTION_PROJECT_REF','s'.repeat(20)],['NEXT_PUBLIC_SUPABASE_URL','https://production.example'],['POSTRIFF_API_ORIGIN','https://production.example'],['NEXT_PUBLIC_APP_URL','https://production.example']]) assert.throws(()=>assertPreviewEnvironment({...good,[key]:value}));
});
