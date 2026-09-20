/** Focused browser rendering of the real receipt component with a disposable-DB snapshot. No live app/session. */
import { createRequire } from 'node:module';
import { readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import ts from '../node_modules/typescript/lib/typescript.js';
import React from '../node_modules/react/index.js';
import { renderToStaticMarkup } from '../node_modules/react-dom/server.node.js';
const require=createRequire(import.meta.url);
const {chromium}=require('/Users/ouxianxing/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const filename=new URL('../src/features/queue/publication-receipt.tsx',import.meta.url);
const output=ts.transpileModule(readFileSync(filename,'utf8'),{compilerOptions:{jsx:ts.JsxEmit.ReactJSX,module:ts.ModuleKind.CommonJS}}).outputText;
const exports={}; new Function('require','exports',output)(createRequire(filename),exports);
const base=new URL('../../docs/postriff-research-20260918/evidence/',import.meta.url);
const job=JSON.parse(readFileSync(new URL('receipt-snapshot.json',base),'utf8'));
const html=renderToStaticMarkup(React.createElement(exports.PublicationReceipt,{job}));
const browser=await chromium.launch({executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless:true});
const checks=[];
try {
  for(const width of [390,1024]) {
    const page=await browser.newPage({viewport:{width,height:700}});
    await page.route('**/*',route=>route.abort());
    await page.setContent(`<html><head><meta name="viewport" content="width=device-width, initial-scale=1"><style>body{margin:24px;font:16px system-ui;color:#172029}main{max-width:620px;padding:20px;border:1px solid #ddd;border-radius:12px}p{overflow-wrap:anywhere}a{display:inline-block;color:#075985}a:focus-visible{outline:3px solid #075985;outline-offset:4px}</style></head><body><main><h1>Publication receipt</h1>${html}</main></body></html>`);
    await page.getByRole('link',{name:'Open verified post'}).waitFor();
    await page.keyboard.press('Tab');
    if(await page.locator(':focus').textContent()!=='Open verified post') throw Error('Receipt link not keyboard reachable');
    if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)) throw Error('Horizontal overflow');
    await page.screenshot({path:fileURLToPath(new URL(`receipt-${width}.png`,base)),fullPage:true});
    checks.push({width,keyboardFocus:'pass',overflow:'pass',receipt:'pass'});
    await page.close();
  }
} finally {await browser.close();}
writeFileSync(new URL('browser-checks.json',base),JSON.stringify({execution:'focused-local-receipt-fixture',checks},null,2));
console.log(JSON.stringify({execution:'focused-local-receipt-fixture',checks}));
