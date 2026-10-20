# H2: GPU-machine readiness (Phase A, offline, 20 October 2026)

Code and docs only. No model was run, nothing downloaded, no cloud command executed, no commit. Closes the G-READY gaps
"vLLM/OpenAI-compatible client not wired" and "held-out/probe generator is MLX-only"; adds Linux sandbox backends.

| Item | Where |
|---|---|
| Self-hosted OpenAI-compatible client + runtime transport (private hosts only, bearer token, guided decoding, tool calls, receipts, InfraFault/ModelFault) | `agents/inference/selfhosted_client.py` |
| Transport factory (Ollama default unchanged) | `agents/runtime/transport.py::make_transport` |
| Additive runtime edits (transport may supply its own endpoint validator; default loopback validation unchanged) | `agents/runtime/loop.py` (2 lines), `agents/runtime/banker_session.py` (1 line) |
| GPU batch generators, LoRA by model name, runtime adapter loading, sampler, probe hook, bake-off / round / probe CLI, vLLM pause-around-training wrapper | `training/gpu_generate.py` |
| Pre-flight (read-only) | `scripts/gpu_preflight.py` |
| Linux sandbox (bubblewrap), LibreOffice discovery | `delivery/isolation.py`, `delivery/libreoffice.py`, `agents/tools/recalc.py` |
| Requirements and step-by-step setup, memory table | `requirements-gpu.txt`, `deployment/GPU_MACHINE_SETUP.md` |
| Tests (fake sockets + stdlib fake OpenAI server on loopback; fakes for nvidia-smi/torch/bwrap) | `tests/selfhosted/`, `tests/gpu_ready/` |

Run: `.venv/bin/python -m pytest tests/selfhosted tests/gpu_ready tests/runtime tests/tools tests/gpu tests/inference tests/delivery tests/training -q`

Decisions worth knowing
- The runtime's loopback-only `validate_endpoint` is bypassed only when the injected transport exposes its own
  `validate_endpoint`; `SelfHostedTransport` accepts exactly the endpoint of its already-validated route. A plain transport still
  cannot talk to a private address (tested).
- `finish_reason=length` is a `ModelFault` for the agent runtime but accepted by batch generators (`allow_length=True`), where
  truncation by `max_tokens` is expected.
- The Linux sandbox refuses `local_model=True` instead of sharing the host network namespace.
- Training and vLLM contend for GPU memory; `ServingPausedBackend` stops/starts serving around `QloraBackend.train`.

Unverified: see section 12 of `deployment/GPU_MACHINE_SETUP.md` (all of it needs a real Linux GPU box).
