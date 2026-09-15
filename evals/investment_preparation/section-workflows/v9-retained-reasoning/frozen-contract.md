# Qwen3.5 continuation fix: frozen complete-pack test

Use the exact company input, prompts, schemas, model and 512-token analysis/review budgets from v9-bounded-reasoning. The sole inference change is retaining think=True on the Qwen3.5 answer-continuation request. The installed Ollama version is 0.33.3. Its native renderer extracts and discards a tagged assistant reasoning block with think=False (model/renderers/qwen35.go lines 277-287); the parser recognizes the final assistant prefill and collects answer content despite think=True (model/parsers/qwen35.go lines 62-69). No private reasoning is stored or published.

Maximum 120 seconds, six logical calls and ten HTTP requests including bounded corrections. Same original five source-checked paraphrases; no reference answer or saved company analysis supplied. Complete nine-section output still requires a separate content audit. Preserve all previous results. No live Store updates, paid calls or downloads.

Primary runtime sources:
- https://github.com/ollama/ollama/blob/v0.33.3/model/renderers/qwen35.go#L277-L287
- https://github.com/ollama/ollama/blob/v0.33.3/model/parsers/qwen35.go#L62-L69
