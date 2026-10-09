"""Patch only workflow instructions that contradict GrowIt's session modes."""
import copy
import json
import os
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'apps/api'))
from app import config
from app.lab.voice import elevenlabs

url = elevenlabs.BASE + '/convai/agents/' + elevenlabs.agent_id()
with httpx.Client(headers={'xi-api-key': elevenlabs.api_key()}, timeout=30) as client:
    response = client.get(url)
    response.raise_for_status()
    before = response.json()
    backup = Path('/private/tmp/growit-agnez-workflow-before.json')
    if not backup.exists():
        fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as out:
            json.dump(before, out)
    workflow = copy.deepcopy(before['workflow'])
    for node in workflow['nodes'].values():
        if node.get('type') == 'override_agent':
            node['additional_prompt'] = ('Follow the active session prompt exactly. Session instructions determine whether this is Talk, dictation, read-aloud or a briefing. '
                'For Talk and read-aloud, speak only text after SAY: exactly; never introduce yourself or ask personal-story questions. '
                'For dictation, remain silent and do not call tools. '
                'Only for a briefing without these modes, follow the active briefing prompt and ask one question at a time. '
                'Do not add bracketed stage directions. Never override a silent session with a greeting.')
    for edge in workflow['edges'].values():
        condition = edge.get('forward_condition', {})
        if condition.get('type') == 'llm':
            condition['condition'] = 'The active briefing prompt calls for moving to its next subject. Never transition during Talk, dictation or read-aloud.'
    if workflow != before['workflow']:
        response = client.patch(url, json={'workflow': workflow})
        response.raise_for_status()
    response = client.get(url)
    response.raise_for_status()
    after = response.json()
    assert after['workflow'] == workflow
    assert after['conversation_config'] == before['conversation_config']
    assert after['platform_settings'] == before['platform_settings']
    print(json.dumps({'workflow_patched': workflow != before['workflow'], 'workflow_verified': True, 'voice_prompt_tools_and_permissions_preserved': True}))
