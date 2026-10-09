# Proposed reasoning model swap

This is a historical comparison checked 2026-10-10 before the user selected the GLM experiment. It does not describe the active model configuration. GLM 5.3 Flash on OpenRouter is now active. See [progress.md](../progress.md) for the measured live result.

| Area | Qwen on Groq at comparison time | DeepSeek on OpenRouter considered then | Expected GrowIt effect at that time |
|---|---|---|---|
| Input/output per million tokens | $0.80 / $4.00 | $0.2156 / $0.6468 promotional DeepInfra; $0.44 / $1.32 other providers | Promotional rates are about 73% / 84% lower; standard rates about 45% / 67% lower |
| Context / maximum output | 131,042 / 16,384 tokens | 1,048,576 / 262,144 tokens | More source material can fit, but current prompts must actually supply it |
| Published speed | 450+ tokens/s advertised | Provider listings report about 50 to 94 tokens/s | Voice followups and generation may take longer; no app benchmark run |
| Tools / structured output / images | Supported | Supported | Existing text routes still need real saved-case regression checks; vision needs image input plumbing |
| Integration | Groq key and URL | OpenRouter or another compatible provider route | URL, key, model and capability validation required, not just a model string edit |

At comparison time, GrowIt used Groq for those text routes. They now use the single `z-ai/glm-5.3-flash` model through OpenRouter. The DeepSeek route was not integrated or benchmarked in GrowIt. ElevenLabs speech and Agnes media generation remain separate integrations.

The exact experimental ID is listed by OpenRouter. Official DeepSeek has retired its older experimental ID in favour of V4.1 Flash via deepseek-flash, which is a different route. Official cache-miss rates are $0.15 / $0.60 off-peak and $0.30 / $1.20 peak; those rates should not be substituted for the requested OpenRouter route.

Sources: [Groq model documentation](https://console.groq.com/docs/model/qwen/qwen3.8-27b), [requested OpenRouter model](https://openrouter.ai/deepseek/deepseek-v4-flash-vision-exp), [official DeepSeek pricing and model routing](https://api-docs.deepseek.com/quick_start/pricing/).
