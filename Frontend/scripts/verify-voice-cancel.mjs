import { chromium } from 'playwright';
import { writeFile } from 'node:fs/promises';
const b=await chromium.launch({args:['--use-fake-ui-for-media-stream','--use-fake-device-for-media-stream']});const rows=[];
for(const width of [1440,390]){
 const c=await b.newContext({viewport:{width,height:844},permissions:['microphone']});await c.addInitScript(()=>{localStorage.setItem('growit-signed-in',JSON.stringify({email:'admin',name:'admin',sub:'admin',at:0}));localStorage.setItem('tour-seen:admin','1');localStorage.setItem('tour-seen:local','1');});
 const p=await c.newPage();let cancelled=false;const errors=[];const connections=[];p.on('pageerror',e=>errors.push(e.message));p.on('websocket',s=>connections.push(s.url().split('?')[0]));
 await p.route('**/voice/token',async route=>{const response=await route.fetch();await new Promise(r=>setTimeout(r,1500));await route.fulfill({response});});
 await p.goto('http://127.0.0.1:3050/?nointro#/brand');await p.getByRole('button',{name:'Speak what to picture',exact:true}).click();await p.waitForTimeout(200);await p.evaluate(()=>{location.hash='#/settings';});cancelled=true;await p.waitForTimeout(3500);
 rows.push({width,cancelled,connections,errors});await c.close();
}
await b.close();await writeFile('/private/tmp/growit-acceptance/voice-cancel.json',JSON.stringify(rows,null,2));console.log(JSON.stringify(rows));
