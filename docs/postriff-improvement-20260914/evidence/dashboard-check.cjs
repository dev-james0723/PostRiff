const { chromium } = require('/Users/ouxianxing/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs = require('fs');
(async()=>{
 const dir='/Users/ouxianxing/Documents/James-Au-Studio/docs/postriff-improvement-20260914';
 const browser=await chromium.launch({headless:true});
 try {
  const page=await browser.newPage({viewport:{width:1440,height:1050}});
  const errors=[]; page.on('pageerror',e=>errors.push(e.message));
  await page.goto('file://'+dir+'/index.html');
  if(await page.locator('#mrr').innerText() !== '$6,815') throw Error('base 36 month value');
  await page.locator('#scenario').selectOption('conservative');
  await page.locator('#month').selectOption('12');
  if(await page.locator('#mrr').innerText() !== '$578') throw Error('conservative 12 month value');
  await page.locator('#scenario').selectOption('base'); await page.locator('#month').selectOption('36');
  await page.screenshot({path:dir+'/evidence/dashboard.png',fullPage:true});
  await page.setViewportSize({width:390,height:844});
  if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)) throw Error('mobile overflow');
  if(errors.length)throw Error(errors.join(';'));
  fs.writeFileSync(dir+'/evidence/dashboard-result.json',JSON.stringify({status:'pass',checks:['base 36 month value','conservative 12 month value','scenario and month controls','mobile width','no page errors'],execution:'local-static-candidate-dashboard'},null,2));
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
