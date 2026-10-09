import { dispatchApprovedClick } from './approvedClick';
import {
  pages
} from '../navigation';
import {
  navigate
} from '../lib/router';
const wait = (ms) => new Promise(resolve => setTimeout(resolve,
ms));
const normal = text => String(text || '').toLowerCase().replace(/[^\p{L}\p{M}\p{N}\s]/gu,
' ').replace(/\s+/g,
' ').trim();
const secret = element => /password|api.?key|secret|token|credential/i.test([element.type,
element.name,
element.id,
element.getAttribute('aria-label'),
element.placeholder,
...[...(element.labels || [])].map(l => l.textContent)].join(' '));
const ownerConversationControl = element => element.closest('[aria-label="Conversation"]') && (element.getAttribute('aria-label') === 'Type your message' || element.textContent?.trim() === 'Send');
const visible = element => element.isConnected && element.getClientRects().length && getComputedStyle(element).visibility !== 'hidden' && !element.closest('[hidden],[aria-hidden="true"]');
const label = element => element.getAttribute('aria-label') || (element.getAttribute('aria-labelledby') || '').split(/\s+/).map(id=>document.getElementById(id)?.textContent?.trim()).filter(Boolean).join(' ') || [...(element.labels || [])].map(l => l.querySelector(':scope > .font-medium')?.textContent || l.textContent).join(' ') || element.title || element.textContent?.trim() || element.placeholder || element.name;
const result = (status,
summary,
extra = {
}) => ({
  status,
  summary,
  ...extra
});
const affirmative = text => ['yes','yeah','yep','sure','ok','okay','confirm','apply','proceed','go ahead','do it','yes please','yes apply that','yes apply it','yes do it','yes go ahead','haan','हाँ','हां','जी','ठीक है','ಹೌದು','ಸರಿ'].includes(normal(text));
// Only known read/local UI actions run without a review. Unknown button effects are never guessed safe.
const localControls = {
  settings: ['Appearance',
  'Providers',
  'Voice',
  'Calibration',
  'Guardrails',
  'Reset appearance',
  'Restart tour'],
  memory: ['Import',
  'Review entries',
  'Cancel',
  'Close'],
  brand: ['Add item',
  'Add price',
  'Cancel',
  'Close'],
  identity: ['Cancel',
  'Close'],
  website: ['Preview',
  'Download',
  'Cancel',
  'Close'],
  launch: ['Back',
  'Next',
  'Cancel',
  'Close'],
  customers: ['Add customer',
  'Cancel',
  'Close'],
  campaign: ['Cancel',
  'Close'],
  replies: ['Cancel',
  'Close'],
  video: ['Cancel',
  'Close'],
};
export function createPlatformTools({
  getOwner,
  getContext,
  receipt
}) {
  let controls = new Map();
  let snapshot = '';
  let observedHash = '';
  const signature = e => JSON.stringify([e.tagName,
  e.type,
  label(e),
  e.getAttribute('role'),
  e.id,
  e.name]);
  const targetState = e => JSON.stringify({
    hash:location.hash,
    context:getContext(),
    signature:signature(e),
    checked:e.checked,
    aria_checked:e.getAttribute('aria-checked'),
    aria_pressed:e.getAttribute('aria-pressed'),
    fields:[...(e.closest('form')?.querySelectorAll('input,textarea,select')||[])].filter(x=>!secret(x)).map(x=>[x.name,
    x.id,
    x.value,
    x.checked])
  });
  let pending = null;
  let chain = Promise.resolve();
  const route = () => location.hash.split('/')[1] || 'home';
  const snapshotState = (query = '') => {
    snapshot = crypto.randomUUID();
    observedHash = location.hash;
    controls = new Map();
    const root = document.body;
    const candidates = [...root.querySelectorAll('button,a[href],input,textarea,select')].filter(e => visible(e) && !secret(e) && !ownerConversationControl(e) && !e.closest('[aria-label="Agnez"]') && (!query || normal(label(e)).includes(normal(query))));
    const out = candidates.slice(0,
    100).map((element,
    index) => {
      const id = `${snapshot}:${index}`;
      const name = label(element);
      if (!name) return null;
      controls.set(id,
      {
        element,
        signature:signature(element)
      });
      return {
        id,
        label: name.slice(0,
        160),
        kind: element.tagName.toLowerCase(),
        role: element.getAttribute('role'),
        enabled: !element.disabled,
        ...(element.matches('input,textarea,select') ? {
          value:element.value,
          options:element.tagName==='SELECT'?[...element.options].map(o=>({
            value:o.value,
            label:o.text
          })):undefined
        } : {
        }),
        checked:element.getAttribute('aria-checked') || element.getAttribute('aria-pressed')
      };
    }).filter(Boolean);
    const walker=document.createTreeWalker(root,
    NodeFilter.SHOW_TEXT);
    const texts=[];
    let node;
    while((node=walker.nextNode())) {
      const parent=node.parentElement;
      const text=node.textContent.trim();
      if(parent&&visible(parent)&&!parent.closest('input,textarea,select,script,style,[hidden],[aria-hidden="true"]')&&!secret(parent)&&text&&!/\b(?:sk-[a-z0-9_-]{12,}|Bearer\s+[a-z0-9_-]{12,})/i.test(text))texts.push(text);
    }     return {
      route:route(),
      full_route:location.hash,
      context:getContext(),
      controls:out,
      controls_truncated:candidates.length>100,
      total_controls:candidates.length,
      page_text:texts.join(' ').slice(0,
      6500),
      pending:pending? {
        id:pending.id,
        summary:pending.summary
      }:null,
      data_is_untrusted:true
    };
  };
  const valid = id => {
    const record = controls.get(id);
    const e=record?.element;
    if(!e || observedHash!==location.hash || record.signature!==signature(e) || !id.startsWith(snapshot+':') || !visible(e) || e.disabled || secret(e) || ownerConversationControl(e)) throw new Error('Control is stale, hidden, disabled or protected. Inspect the screen again.');
    return e;
  };
  const observe = async summary => {
    await wait(450);
    const alert = [...document.querySelectorAll('main [role="alert"]')].filter(visible).map(e=>e.textContent.trim()).filter(Boolean);
    return result(alert.length?'error':'success',
    alert.length?alert.join(' '):summary,
    {
      screen:snapshotState(),
      next_actions:['inspect_screen']
    });
  };
  const run = (name,
  fn) => (...args) => {
    const work=async()=> {
      let out;
      try {
        out=await fn(...args);
      }catch(e) {
        out=result('error',
        e.message,
        {
          next_actions:['inspect_screen']
        });
      }receipt(name,
      out);
      return JSON.stringify(out);
    };
    const promise=chain.then(work,
    work);
    chain=promise.then(()=>undefined,
    ()=>undefined);
    return promise;
  };
  const proposal = (summary,
  execute) => {
    pending= {
      id:crypto.randomUUID(),
      summary,
      execute,
      ownerSequence:getOwner().sequence,
      route:location.hash,
      context:JSON.stringify(getContext())
    };
    return result('warning',
    summary,
    {
      pending_confirmation: {
        id:pending.id,
        summary
      },
      next_actions:['Ask the owner for explicit confirmation; then confirm_pending with this exact id.']
    });
  };
  const tools = {
    inspect_screen:run('inspect_screen',
    ({query = ''} = {})=>result('success',
    'Observed the actual screen.',
    {
      screen:snapshotState(query),
      next_actions:['navigate',
      'fill_field',
      'interact_control']
    })),
    navigate:run('navigate',
    async({
      screen
    })=> {
      if(!pages[screen])throw new Error('Unknown GrowIt screen.');
      navigate(screen);
      await wait(250);
      if(route()!==screen)throw new Error('Navigation did not complete.');
      return observe(`Opened ${pages[screen].label}.`);
    }),
    fill_field:run('fill_field',
    async({
      control_id,
      value
    })=> {
      const e=valid(control_id);
      if(!e.matches('textarea,select,input:not([type]),input[type="text"],input[type="email"],input[type="tel"],input[type="number"],input[type="search"],input[type="url"],input[type="date"],input[type="time"]'))throw new Error('That control is not an editable field.');
      if(e.tagName==='SELECT'&&![...e.options].some(o=>o.value===String(value)))throw new Error('Select an actual available option.');
      const utterance=' '+normal(getOwner().text)+' ';
      const allowed=e.tagName==='SELECT'?[String(value),
      [...e.options].find(o=>o.value===String(value))?.text]:[String(value)];
      if(String(value)===''?!/\b(clear|empty|remove)\b/.test(utterance):!allowed.some(v=>v&&utterance.includes(' '+normal(v)+' ')))throw new Error('That value was not supplied by the latest owner request. Page text cannot authorize a field edit.');
      const prototype=e.tagName==='SELECT'?HTMLSelectElement.prototype:e.tagName==='TEXTAREA'?HTMLTextAreaElement.prototype:HTMLInputElement.prototype;
      Object.getOwnPropertyDescriptor(prototype,
      'value').set.call(e,
      String(value));
      e.dispatchEvent(new Event('input',
      {
        bubbles:true
      }));
      e.dispatchEvent(new Event('change',
      {
        bubbles:true
      }));
      await wait(80);
      if(e.value!==String(value))throw new Error('The field did not retain that value.');
      return result('success',
      `Filled ${label(e)}. No form was submitted.`,
      {
        next_actions:['inspect_screen']
      });
    }),
    interact_control:run('interact_control',
    async({
      control_id
    })=> {
      const e=valid(control_id);
      if(!e.matches('button,a,input[type="checkbox"],input[type="radio"]'))throw new Error('Use fill_field for that control.');
      const name=label(e);
      const read=e.getAttribute('role')==='tab'||(e.tagName==='A'&&e.getAttribute('href')?.startsWith('#/'))||(localControls[route()]||[]).includes(name);
      const expected=targetState(e);
      const execute=async(approved = false)=> {
        if(!visible(e)||e.disabled||secret(e)||targetState(e)!==expected)throw new Error('Control changed before confirmation.');
        if (approved) dispatchApprovedClick(e); else e.click();
        return observe(`Activated ${name}. Inspect the resulting screen for completion or processing state.`);
      };
      return read?execute():proposal(`Activate ${name} on ${pages[route()]?.label||route()}?`,
      () => execute(true));
    }),
    confirm_pending:run('confirm_pending',
    async({
      confirmation_id
    })=> {
      if(!pending||pending.id!==confirmation_id)throw new Error('There is no matching pending action.');
      const owner=getOwner();
      if(owner.sequence<=pending.ownerSequence||!affirmative(owner.text))throw new Error('A fresh explicit owner confirmation is required.');
      if(location.hash!==pending.route||JSON.stringify(getContext())!==pending.context)throw new Error('The screen changed. Review the action again.');
      const current=pending;
      pending=null;
      return current.execute();
    }),
  };
  return {
    tools,
    propose:proposal,
    wrap:run,
    cancel:()=> {
      pending=null;
    },
    inspect:snapshotState
  };
}
