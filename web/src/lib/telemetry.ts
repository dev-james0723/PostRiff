import type { ErrorEvent } from '@sentry/nextjs';

function diagnosticFilename(value: string | undefined): string | undefined {
  if (!value) return undefined;
  try {
    const path = new URL(value).pathname;
    return /^\/_next\/static\/[a-zA-Z0-9/._-]+$/.test(path) ? path : '[withheld]';
  } catch {
    const name = value.split(/[\\/]/).at(-1) ?? '';
    return /^[a-zA-Z0-9._-]+\.(js|mjs|cjs|ts|tsx)$/.test(name) ? name : '[withheld]';
  }
}

/** Allow diagnostic structure only: no request, content, identities or free-form messages. */
export function scrubTelemetry(event: ErrorEvent): ErrorEvent {
  return {
    type: event.type,
    event_id: event.event_id,
    timestamp: event.timestamp,
    platform: event.platform,
    level: event.level,
    release: event.release,
    environment: event.environment,
    exception: event.exception ? {
      values: event.exception.values?.map((value) => ({
        type: ['Error','TypeError','RangeError','ReferenceError','SyntaxError','URIError','EvalError','AggregateError'].includes(value.type ?? '') ? value.type : 'Error',
        value: 'Application error (message withheld)',
        stacktrace: value.stacktrace ? {
          frames: value.stacktrace.frames?.map((frame) => ({
            filename: diagnosticFilename(frame.filename),
            lineno: frame.lineno,
            colno: frame.colno,
            in_app: frame.in_app
          }))
        } : undefined
      }))
    } : undefined
  };
}
