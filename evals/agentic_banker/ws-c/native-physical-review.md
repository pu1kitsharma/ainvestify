# Native isolation and immutable source regression — 16 October 2026

Focused result: 13 passed, 1 skipped in 1.84s. Production code is unchanged.

The actual native worker failed with exit 71 and `sandbox-exec: sandbox_apply:
Operation not permitted`. An independent minimal deny-network `/usr/bin/true`
Seatbelt policy fails the same way inside this enclosing execution sandbox.
The test now probes that separate native capability and skips only that exact
capability failure. Unexpected probe errors still fail; a malformed-profile
return-code regression proves they are not swallowed. The mandatory real native
sibling-read/write-denial check remains UNRUN and blocks security acceptance.
Run it on a qualified native host before release; this skip is not qualification.

The physical-plan mismatch was reproducible without sleeps by generating the
same synthetic PPTX with ZIP timestamps four seconds apart. The resulting source
bytes and inventory revisions differ. The test incorrectly reconstructed the old
request with the second generated inventory. It now retains the first inventory
for exact old-request equality. A regression asserts unchanged source reproduces
exactly and regenerated different source does not. No request binding, source
identity or equality validation was relaxed. The earlier unexplained-order-state
finding in offline-regression-review.md is superseded by this reproduction.
