import { chromium } from 'playwright';
import { writeFile } from 'node:fs/promises';
const browser=await chromium.launch({args:['--use-fake-ui-for-media-stream','--use-fake-device-for-media-stream','--autoplay-policy=no-user-gesture-required']});
const rows=[];
for(const width of [1440,390]){
 const ctx=await browser.newContext({viewport:{width,height:844},permissions:['microphone']});
 await ctx.addInitScript(()=>{localStorage.setItem('growit-signed-in',JSON.stringify({email:'admin',name:'admin',sub:'admin',at:0}));localStorage.setItem('tour-seen:admin','1');localStorage.setItem('tour-seen:local','1');});
 const p=await ctx.newPage();const errors=[];const tokens=[];p.on('pageerror',e=>errors.push(e.message));p.on('console',m=>{if(m.type()==='error')errors.push(m.text());});p.on('response',r=>{if(r.url().includes('/voice/token'))tokens.push(r.status());});
 await p.goto('http://127.0.0.1:3050/?nointro#/voice');
 let live=false;try{await p.getByRole('button',{name:'Mute microphone',exact:true}).waitFor({timeout:30000});live=true;}catch{}
 await p.waitForTimeout(12000);
 const buttons=await p.getByRole('button').allTextContents();
 const mute=p.getByRole('button',{name:'Mute microphone',exact:true});
 if(live){await mute.click();await p.getByRole('button',{name:'Unmute microphone',exact:true}).click();await p.getByRole('button',{name:'Pause the call',exact:true}).click();await p.getByRole('button',{name:'Resume the call',exact:true}).click();}
 await p.screenshot({path:`/private/tmp/growit-acceptance/${width}-agnez.png`,fullPage:true});
 if(live){await p.getByRole('button',{name:'End call',exact:true}).click();await p.waitForTimeout(1500);}
 rows.push({width,live,tokens,errors,buttons,alerts:await p.getByRole('alert').allTextContents(),statuses:await p.getByRole('status').allTextContents(),overflow:await p.evaluate(()=>document.documentElement.scrollWidth>innerWidth)});await ctx.close();
}
await browser.close();await writeFile('/private/tmp/growit-acceptance/agnez.json',JSON.stringify(rows,null,2));console.log(JSON.stringify(rows));
