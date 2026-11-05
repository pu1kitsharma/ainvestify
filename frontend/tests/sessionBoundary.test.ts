import assert from 'node:assert/strict';
import {afterEach, test} from 'node:test';
import {SessionBoundary, identityKey, sessionNotifications, SESSION_NOTICE_KEY} from '../src/api/sessionBoundary.ts';
import {api, setCsrfToken} from '../src/api/client.ts';
import {allowPrivateRequests, suspendPrivateRequests} from '../src/api/sessionEpoch.ts';

function makeBoundary<T extends {user_id: string; tenant_id: string; csrf_token: string}>(options: {
  readIdentity: (signal: AbortSignal) => Promise<T>; setCsrf: (value: string) => void;
  broadcast: () => void; navigate?: () => void;
}) { return new SessionBoundary({...options, navigate: options.navigate ?? (() => {})}); }

const originalFetch = globalThis.fetch;
afterEach(() => {globalThis.fetch = originalFetch; suspendPrivateRequests(); setCsrfToken('');});

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (value: unknown) => void;
  const promise = new Promise<T>((yes, no) => {resolve = yes; reject = no;});
  return {promise, resolve, reject};
}
const alice = {user_id: 'synthetic-alice', tenant_id: 'synthetic-one', csrf_token: 'synthetic-csrf-a'};
const bob = {user_id: 'synthetic-bob', tenant_id: 'synthetic-two', csrf_token: 'synthetic-csrf-b'};

test('a delayed real QueryClient query and old mutation callback cannot hydrate a new account cache', async () => {
  let identity = alice;
  const boundary = makeBoundary({readIdentity: async () => identity, setCsrf: setCsrfToken, broadcast() {}});
  boundary.activate(); await boundary.revalidate('initial');
  const old = boundary.getSnapshot().queryClient;
  const data = deferred<{private: string}>();
  const request = old.fetchQuery({queryKey: ['private-room'], queryFn: () => data.promise, retry: false});
  const settled = request.catch(() => undefined);
  identity = bob; boundary.remoteChange(); await boundary.revalidate('focus');
  const current = boundary.getSnapshot().queryClient;
  assert.notEqual(old, current);
  data.resolve({private: 'synthetic prior account bytes'}); await settled;
  // A mutation already beyond HTTP completion can still call its captured
  // QueryClient; that obsolete client is never reused by the next identity.
  old.setQueryData(['private-room'], {private: 'synthetic late callback'});
  assert.equal(current.getQueryData(['private-room']), undefined);
  assert.equal(boundary.getSnapshot().user, null);
  assert.equal(boundary.getSnapshot().checking, true);
  old.clear(); boundary.stop();
});

test('identity change clears cache and hard-navigates before installing the new identity or CSRF', async () => {
  let identity = alice, navigations = 0; const csrf: string[] = [];
  const boundary = makeBoundary({readIdentity: async () => identity, setCsrf: value => csrf.push(value), broadcast() {}, navigate() {navigations += 1;}});
  boundary.activate(); await boundary.revalidate('initial');
  const before = boundary.getSnapshot(); before.queryClient.setQueryData(['private'], 'synthetic');
  identity = bob; await boundary.revalidate('focus');
  const after = boundary.getSnapshot();
  assert.notEqual(identityKey(before.user!), identityKey(bob));
  assert.equal(after.user, null); assert.equal(after.checking, true); assert.equal(navigations, 1);
  assert.equal(csrf.includes(bob.csrf_token), false); assert.equal(csrf.at(-1), '');
  assert.notEqual(before.revision, after.revision);
  assert.equal(before.queryClient.getQueryData(['private']), undefined);
  assert.equal(after.queryClient.getQueryData(['private']), undefined);
  boundary.stop();
});

test('a delayed real mutation cannot run old UI success/error callbacks after account replacement', async () => {
  let identity = alice, callbacks = 0;
  const boundary = makeBoundary({readIdentity: async () => identity, setCsrf() {}, broadcast() {}});
  boundary.activate(); await boundary.revalidate('initial');
  const old = boundary.getSnapshot().queryClient;
  const data = deferred<string>();
  const started = deferred<void>();
  const mutation = old.getMutationCache().build(old, {
    mutationFn: () => {started.resolve(); return data.promise;},
    onSuccess: () => {callbacks += 1;}, onError: () => {callbacks += 1;}, onSettled: () => {callbacks += 1;},
  });
  const request = mutation.execute(undefined);
  await started.promise; identity = bob; boundary.remoteChange(); await boundary.revalidate('focus');
  data.resolve('synthetic previous account response'); await request;
  assert.equal(callbacks, 0); old.clear(); boundary.stop();
});

