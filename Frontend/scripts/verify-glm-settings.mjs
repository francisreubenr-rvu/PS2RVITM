import { chromium } from 'playwright';
import { writeFile } from 'node:fs/promises';
const b=await chromium.launch();const rows=[];
for(const width of [1440,390]){
 const c=await b.newContext({viewport:{width,height:900}});await c.addInitScript(()=>{localStorage.setItem('growit-signed-in',JSON.stringify({email:'admin',name:'admin',sub:'admin',at:0}));localStorage.setItem('tour-seen:admin','1');localStorage.setItem('tour-seen:local','1');});const p=await c.newPage();p.setDefaultTimeout(15000);const errors=[];p.on('pageerror',e=>errors.push(e.message));p.on('console',m=>{if(m.type()==='error')errors.push(m.text());});
 await p.goto('http://127.0.0.1:3050/?nointro#/settings');await p.getByRole('tab',{name:'Providers',exact:true}).click();await p.getByText('z-ai/glm-5.3-flash',{exact:true}).waitFor();
 const before=await p.evaluate(async()=>{const r=await fetch('http://127.0.0.1:8031/settings/toggles');return (await r.json()).toggles.find(x=>x.name==='openrouter');});
 const toggle=p.getByRole('switch',{name:'Use OpenRouter',exact:true});await toggle.scrollIntoViewIfNeeded();await toggle.click();console.log(JSON.stringify({width,step:'toggle clicked'}));await p.waitForFunction(async()=>{const r=await fetch('http://127.0.0.1:8031/health');return !(await r.json()).text_active;},null,{timeout:10000});await toggle.click();console.log(JSON.stringify({width,step:'toggle clicked'}));await p.waitForFunction(async()=>{const r=await fetch('http://127.0.0.1:8031/health');return (await r.json()).text_active;},null,{timeout:10000});
 await p.screenshot({path:`/private/tmp/growit-acceptance/${width}-glm-settings.png`,fullPage:true});rows.push({width,before,errors,overflow:await p.evaluate(()=>document.documentElement.scrollWidth>innerWidth)});await c.close();
}
await b.close();await writeFile('/private/tmp/growit-acceptance/glm-settings.json',JSON.stringify(rows,null,2));console.log(JSON.stringify(rows));
