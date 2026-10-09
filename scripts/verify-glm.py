"""Bounded read-only live GLM experiment against existing GrowIt data."""
import json
import time
from pathlib import Path
import httpx

base = 'http://127.0.0.1:8031'
rows = []
with httpx.Client(base_url=base, timeout=90) as client:
    health = client.get('/health').json()
    assert health['text_model'] == 'z-ai/glm-5.3-flash' and health['text_provider'] == 'openrouter' and health['text_active']
    providers = client.get('/settings/providers').json()['providers']
    text = next(row for row in providers if row['capability'] == 'text')
    assert text['provider'] == 'openrouter' and text['model'] == health['text_model'] and text['active']
    source = next(item for item in client.get('/memory').json()['items'] if item['status'] == 'active' and item['body'])
    for path, body in [('/agent/orchestrate', {'utterance': 'Open Memory', 'state': {'screen': 'agent'}}),
                       ('/talk/chat', {'messages': [{'role': 'user', 'content': 'Open Memory'}], 'lang': 'en'}),
                       ('/memory/import/preview', {'text': source['body'], 'tidy': True})]:
        start = time.monotonic()
        response = client.post(path, json=body)
        result = response.json()
        rows.append({'route': path, 'status': response.status_code, 'seconds': round(time.monotonic()-start, 2), 'result': result})
        if response.status_code != 200:
            break
Path('/private/tmp/growit-acceptance/glm-experiment.json').write_text(json.dumps({'health': health, 'text_provider': text, 'source_id': source['id'], 'calls': rows}, ensure_ascii=False, indent=2))
print(json.dumps(rows, ensure_ascii=False))
