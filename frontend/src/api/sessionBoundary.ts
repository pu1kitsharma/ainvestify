import {QueryClient} from '@tanstack/react-query';
import {allowPrivateRequests, SessionChangedError, suspendPrivateRequests} from './sessionEpoch.ts';

export type SessionIdentity = {user_id: string; tenant_id: string; csrf_token: string};
export type SessionSnapshot<T> = {user: T | null; checking: boolean; queryClient: QueryClient; revision: number};
type CheckSource = 'initial' | 'focus' | 'remote';

export function identityKey(user: SessionIdentity) { return JSON.stringify([user.user_id, user.tenant_id]); }

export function createPrivateQueryClient() {
  return new QueryClient({defaultOptions: {queries: {retry: 1, refetchOnWindowFocus: false}}});
}

function clearPrivateClient(client: QueryClient) {
  // Query cancellation does not cancel mutations. Detach their old UI hooks
  // and prevent a queued/retrying mutation from starting under a new cookie.
  for (const mutation of client.getMutationCache().getAll()) {
    mutation.setOptions({...mutation.options,
      mutationFn: async () => {throw new SessionChangedError();},
      onMutate: undefined, onSuccess: undefined, onError: undefined, onSettled: undefined});
  }
  void client.cancelQueries().catch(() => {});
  client.clear();
}

export class SessionBoundary<T extends SessionIdentity> {
  private state: SessionSnapshot<T> = {user: null, checking: true, queryClient: createPrivateQueryClient(), revision: 0};
  private listeners = new Set<() => void>();
  private serial = 0;
  private active = false;
  private loggingOut = false;
  private navigating = false;
  // Retained only in this document's memory, including while signed out.
  // A new session must never make old async work authoritative again.
  private confirmedSession: {identity: string; csrf: string} | null = null;
  private probe: AbortController | null = null;
  private pending: Promise<void> | null = null;
  private readIdentity: (signal: AbortSignal) => Promise<T>;
  private setCsrf: (value: string) => void;
  private broadcast: () => void;
  private navigate: () => void;

  constructor(options: {readIdentity: (signal: AbortSignal) => Promise<T>; setCsrf: (value: string) => void; broadcast: () => void; navigate: () => void}) {
    this.readIdentity = options.readIdentity;
    this.setCsrf = options.setCsrf;
    this.broadcast = options.broadcast;
    this.navigate = options.navigate;
  }

  getSnapshot = () => this.state;
  subscribe = (listener: () => void) => { this.listeners.add(listener); return () => { this.listeners.delete(listener); }; };
  private update(next: Partial<SessionSnapshot<T>>) {
    this.state = {...this.state, ...next};
    for (const listener of this.listeners) listener();
  }
  activate() { this.active = true; }
  setBroadcaster(callback: () => void) { this.broadcast = callback; }

  private discard(notify = true) {
    suspendPrivateRequests(); this.setCsrf('');
    const old = this.state.queryClient;
    clearPrivateClient(old);
    const next = {queryClient: createPrivateQueryClient(), revision: this.state.revision + 1};
    if (notify) this.update(next); else this.state = {...this.state, ...next};
  }

  suspend() {
    if (!this.active) return;
    this.serial += 1; this.probe?.abort(); this.probe = null; this.pending = null;
    suspendPrivateRequests(); this.setCsrf('');
    void this.state.queryClient.cancelQueries().catch(() => {});
    this.update({checking: true});
  }

  expire(broadcast = true) {
    if (!this.active) return;
    this.serial += 1; this.probe?.abort(); this.probe = null; this.pending = null;
    this.discard(); this.update({user: null, checking: this.loggingOut || this.navigating});
    if (broadcast) this.broadcast();
  }

  beginLogout() { this.loggingOut = true; this.expire(false); }
  finishLogout(success = true) { this.loggingOut = false; this.expire(success); }

  remoteChange() {
    if (!this.active) return;
    this.expire(false);
    void this.revalidate('remote');
  }

