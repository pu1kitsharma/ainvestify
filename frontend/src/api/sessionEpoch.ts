// Memory-only request ownership. No identity, credential or private payload is stored.
let generation = 0;
let ready = false;
const pending = new Set<AbortController>();

export class SessionChangedError extends Error {
  constructor() { super('The account session changed.'); this.name = 'AbortError'; }
}

export function suspendPrivateRequests() {
  generation += 1;
  ready = false;
  for (const controller of pending) controller.abort();
  pending.clear();
}

export function allowPrivateRequests() { ready = true; }

export function privateRequestScope() {
  if (!ready) throw new SessionChangedError();
  const started = generation;
  const controller = new AbortController();
  pending.add(controller);
  return {
    signal: controller.signal,
    assertCurrent() { if (!ready || started !== generation) throw new SessionChangedError(); },
    finish() { pending.delete(controller); },
  };
}
