import { chromium } from 'playwright';
import { mkdir, writeFile } from 'node:fs/promises';
const output='/private/tmp/growit-acceptance';await mkdir(output,{recursive:true});
const results=[];const browser=await chromium.launch();
try {
for(const width of [1440,390]){
const context=await browser.newContext({viewport:{width,height:900}});
await context.addInitScript(()=>{localStorage.setItem('growit-signed-in',JSON.stringify({email:'admin',name:'admin',sub:'admin',at:0}));localStorage.setItem('tour-seen:admin','1');localStorage.setItem('tour-seen:local','1');});
const page=await context.newPage();const errors=[];const calls=[];
page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')errors.push(m.text());});
page.on('response',async r=>{if(/\/launch\/(pathways|ideas|names)$/.test(r.url()))calls.push({url:r.url(),status:r.status(),data:await r.json().catch(()=>null)});});
page.setDefaultTimeout(70000);await page.goto('http://127.0.0.1:3050/?nointro#/launch');
const inputs=page.locator('main section input');await inputs.nth(0).fill('Indiranagar, Bengaluru');await inputs.nth(1).fill('DEMO scenario: filter coffee preparation, cooking, friendly customer service');await page.getByLabel('Rupees you can start with each week').fill('2500');await inputs.nth(3).fill('20');await inputs.nth(4).fill('DEMO scenario: no late nights, no heavy lifting');await inputs.nth(5).fill('Brew House (sample)');await inputs.nth(6).fill('DEMO coffee business');
await page.getByRole('button',{name:'Find pathways',exact:true}).click();await page.locator('[data-launch="pathways"] button').first().waitFor();const pathways=await page.locator('[data-launch="pathways"] button').count();if(pathways<3)throw new Error('Fewer than three real pathways');await page.screenshot({path:`${output}/${width}-launch-pathways.png`,fullPage:true});
await page.locator('[data-launch="pathways"] button').first().click();await page.getByRole('button',{name:'Next',exact:true}).click();await page.locator('[data-launch="ideas"] button').first().waitFor();await page.locator('[data-launch="ideas"] button').first().click();await page.getByRole('button',{name:'Next',exact:true}).click();await page.getByLabel('Tagline',{exact:true}).waitFor();await page.waitForFunction(()=>document.querySelector('input[aria-label="Tagline"]')?.value);await page.getByRole('button',{name:'Next',exact:true}).click();await page.getByRole('button',{name:'Next',exact:true}).click();await page.getByRole('button',{name:'Next',exact:true}).click();const packs=await page.locator('[data-launch="packs"] button').count();if(packs<2)throw new Error('Fewer than two launch packs');await page.locator('[data-launch="packs"] button').first().click();await page.locator('[data-launch="packs"] button').nth(1).click();await page.screenshot({path:`${output}/${width}-launch-packs.png`,fullPage:true});results.push({width,pathways,packs,calls,errors,overflow:await page.evaluate(()=>document.documentElement.scrollWidth-innerWidth)});await context.close();
}
}finally{await browser.close();await writeFile(`${output}/demo-launch.json`,JSON.stringify(results,null,2));}
console.log(JSON.stringify(results));