  revalidate(source: CheckSource): Promise<void> {
    if (!this.active || this.loggingOut || this.navigating) return Promise.resolve();
    if (source === 'focus' && this.pending) return this.pending;
    this.serial += 1; const serial = this.serial;
    this.probe?.abort(); const probe = new AbortController(); this.probe = probe;
    suspendPrivateRequests(); this.setCsrf('');
    void this.state.queryClient.cancelQueries().catch(() => {});
    this.update({checking: true});
    const load = async () => {
      try {
        const next = await this.readIdentity(probe.signal);
        if (!this.active || serial !== this.serial) return;
        if (!next || !next.user_id || !next.tenant_id || !next.csrf_token
            || typeof next.user_id !== 'string' || typeof next.tenant_id !== 'string' || typeof next.csrf_token !== 'string') {
          throw new Error('Invalid account identity response');
        }
        const nextIdentity = identityKey(next);
        if (this.confirmedSession && (this.confirmedSession.identity !== nextIdentity
            || this.confirmedSession.csrf !== next.csrf_token)) {
          // Unmounting cannot stop a handler paused in file.text(), a timer or
          // another non-HTTP await. Keep all private HTTP blocked and destroy
          // this JS document before accepting the new session's CSRF/user.
          this.navigating = true; this.serial += 1;
          this.probe?.abort(); this.probe = null; this.pending = null;
          this.discard(); this.update({user: null, checking: true});
          if (source !== 'remote') this.broadcast();
          this.navigate();
          return;
        }
        const previous = this.state.user ? identityKey(this.state.user) : null;
        const changed = previous !== nextIdentity;
        if (changed) this.discard();
        this.confirmedSession = {identity: nextIdentity, csrf: next.csrf_token};
        this.setCsrf(next.csrf_token); allowPrivateRequests();
        this.update({user: next, checking: false});
        if (source !== 'remote' && (source === 'initial' || previous !== null && changed)) this.broadcast();
      } catch {
        if (!this.active || serial !== this.serial) return;
        const hadUser = this.state.user !== null;
        this.discard(); this.update({user: null, checking: false});
        if (source !== 'remote' && hadUser) this.broadcast();
      } finally {
        if (serial === this.serial) { this.pending = null; this.probe = null; }
      }
    };
    this.pending = load();
    return this.pending;
  }

  stop() {
    this.active = false; this.loggingOut = false; this.serial += 1; this.probe?.abort(); this.probe = null; this.pending = null;
    this.discard(false); this.state = {...this.state, user: null, checking: true};
  }
}

export const SESSION_NOTICE_KEY = 'investify.session-change.v1';
type Notice = {version: 1; nonce: string};
type NoticeChannel = Pick<BroadcastChannel, 'postMessage' | 'addEventListener' | 'removeEventListener' | 'close'>;
type NoticeHost = {
  addEventListener: (type: 'storage', listener: (event: StorageEvent) => void) => void;
  removeEventListener: (type: 'storage', listener: (event: StorageEvent) => void) => void;
  storage: Pick<Storage, 'setItem'>;
  channel: NoticeChannel | null;
  nonce: () => string;
};

// Only a version and fresh event nonce cross tabs. Duplicated channel/storage
// delivery is deduplicated, and receiving never publishes another notice.
export function sessionNotifications(onChange: () => void, host?: NoticeHost) {
  let browserChannel: BroadcastChannel | null = null;
  if (!host) {
    try { browserChannel = new BroadcastChannel(SESSION_NOTICE_KEY); } catch { /* Focus checks remain available. */ }
    host = {addEventListener: (type, listener) => window.addEventListener(type, listener),
      removeEventListener: (type, listener) => window.removeEventListener(type, listener),
      storage: {setItem: (key, value) => window.localStorage.setItem(key, value)},
      channel: browserChannel, nonce: () => crypto.randomUUID()};
  }
  const target = host;
  const seen = new Set<string>(); let closed = false;
  const remember = (nonce: string) => {
    seen.add(nonce);
    if (seen.size > 64) seen.delete(seen.values().next().value!);
  };
  const receive = (value: unknown) => {
    if (closed || !value || typeof value !== 'object') return;
    const notice = value as Notice;
    if (Object.keys(notice).sort().join(',') !== 'nonce,version' || notice.version !== 1
        || typeof notice.nonce !== 'string' || !/^[0-9a-f-]{36}$/i.test(notice.nonce) || seen.has(notice.nonce)) return;
    remember(notice.nonce); onChange();
  };
  const message = (event: MessageEvent) => receive(event.data);
  const storage = (event: StorageEvent) => {
    if (event.key !== SESSION_NOTICE_KEY || !event.newValue) return;
    try { receive(JSON.parse(event.newValue)); } catch { /* Unrelated/invalid notices have no authority. */ }
  };
  target.channel?.addEventListener('message', message);
  target.addEventListener('storage', storage);
  return {
    publish() {
      if (closed) return;
      const notice: Notice = {version: 1, nonce: target.nonce()}; remember(notice.nonce);
      try { target.channel?.postMessage(notice); } catch { /* Storage/focus remain available. */ }
      try { target.storage.setItem(SESSION_NOTICE_KEY, JSON.stringify(notice)); } catch { /* Storage can be disabled. */ }
    },
    close() {
      closed = true; target.channel?.removeEventListener('message', message); target.channel?.close();
      target.removeEventListener('storage', storage);
    },
  };
}
