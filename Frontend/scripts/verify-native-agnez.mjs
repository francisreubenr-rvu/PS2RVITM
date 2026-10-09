import {chromium} from 'playwright';import{readFile,writeFile}from'node:fs/promises';
const b=await chromium.launch({args:['--use-fake-ui-for-media-stream','--use-fake-device-for-media-stream','--autoplay-policy=no-user-gesture-required']});const rows=[];
for(const width of [1440,390]){
 const c=await b.newContext({viewport:{width,height:900},permissions:['microphone']});await c.addInitScript(()=>{
  localStorage.setItem('growit-signed-in',JSON.stringify({email:'admin',name:'admin',sub:'admin',at:0}));localStorage.setItem('tour-seen:admin','1');localStorage.setItem('tour-seen:local','1');localStorage.setItem('talk-lang','en');
  const context=new AudioContext();const destination=context.createMediaStreamDestination();navigator.mediaDevices.getUserMedia=async()=>{await context.resume();return destination.stream.clone();};window.replaySpeech=async encoded=>{const data=Uint8Array.from(atob(encoded),c=>c.charCodeAt(0));const buffer=await context.decodeAudioData(data.buffer);const source=context.createBufferSource();source.buffer=buffer;source.connect(destination);source.start();return buffer.duration;};
 });const p=await c.newPage();p.setDefaultTimeout(25000);const errors=[],tokens=[],answers=[],tools=[];p.on('pageerror',e=>errors.push(e.message));p.on('response',async r=>{if(r.url().includes('/voice/token'))tokens.push(r.status());if(/\/interview\/[^/]+\/answer$/.test(r.url()))answers.push({status:r.status(),body:await r.json()});});
 try{console.log(JSON.stringify({width,step:'starting'}));await p.goto('http://127.0.0.1:3050/?nointro#/voice');await p.getByRole('button',{name:'End call',exact:true}).waitFor();await p.waitForTimeout(6500);
 const send=async text=>{if(!await p.getByLabel('Type your message',{exact:true}).isVisible())await p.getByRole('button',{name:'Type instead',exact:true}).click();await p.getByLabel('Type your message',{exact:true}).fill(text);await p.getByRole('button',{name:'Send',exact:true}).click();};
 await send('Start a new campaign.');await p.waitForFunction(()=>document.body.textContent.includes('What is your business called?'),null,{timeout:25000});await p.waitForTimeout(3500);
 const waitQuestion=field=>p.waitForFunction(async field=>{const id=location.hash.split('/')[2];if(!id)return false;const response=await fetch('http://127.0.0.1:8031/interview/'+id);const data=await response.json();return data.question?.field===field;},field,{timeout:25000});
 const speak=async file=>{await p.evaluate(encoded=>window.replaySpeech(encoded),(await readFile(file)).toString('base64'));};
 console.log(JSON.stringify({width,step:'name audio',tracks:await p.evaluate(()=>({state:document.querySelector('audio')?.srcObject?.getAudioTracks()?.[0]?.readyState}))}));await speak('/private/tmp/growit-starbucks.wav');await waitQuestion('business_type');await p.waitForTimeout(5000);
 const beforeRepeat=answers.length;await speak('/private/tmp/growit-repeat.wav');await p.waitForTimeout(10000);const repeatDidNotSubmit=answers.length===beforeRepeat;
 await speak('/private/tmp/growit-cafe.wav');await waitQuestion('area');await p.waitForTimeout(5000);
 await speak('/private/tmp/growit-bangalore.wav');await waitQuestion('goal');await p.waitForTimeout(6000);
 const current=answers.at(-1)?.body;const interview={id:current?.id,fields:current?.fields,question:current?.question,clarify:current?.clarify};
 await send('Open Settings.');await p.waitForURL('**#/settings',{timeout:25000});
 // Use the persistent dock conversation: opening Talk briefly preserves the same provider session.
 await p.getByRole('button',{name:'Open the full conversation',exact:true}).click();await p.waitForURL('**#/voice');await send('Open Memory.');await p.waitForURL('**#/memory',{timeout:25000});
 await p.screenshot({path:`/private/tmp/growit-acceptance/${width}-native-agnez.png`,fullPage:true});
 rows.push({width,tokens,errors,repeatDidNotSubmit,interview,route:await p.evaluate(()=>location.hash),overflow:await p.evaluate(()=>document.documentElement.scrollWidth>innerWidth)});
 await p.getByRole('button',{name:'End',exact:true}).click();console.log(JSON.stringify({width,completed:true}));}catch(error){rows.push({width,error:error.message,errors,answers,body:await p.locator('body').innerText()});await p.screenshot({path:`/private/tmp/growit-acceptance/${width}-native-failure.png`,fullPage:true});console.log(JSON.stringify({width,error:error.message}));}finally{await c.close();await writeFile('/private/tmp/growit-acceptance/native-agnez.json',JSON.stringify(rows,null,2));}
}
await b.close();await writeFile('/private/tmp/growit-acceptance/native-agnez.json',JSON.stringify(rows,null,2));console.log(JSON.stringify(rows));
