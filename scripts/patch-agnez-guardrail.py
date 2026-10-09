"""Remove the evidenced ordinary-command false-positive terminator only."""
import copy,json,os,sys
from pathlib import Path
import httpx
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'apps/api'))
from app import config
from app.lab.voice import elevenlabs as e
with httpx.Client(headers={'xi-api-key':e.api_key()},timeout=30) as client:
 url=e.BASE+'/convai/agents/'+e.agent_id();response=client.get(url);response.raise_for_status();before=response.json()
 snapshot=Path('/private/tmp/growit-agnez-guardrail-before.json')
 if not snapshot.exists():
  fd=os.open(snapshot,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
  with os.fdopen(fd,'w') as out:json.dump(before,out)
 guards=copy.deepcopy(before['platform_settings']['guardrails']);guards['prompt_injection']['is_enabled']=False
 response=client.patch(url,json={'platform_settings':{'guardrails':guards}});response.raise_for_status();after=client.get(url);after.raise_for_status();after=after.json()
 expected=copy.deepcopy(before['platform_settings']);expected['guardrails']=guards
 assert after['platform_settings']==expected
 assert after['conversation_config']==before['conversation_config']
 assert after['workflow']==before['workflow']
 print(json.dumps({'prompt_injection_terminator_disabled':True,'focus_content_voice_asr_tools_permissions_preserved':True}))