test('an old mutation still waiting for onMutate cannot start an HTTP action under the next account', async () => {
  let requests = 0;
  const boundary = makeBoundary({readIdentity: async () => alice, setCsrf() {}, broadcast() {}});
  boundary.activate(); await boundary.revalidate('initial');
  const old = boundary.getSnapshot().queryClient;
  const started = deferred<void>(), release = deferred<void>();
  const mutation = old.getMutationCache().build(old, {
    onMutate: async () => {started.resolve(); await release.promise;},
    mutationFn: async () => {requests += 1; return 'must not execute';},
  });
  const pending = mutation.execute(undefined);
  const rejected = assert.rejects(pending, error => error instanceof Error && error.name === 'AbortError');
  await started.promise; boundary.expire(); release.resolve(); await rejected;
  assert.equal(requests, 0); old.clear(); boundary.stop();
});

test('late auth/me after logout or expiry cannot restore identity or CSRF', async () => {
  const response = deferred<typeof alice>(); const csrf: string[] = [];
  const boundary = makeBoundary({readIdentity: () => response.promise, setCsrf: value => csrf.push(value), broadcast() {}});
  boundary.activate(); const pending = boundary.revalidate('initial');
  boundary.expire(); response.resolve(alice); await pending;
  assert.equal(boundary.getSnapshot().user, null);
  assert.equal(boundary.getSnapshot().checking, false);
  assert.equal(csrf.at(-1), ''); boundary.stop();
});

test('focus and remote notices cannot restore the old cookie while server logout is pending', async () => {
  let reads = 0, notices = 0;
  const boundary = makeBoundary({readIdentity: async () => {reads += 1; return alice;}, setCsrf() {}, broadcast() {notices += 1;}});
  boundary.activate(); await boundary.revalidate('initial');
  boundary.beginLogout(); await boundary.revalidate('focus'); boundary.remoteChange();
  assert.equal(reads, 1); assert.equal(boundary.getSnapshot().user, null);
  assert.equal(boundary.getSnapshot().checking, true); assert.equal(notices, 1);
  boundary.finishLogout();
  assert.equal(boundary.getSnapshot().checking, false); assert.equal(notices, 2);
  boundary.stop();
});

test('focus hides the existing view until the server answers and simultaneous focus checks share a probe', async () => {
  const next = deferred<typeof alice>(); let reads = 0;
  const boundary = makeBoundary({readIdentity: () => ++reads === 1 ? Promise.resolve(alice) : next.promise, setCsrf() {}, broadcast() {}});
  boundary.activate(); await boundary.revalidate('initial');
  boundary.suspend(); const first = boundary.revalidate('focus'); const second = boundary.revalidate('focus');
  assert.equal(boundary.getSnapshot().checking, true);
  assert.equal(first, second); assert.equal(reads, 2);
  next.resolve(alice); await first;
  assert.equal(boundary.getSnapshot().checking, false); boundary.stop();
});

test('a late manual HTTP body is discarded even when fetch ignores abort', async () => {
  const body = deferred<{private: string}>();
  globalThis.fetch = async () => ({ok: true, status: 200, json: () => body.promise}) as Response;
  allowPrivateRequests();
  const request = api.get('/api/private-synthetic');
  await Promise.resolve(); suspendPrivateRequests();
  body.resolve({private: 'synthetic stale bytes'});
  await assert.rejects(request, error => error instanceof Error && error.name === 'AbortError');
});

test('anonymous auth/me 401 performs one probe without global expiry or notification ping-pong', async () => {
  let requests = 0, notifications = 0;
  globalThis.fetch = async () => {requests += 1; return new Response('{"detail":"anonymous"}', {status: 401});};
  // No window is installed in this Node test: an accidental session-expired
  // dispatch from the auth probe would fail this test instead of looping.
  const boundary = makeBoundary({readIdentity: signal => api.get('/api/auth/me', {signal}), setCsrf() {}, broadcast() {notifications += 1;}});
  boundary.activate(); await boundary.revalidate('initial');
  assert.equal(requests, 1); assert.equal(notifications, 0);
  assert.equal(boundary.getSnapshot().user, null); assert.equal(boundary.getSnapshot().checking, false);
  boundary.stop();
});

test('remote session change clears query and mutation cache then probes without rebroadcast', async () => {
  let identity = alice, publications = 0;
  const boundary = makeBoundary({readIdentity: async () => identity, setCsrf() {}, broadcast() {publications += 1;}});
  boundary.activate(); await boundary.revalidate('initial');
  const old = boundary.getSnapshot().queryClient;
  old.setQueryData(['private'], 'synthetic');
  old.getMutationCache().build(old, {mutationKey: ['private-mutation'], mutationFn: async () => 'synthetic'});
  identity = bob; boundary.remoteChange(); await boundary.revalidate('focus');
  assert.equal(old.getQueryCache().getAll().length, 0);
  assert.equal(old.getMutationCache().getAll().length, 0);
  assert.equal(publications, 1); assert.equal(boundary.getSnapshot().user, null);
  boundary.stop();
});

