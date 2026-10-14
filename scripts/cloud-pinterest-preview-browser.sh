#!/usr/bin/env bash
set -euo pipefail
if [ "$(uname -s)" != Linux ] || [ "${CI:-}" != true ]; then
  echo 'Use the JCB cloud e2e runner.' >&2; exit 64
fi
cd "$(dirname "$0")/.."
task_root="$PWD"
fixture_backup="$(mktemp)"
cp web/src/components/application/post-preview/gallery.tsx "$fixture_backup"
preview_server_pid=''
cleanup() {
  if [ -n "$preview_server_pid" ]; then kill "$preview_server_pid" 2>/dev/null || true; fi
  cp "$fixture_backup" "$task_root/web/src/components/application/post-preview/gallery.tsx"
  rm -f "$fixture_backup"
  rm -f "$task_root/web/src/features/queue/pinterest-contract.tsx" "$task_root/web/src/features/queue/pinterest-fixture-api.ts" "$task_root/web/src/app/dev/pinterest-fields/page.tsx"
  rmdir "$task_root/web/src/app/dev/pinterest-fields" 2>/dev/null || true
}
trap cleanup EXIT
# Test-only overlay in a disposable cloud checkout. The shipped template is unchanged.
python3 - <<'PY'
from pathlib import Path
p=Path('web/src/components/application/post-preview/gallery.tsx')
s=p.read_text()
s="import { pinterestPreviewFields } from './preview-metadata';\n" + s
# Preserve the client directive before imports.
s=s.replace("import { pinterestPreviewFields } from './preview-metadata';\n'use client';", "'use client';\nimport { pinterestPreviewFields } from './preview-metadata';")
old='            text: sampleText(channel.region),'
assert s.count(old)==1
s=s.replace(old, old+'''
            ...(channel.slug === 'pinterest' ? pinterestPreviewFields({
              title: params.has('emptyTitle') ? undefined : 'Exact approved mock title',
              boardId: '1234567',
              link: params.has('unsafeLink') ? 'javascript:alert(1)' : 'https://example.com/approved-destination'
            }) : {}),''')
p.write_text(s)
fixture=Path('web/src/features/queue/pinterest-contract.tsx')
assert not fixture.exists()
component=Path('web/src/features/queue/publish-options.tsx').read_text()
component=component.replace("import { useWorkspaceApi } from '@/lib/workspace/provider';", "import { useWorkspaceApi } from './pinterest-fixture-api';")
fixture.write_text(component+"\nexport { PinterestFields };\n")
Path('web/src/features/queue/pinterest-fixture-api.ts').write_text("""
const api = { channelDestinations: async (_w: string, account: string, boardId?: string) => {
  await new Promise(resolve => setTimeout(resolve, 20));
  return {connectionId:account,scope:'post',destinations:boardId
    ? [{id:'6543210',name:'Mock section',kind:'section',boardId,selected:false}]
    : [{id:account==='a'?'1234567':'7654321',name:'Public Mock Board',kind:'board',privacy:'PUBLIC',eligible:true,selected:false},
       {id:'9999999',name:'Secret Mock Board',kind:'board',privacy:'SECRET',eligible:false,selected:false}]};
}};
export function useWorkspaceApi() { return {workspaceId:'synthetic',api}; }
""")
page=Path('web/src/app/dev/pinterest-fields/page.tsx')
assert not page.exists();page.parent.mkdir(parents=True,exist_ok=True)
page.write_text("""'use client';
import { useCallback, useState } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { PinterestFields } from '@/features/queue/pinterest-contract';
export default function Page() {
  const [client] = useState(() => new QueryClient());
  const [account,setAccount] = useState('a');
  const [options,setOptions] = useState('null');
  const change = useCallback((value: unknown) => setOptions(JSON.stringify(value)),[]);
  return <QueryClientProvider client={client}><main>
    <button onClick={()=>setAccount('b')}>Switch mock account</button>
    <PinterestFields channelId={account} asset={{id:'synthetic',mime:'image/jpeg',bytes:1024} as never} onChange={change} />
    <pre data-testid='pin-options'>{options}</pre>
  </main></QueryClientProvider>;
}
""")
PY
cd web
node node_modules/playwright/cli.js install --with-deps chromium
POSTRIFF_DIST_DIR=.next-pinterest-preview node node_modules/next/dist/bin/next dev --hostname 127.0.0.1 --port 4440 > /tmp/pinterest-preview-next.log 2>&1 &
preview_server_pid=$!
node tests/pinterest-preview-browser.cjs
