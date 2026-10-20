# WS-B local runtime slice

Synthetic offline qualification: `python -m pytest -q tests/runtime` — 22 passed.
No model inference, network calls, downloads, runtime restarts or delivery integration.

Implemented an injectable OpenAI-compatible transport interface, loopback-literal
HTTP endpoint gate, eight narrow role allowlists/prompts, cumulative six-call /
120-second pass limits, token accounting, exact response and tool-observation JSONL,
private checkpoint files, in-flight replay rejection and a dependency task ledger.
Private trajectories must remain in approved private run directories, outside Git.

Limitations: transport/tool timeout enforcement requires a separately qualified
implementation; injected callables cannot be preempted by this synchronous loop.
A single-attempt stdlib local HTTP adapter is now included and tested with fake sockets.
No full team orchestrator, production hook, model baseline,
financial validation or investor acceptance is claimed. Checkpoints record pass
state, but successful/failed runs are terminal and cannot be resumed as new calls.
Taskboard is an isolated primitive, not yet a persisted multi-worker coordinator.
Market role deliberately lacks external network tools in this fully local slice.

Transport rejects redirects, DNS names, remote addresses, invalid/oversized JSON,
nonfinite constants, duplicate JSON keys and malformed completion envelopes. It
uses no environment proxy configuration. Socket deadlines are cooperative, not
hard process cancellation. Checkpoints bind endpoint, model, budgets, role prompts,
allowlists and tool schemas; in-flight calls are terminal and never replayed.

Duplicate tool-call IDs are rejected across responses and within each batch,
before executing duplicate effects. IDs are reserved in private checkpoints before
tool invocation. Crash-uncertain intents remain inflight and cannot be replayed.

## Gate 1 receipt checkpoint — 16 October 2026

35 offline synthetic tests passed. Concrete local HTTP transport exposes a receipt
hook; runtime writes exact request/response body bytes with SHA-256 and exclusive
private manifests before parsing or model-directed tool effects. The checkpoint
binds receipts to endpoint/model/configuration, call number and request digest.
Loading detects body/manifest tampering. These are local integrity receipts, not
remote authenticity or full TLS/TCP packet captures. Injected dict transports
explicitly log raw_capture=false and claim no raw HTTP provenance.

Missing terminal finish reason, length/content-filter truncation, returned model
mismatch and missing schema-validator callbacks all fail before tool execution or
final draft acceptance. Registry validate(arguments) callbacks are mandatory and
must perform side-effect-free strict validation; tool call wrappers validate again.
Malformed received bytes are retained before parser rejection. Oversized bodies
are marked incomplete; socket/network interruption may leave only a request
receipt. Such calls remain failed/uncertain and cannot replay. Existing cumulative
six-call/120-second bounds remain; no hard process cancellation is claimed.

No inference, network, private company input, production integration or investment
acceptance was used in this checkpoint.

Terminal acceptance follow-up: 47 offline tests passed. Empty, whitespace or
non-string final content fails before human review. Injected transport tool-call
envelopes require bounded lists, explicit function type, string IDs/names/JSON
arguments. Invalid terminal content preserves exact HTTP receipts and a failure
trajectory event. This adds structural checks, not semantic draft acceptance.
