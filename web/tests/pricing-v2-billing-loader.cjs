// Real billing components; only the surrounding app shell, routing and API reads are synthetic.
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const { QueryClient, QueryClientProvider } = require('@tanstack/react-query');
const SRC = path.resolve(__dirname, '../src');
const BILLING = path.join(SRC, 'features/billing');
function environment(data, packResponse = { available: false, packs: [] }, queryError = false, usageRead = {}) {
  const cache = new Map();
  const query = value => ({ data: value, isPending: false, isSuccess: true, isError: false, dataUpdatedAt: 1, refetch: async () => ({ isError: false }) });
  const api = { creditPacks: async () => packResponse, creditCheckout: async () => { throw new Error('Synthetic harness refuses purchases'); } };
  const stubs = {
    'next/link': { default: ({ children, ...props }) => React.createElement('a', props, children) },
    'next/navigation': { useSearchParams: () => new URLSearchParams(), useRouter: () => ({ replace() {} }), usePathname: () => '/app/account/billing' },
    '@/components/layout/page-container': { default: ({ children, pageTitle }) => React.createElement('main', null, React.createElement('h1', null, pageTitle), children) },
    '@/lib/api/hooks': { useUsage: () => ({ ...query(data), ...usageRead }), useChannels: () => query({ channels: [], providers: [] }), useMembers: () => query({ members: [], membership: data.membership }) },
    '@/lib/workspace/provider': { useWorkspaceApi: () => ({ api, workspaceId: 'synthetic-billing' }) },
    '@/lib/auth/access': { useWorkspaceAccess: () => data.membership, checkAccess: (access, check) => access.permissions.includes(check.permission) }
  };
  function load(file) {
    // RED provenance: optional retained Git-base billing source, never an in-place rollback.
    if (process.env.TASK8_BILLING_BASE && file.startsWith(BILLING + path.sep)) file = path.join(process.env.TASK8_BILLING_BASE, path.relative(BILLING, file));
    if (cache.has(file)) return cache.get(file).exports;
    const mod = { exports: {} }; cache.set(file, mod);
    const local = name => {
      if (stubs[name]) return { __esModule: true, ...stubs[name] };
      if (!name.startsWith('@/') && !name.startsWith('.')) return require(name);
      const base = name.startsWith('@/') ? path.join(SRC, name.slice(2)) : path.resolve(path.dirname(file), name);
      const candidate = [base, `${base}.ts`, `${base}.tsx`, path.join(base, 'index.ts'), path.join(base, 'index.tsx')].find(p => fs.existsSync(p) && fs.statSync(p).isFile());
      if (!candidate) throw new Error(`Cannot resolve ${name} from ${file}`);
      return load(candidate);
    };
    const output = ts.transpileModule(fs.readFileSync(file, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2023, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } });
    new Function('require', 'module', 'exports', output.outputText)(local, mod, mod.exports);
    return mod.exports;
  }
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  client.setQueryData(['credit-packs', 'synthetic-billing'], packResponse);
  if (queryError) client.getQueryCache().find({ queryKey: ['credit-packs', 'synthetic-billing'] }).setState({ status: 'error', error: new Error('Synthetic read failure') });
  return { setUsageRead: next => Object.assign(usageRead, next), load: relative => load(path.join(SRC, relative)), render: (relative, name, props = {}) => {
    const Component = load(path.join(SRC, relative))[name];
    return renderToStaticMarkup(React.createElement(QueryClientProvider, { client }, React.createElement(Component, props)));
  } };
}
module.exports = { environment };
