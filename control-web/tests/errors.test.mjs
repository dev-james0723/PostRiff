import test from 'node:test';
import assert from 'node:assert/strict';
import { controlError } from '../errors.mjs';
test('Authentication errors remain distinct from retryable identity failures',()=>{
 assert.equal(controlError(429,'RATE_LIMITED'),'Identity source is rate limited. Wait before retrying.');
 assert.equal(controlError(503,'SOURCE_UNAVAILABLE'),'Identity source is unavailable. Retry when it recovers.');
 assert.equal(controlError(401,'AUTH_REQUIRED'),'Authentication could not be verified. Sign in again.');
 assert.match(controlError(403,'FOUNDER_REQUIRED'),/permission/);
 assert.equal(controlError(503,'PRIVATE_PROVIDER_CANARY'),'Identity source is unavailable. Retry when it recovers.');
});
