# V9 raw continuation and bounded field repair

Same original five Paasa source records. No reference answer, prior company output or model download. Qwen3.5:9b; 512 reasoning tokens each for analysis and review, fast founder writing and targeted field corrections. Total 120 seconds, six logical calls, ten raw requests.

After thinking, Qwen3.5 now uses raw ChatML completion through /api/generate with raw=True and think=False. This preserves the closed reasoning block without passing through the native chat renderer, while keeping JSON-schema decoding active. The prompt uses the installed renderer's text-only system/user/assistant format. No private reasoning is persisted. Missing fields are repaired individually rather than rewriting the full analysis; those corrections use the fast route.

Full nine-section acceptance remains unchanged: a separate audit must find source-faithful business and revenue explanations, a conditional commercial case, a real risk, a concrete outside-adviser offer, and coherent linked record requests and analyses. No fabricated results, unsupported revenue ownership or causal claims. Preserve all original failed reports. Live data remain untouched.

Primary API contract: https://docs.ollama.com/api/generate
Qwen reference protocol: https://github.com/QwenLM/Qwen3/blob/main/docs/source/getting_started/thinking_budget.md
