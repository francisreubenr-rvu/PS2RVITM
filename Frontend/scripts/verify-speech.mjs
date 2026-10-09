import { chromium } from 'playwright';
import { writeFile } from 'node:fs/promises';
const source=process.env.SPEECH_AUDIO_PATH;
if (!source) throw new Error('Set SPEECH_AUDIO_PATH to a WAV recording of real source content.');
const browser=await chromium.launch({args:['--use-fake-ui-for-media-stream','--use-fake-device-for-media-stream',`--use-file-for-fake-audio-capture=${source}`,'--autoplay-policy=no-user-gesture-required']});
const rows=[];
for(const width of [1440,390]){
 const ctx=await browser.newContext({viewport:{width,height:844},permissions:['microphone']});
 await ctx.addInitScript(()=>{try{localStorage.setItem('growit-signed-in',JSON.stringify({email:'admin',name:'admin',sub:'admin',at:0}));localStorage.setItem('tour-seen:admin','1');localStorage.setItem('tour-seen:local','1');}catch{}});
 const p=await ctx.newPage();const errors=[];const status=[];p.on('pageerror',e=>errors.push(e.message));p.on('response',r=>{if(r.url().includes('/voice/token'))status.push(r.status());});
 await p.goto('http://127.0.0.1:3050/?nointro#/brand');await p.getByRole('button',{name:'Speak what to picture',exact:true}).waitFor();
 await p.getByRole('button',{name:'Speak what to picture',exact:true}).click();
 let heard='';try{await p.waitForFunction(()=>[...document.querySelectorAll('input')].some(i=>i.placeholder==='Filter coffee'&&i.value.toLowerCase().includes('coffee')),{},{timeout:30000});heard=await p.getByPlaceholder('Filter coffee',{exact:true}).inputValue();}catch{}
 rows.push({width,status,heard,errors,alerts:await p.getByRole('alert').allTextContents()});
 await p.screenshot({path:`/private/tmp/growit-acceptance/${width}-dictation.png`,fullPage:true});await ctx.close();
}
await browser.close();await writeFile('/private/tmp/growit-acceptance/speech.json',JSON.stringify(rows,null,2));console.log(JSON.stringify(rows));