for (const [label, next] of [
  ['a different user', bob],
  ['the same user with a new session', {...alice, csrf_token: 'synthetic-new-session-csrf'}],
] as const) {
  test(`work paused in a non-HTTP await cannot post old input after ${label} signs in`, async () => {
    let current: typeof alice | null = alice, navigations = 0, requests = 0, reads = 0;
    const csrf: string[] = [];
    globalThis.fetch = async () => {requests += 1; return new Response('{}');};
    const boundary = makeBoundary({readIdentity: async () => {
      reads += 1; if (!current) throw new Error('synthetic anonymous session'); return current;
    }, setCsrf: value => {csrf.push(value); setCsrfToken(value);}, broadcast() {}, navigate() {navigations += 1;}});
    boundary.activate(); await boundary.revalidate('initial');
    const fileText = deferred<string>();
    // This handler has begun, but has not called api.post or captured its epoch.
    const oldWork = (async () => {
      const text = await fileText.promise;
      return api.post('/api/private-generic-endpoint', {text});
    })();
    const blocked = assert.rejects(oldWork, error => error instanceof Error && error.name === 'AbortError');
    // Preserve the previous in-memory session binding across remote logout.
    current = null; boundary.remoteChange(); await boundary.revalidate('focus');
    assert.equal(boundary.getSnapshot().user, null);
    current = next; boundary.remoteChange(); await boundary.revalidate('focus');
    assert.equal(navigations, 1); assert.equal(boundary.getSnapshot().user, null);
    assert.equal(boundary.getSnapshot().checking, true);
    assert.equal(csrf.includes(next.csrf_token), false); assert.equal(csrf.at(-1), '');
    fileText.resolve('synthetic input from the previous session'); await blocked;
    assert.equal(requests, 0);
    await boundary.revalidate('focus'); assert.equal(reads, 3); // No old-heap re-entry while navigating.
    boundary.stop();
  });
}

test('ordinary same-session focus revalidation stays soft and preserves the current query client', async () => {
  let navigations = 0;
  const boundary = makeBoundary({readIdentity: async () => ({...alice}), setCsrf() {}, broadcast() {}, navigate() {navigations += 1;}});
  boundary.activate(); await boundary.revalidate('initial');
  const original = boundary.getSnapshot(); original.queryClient.setQueryData(['private'], 'synthetic same-session cache');
  boundary.suspend(); await boundary.revalidate('focus');
  const current = boundary.getSnapshot();
  assert.equal(navigations, 0); assert.equal(current.user?.user_id, alice.user_id);
  assert.equal(current.queryClient, original.queryClient); assert.equal(current.revision, original.revision);
  assert.equal(current.queryClient.getQueryData(['private']), 'synthetic same-session cache');
  boundary.stop();
});

test('StrictMode-style stop and activate ignores the previous probe', async () => {
  const first = deferred<typeof alice>(); let count = 0;
  const boundary = makeBoundary({readIdentity: () => ++count === 1 ? first.promise : Promise.resolve(bob), setCsrf() {}, broadcast() {}});
  boundary.activate(); const old = boundary.revalidate('initial'); boundary.stop();
  boundary.activate(); await boundary.revalidate('initial'); first.resolve(alice); await old;
  assert.equal(boundary.getSnapshot().user?.user_id, bob.user_id); boundary.stop();
});

test('cross-tab channel and storage duplicates deliver once and contain only version and nonce', () => {
  const targets: EventTarget[] = [], channels: Channel[] = [], writes: string[] = [];
  class Channel extends EventTarget {
    postMessage(data: unknown) {for (const other of channels) if (other !== this) other.dispatchEvent(new MessageEvent('message', {data}));}
    close() {}
  }
  function host(index: number) {
    const target = new EventTarget(); targets.push(target); const channel = new Channel(); channels.push(channel);
    return {addEventListener: (_: 'storage', listener: (event: StorageEvent) => void) => target.addEventListener('storage', listener as EventListener),
      removeEventListener: (_: 'storage', listener: (event: StorageEvent) => void) => target.removeEventListener('storage', listener as EventListener), channel,
      storage: {setItem(key: string, value: string) {writes.push(value); for (const other of targets) if (other !== target) {
        const event = new Event('storage'); Object.assign(event, {key, newValue: value}); other.dispatchEvent(event);
      }}}, nonce: () => `00000000-0000-4000-8000-${String(index).padStart(12, '0')}`};
  }
  let received = 0;
  const one = sessionNotifications(() => assert.fail('Sender must not receive itself'), host(1));
  const two = sessionNotifications(() => {received += 1;}, host(2));
  one.publish(); assert.equal(received, 1);
  assert.deepEqual(Object.keys(JSON.parse(writes[0])).sort(), ['nonce', 'version']);
  assert.equal(JSON.parse(writes[0]).version, 1);
  // Malformed/private-bearing messages have no session authority.
  channels[0].postMessage({version: 1, nonce: '00000000-0000-4000-8000-000000000003', user_id: alice.user_id});
  channels[0].postMessage({version: 2, nonce: '00000000-0000-4000-8000-000000000004'});
  assert.equal(received, 1); assert.equal(writes.length, 1);
  assert.equal(SESSION_NOTICE_KEY, 'investify.session-change.v1');
  one.close(); two.close();
});
