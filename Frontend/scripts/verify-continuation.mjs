import { chromium } from 'playwright';
import { mkdir, writeFile } from 'node:fs/promises';
const out='/private/tmp/growit-acceptance'; await mkdir(out,{recursive:true});
const base='http://127.0.0.1:3050';
const memory=await (await fetch('http://127.0.0.1:8031/memory')).json();
const source=memory.items[0];
const browser=await chromium.launch(); const results=[];
for (const viewport of [{width:1440,height:900},{width:390,height:844}]) {
 const context=await browser.newContext({viewport});
 await context.addInitScript(()=>{try {localStorage.setItem('growit-signed-in',JSON.stringify({email:'admin',name:'admin',sub:'admin',at:0}));localStorage.setItem('tour-seen:admin','1');localStorage.setItem('tour-seen:local','1');}catch {}});
 const page=await context.newPage(); const errors=[];
 page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')errors.push(m.text());});
 for (const route of ['studio','identity','brand','website','settings','connections','launch','replies/demo-613663d1220f','log/demo-613663d1220f','memory']) {
  errors.length=0;await page.goto(`${base}/?nointro#/${route}`);await page.waitForTimeout(1200);
  if(!await page.locator('main').count()) throw new Error('App did not render: '+errors.join('; '));
  const row={viewport:viewport.width,route,errors:[...errors],overflow:await page.evaluate(()=>document.documentElement.scrollWidth-innerWidth)};
  if(route==='studio'){const b=page.locator('main section button[aria-pressed]').first();if(await b.isVisible()){await b.click();row.interaction='clicked studio option';}}
  if(route==='connections')row.configuration=await page.locator('main').innerText();
  if(route==='memory' && source){await page.getByRole('button',{name:'Import',exact:true}).click();await page.getByLabel('Paste it here').fill(JSON.stringify([{title:source.title,body:source.body}]));await page.getByRole('button',{name:'Review entries',exact:true}).click();await page.getByLabel('Title, entry 1',{exact:true}).waitFor();row.importPreview=await page.getByLabel('Title, entry 1',{exact:true}).inputValue();const response=page.waitForResponse(r=>r.url().endsWith('/memory/import')&&r.request().method()==='POST');await page.getByRole('button',{name:'Save 1',exact:true}).click();row.importSave=await (await response).json();}
  if(route==='settings'){const tabs=page.getByRole('button',{name:'Voice',exact:true});if(await tabs.count())await tabs.click();}
  await page.evaluate(async()=>{await Promise.all([...document.images].map(i=>i.complete?Promise.resolve():new Promise(r=>{i.onload=r;i.onerror=r;})));});
  await page.screenshot({path:`${out}/${viewport.width}-${route.replaceAll('/','-')}.png`,fullPage:true});results.push(row);
 }
 await page.getByRole('button',{name:/^Notifications/}).first().click();await page.waitForTimeout(500);
 const bell=page.getByRole('dialog',{name:'Notifications'});const box=await bell.boundingBox();results.push({viewport:viewport.width,route:'bell',box,fits:box&&box.x>=0&&box.y>=0&&box.x+box.width<=viewport.width&&box.y+box.height<=viewport.height});
 await page.screenshot({path:`${out}/${viewport.width}-bell.png`});await context.close();
}
await browser.close();await writeFile(`${out}/results.json`,JSON.stringify(results,null,2));console.log(JSON.stringify(results));
