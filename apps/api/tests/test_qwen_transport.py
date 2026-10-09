"""Shared text facade: Qwen only, provider gates, cache isolation and no media fallback."""
import asyncio
import httpx
import pytest
from app.agnes import AgnesError, AgnesNotConfigured
from app.config import TEXT_MODEL
from b_helpers import make_client


def test_shared_text_routes_to_fixed_qwen_and_cache_is_provider_qualified(tmp_path,monkeypatch):
    import app.agnes as transport
    app,_=make_client(tmp_path)
    monkeypatch.setenv("OPENROUTER_API_KEY","test-key")
    monkeypatch.setenv("GROQ_CHAT_MODEL","unapproved-model")
    calls=[]
    class Client:
        def __init__(self,**kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self,*args): pass
        async def post(self,url,**kwargs):
            calls.append((url,kwargs))
            return httpx.Response(200,json={"choices":[{"message":{"content":"Provider-backed answer"}}]})
    monkeypatch.setattr(transport.httpx,"AsyncClient",Client)
    messages=[{"role":"user","content":"Explain this offer"}]
    result=asyncio.run(app.state.agnes.chat(messages,cache_kind="copy"))
    assert result=="Provider-backed answer"
    assert calls[0][0]=="https://openrouter.ai/api/v1/chat/completions"
    assert calls[0][1]["json"]["model"]==TEXT_MODEL=="z-ai/glm-5.3-flash"
    assert calls[0][1]["json"]["provider"] == {"require_parameters": True}
    assert calls[0][1]["json"]["reasoning"] == {"effort": "low", "exclude": True}
    assert asyncio.run(app.state.agnes.chat(messages,cache_kind="copy"))==result and len(calls)==1
    app.state.db.execute("INSERT INTO service_toggle (name,enabled,updated_at) VALUES ('openrouter',0,'test')")
    with pytest.raises(AgnesNotConfigured):
        asyncio.run(app.state.agnes.chat(messages,cache_kind="copy"))
    assert len(calls)==1


def test_shared_text_errors_do_not_call_another_provider(tmp_path,monkeypatch):
    import app.agnes as transport
    app,_=make_client(tmp_path)
    monkeypatch.setenv("OPENROUTER_API_KEY","test-key")
    calls=[]
    class Client:
        def __init__(self,**kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self,*args): pass
        async def post(self,url,**kwargs):
            calls.append(url)
            return httpx.Response(429)
    monkeypatch.setattr(transport.httpx,"AsyncClient",Client)
    with pytest.raises(AgnesError):
        asyncio.run(app.state.agnes.chat([{"role":"user","content":"Help"}],cache_kind="copy"))
    assert calls==["https://openrouter.ai/api/v1/chat/completions"]

@pytest.mark.parametrize("kind", ["image", "video"])
def test_text_swap_never_rewrites_agnes_media_transport(tmp_path, monkeypatch, kind):
    import app.agnes as transport
    from app.config import IMAGE_MODEL, VIDEO_MODEL
    app, _ = make_client(tmp_path)
    calls = []
    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, url, **kwargs):
            calls.append((url, kwargs))
            return httpx.Response(200, json={})
    monkeypatch.setattr(transport.httpx, "AsyncClient", Client)
    call = app.state.agnes.image("filter coffee") if kind == "image" else app.state.agnes.video("filter coffee")
    asyncio.run(call)
    url, request = calls[0]
    assert url.startswith(app.state.settings.agnes_base_url)
    assert request["json"]["model"] == (IMAGE_MODEL if kind == "image" else VIDEO_MODEL)
    assert "provider" not in request["json"] and "reasoning" not in request["json"]
