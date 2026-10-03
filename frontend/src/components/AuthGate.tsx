import {useEffect, useState, type FormEvent, type ReactNode} from 'react';
import {api, setCsrfToken} from '../api/client';
import {AuthContext, type SignedInUser} from './AuthContext';

type SignInConfig = {configured: boolean; local_password_enabled: boolean; login_url: string};

function GoogleMark() {
 return <svg aria-hidden="true" viewBox="0 0 24 24" className="h-5 w-5 shrink-0">
  <path fill="#4285F4" d="M21.35 12.24c0-.71-.06-1.38-.18-2.04H12v3.87h5.24a4.48 4.48 0 0 1-1.94 2.94v2.44h3.14c1.84-1.7 2.91-4.2 2.91-7.21Z"/>
  <path fill="#34A853" d="M12 21.5c2.63 0 4.84-.87 6.45-2.35l-3.14-2.44c-.87.58-1.98.92-3.31.92-2.55 0-4.71-1.72-5.48-4.03H3.28v2.51A9.75 9.75 0 0 0 12 21.5Z"/>
  <path fill="#FBBC05" d="M6.52 13.6A5.85 5.85 0 0 1 6.21 12c0-.55.1-1.09.31-1.6V7.89H3.28A9.75 9.75 0 0 0 2.25 12c0 1.55.37 3.02 1.03 4.11l3.24-2.51Z"/>
  <path fill="#EA4335" d="M12 6.37c1.43 0 2.72.49 3.73 1.47l2.8-2.8A9.36 9.36 0 0 0 12 2.5a9.75 9.75 0 0 0-8.72 5.39l3.24 2.51A5.84 5.84 0 0 1 12 6.37Z"/>
 </svg>;
}

function Brand({light = false}: {light?: boolean}) {
 return <div className="flex items-center gap-3">
  <span className="flex h-11 w-11 items-center justify-center overflow-hidden rounded-2xl bg-white p-1 shadow-sm"><img src="/favicon.png" alt="" className="h-full w-full object-contain"/></span>
  <span className={`text-lg font-bold tracking-tight ${light ? 'text-white' : 'text-slate-900'}`}>AInvestify</span>
 </div>;
}

function SignIn({config}: {config: SignInConfig | null}) {
 const [userId, setUserId] = useState('');
 const [password, setPassword] = useState('');
 const [showPassword, setShowPassword] = useState(false);
 const [error, setError] = useState('');
 const [submitting, setSubmitting] = useState(false);

 async function submit(event: FormEvent<HTMLFormElement>) {
  event.preventDefault();setError('');setSubmitting(true);
  try {
   await api.post('/api/auth/local-login', {user_id: userId.trim(), password});
   setPassword('');window.location.assign('/');
  } catch (err) {
   setError(err instanceof Error ? err.message : 'Sign-in failed. Please try again.');setSubmitting(false);
  }
 }

 return <main className="min-h-screen bg-[#f5f7fa] text-slate-900 lg:grid lg:grid-cols-[minmax(0,1fr)_minmax(520px,0.95fr)]">
  <section className="relative hidden min-h-screen flex-col overflow-hidden bg-[#11243b] p-12 text-white lg:flex xl:p-16" aria-label="About AInvestify">
   <div aria-hidden="true" className="pointer-events-none absolute -right-28 top-12 h-96 w-96 rounded-full bg-emerald-400/15 blur-3xl"/>
   <div aria-hidden="true" className="pointer-events-none absolute -left-20 bottom-6 h-72 w-72 rounded-full bg-indigo-400/15 blur-3xl"/>
   <div className="relative"><Brand light/><p className="mt-3 pl-14 text-xs font-medium uppercase tracking-[0.24em] text-slate-300">Deal workspace</p></div>
   <div className="relative my-auto max-w-xl py-12">
    <h1 className="text-4xl font-semibold leading-[1.12] tracking-tight xl:text-5xl">Build a clearer case for every deal.</h1>
    <p className="mt-6 max-w-md text-base leading-7 text-slate-300">Bring research, numbers and working documents together as a deal takes shape.</p>
    <div className="mt-10 grid max-w-lg gap-3 sm:grid-cols-3">{['Collect evidence','Review financials','Prepare materials'].map((item,index)=><div key={item} className="rounded-2xl border border-white/10 bg-white/5 p-4 backdrop-blur-sm"><span className="text-xs font-semibold text-emerald-300">0{index+1}</span><p className="mt-2 text-sm font-medium leading-5 text-white">{item}</p></div>)}</div>
   </div>
  </section>

  <section className="flex min-h-screen flex-col justify-center px-5 py-8 sm:px-10 lg:px-12 xl:px-20">
   <div className="mx-auto w-full max-w-[460px]">
    <div className="mb-8 lg:hidden"><Brand/></div>
    <div className="rounded-[28px] border border-slate-200/90 bg-white p-6 shadow-[0_22px_65px_-32px_rgba(15,35,60,0.28)] sm:p-9">
     <div className="mb-7"><p className="text-xs font-semibold uppercase tracking-[0.2em] text-indigo-600">Account access</p><h2 className="mt-2 text-3xl font-semibold tracking-tight text-slate-950">Welcome back</h2><p className="mt-2 text-sm leading-6 text-slate-500">Choose how you’d like to continue.</p></div>
     {config?.configured ? <a href={config.login_url} className="flex min-h-12 w-full items-center justify-center gap-3 rounded-xl border border-slate-300 bg-white px-4 text-sm font-semibold text-slate-800 shadow-sm transition hover:border-slate-400 hover:bg-slate-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600"><GoogleMark/>Continue with Google</a>
      : <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3.5"><div className="flex items-center justify-between gap-3"><div className="flex items-center gap-3 text-sm font-semibold text-slate-500"><GoogleMark/>Continue with Google</div><span className="whitespace-nowrap rounded-full bg-slate-200 px-2.5 py-1 text-[11px] font-semibold text-slate-600 sm:hidden">Pending</span><span className="hidden whitespace-nowrap rounded-full bg-slate-200 px-2.5 py-1 text-[11px] font-semibold text-slate-600 sm:inline-flex">Setup pending</span></div></div>}
     {config?.local_password_enabled && <>
      <div className="my-7 flex items-center gap-4"><span className="h-px flex-1 bg-slate-200"/><span className="text-xs font-medium uppercase tracking-widest text-slate-400">or</span><span className="h-px flex-1 bg-slate-200"/></div>
      <form onSubmit={submit} className="space-y-4">
       <h3 className="text-sm font-semibold text-slate-900">Use a local account</h3>
       <label className="block text-sm font-medium text-slate-700">User ID<input className="mt-1.5 block h-12 w-full rounded-xl border border-slate-300 bg-white px-3.5 text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-indigo-500 focus:ring-4 focus:ring-indigo-100" value={userId} onChange={event=>setUserId(event.target.value)} autoComplete="username" placeholder="Enter your user ID" required /></label>
       <label className="block text-sm font-medium text-slate-700">Password<span className="relative mt-1.5 block"><input className="block h-12 w-full rounded-xl border border-slate-300 bg-white px-3.5 pr-16 text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-indigo-500 focus:ring-4 focus:ring-indigo-100" type={showPassword ? 'text' : 'password'} value={password} onChange={event=>setPassword(event.target.value)} autoComplete="current-password" placeholder="Enter your password" required /><button type="button" className="absolute inset-y-0 right-3 text-xs font-semibold text-slate-500 hover:text-indigo-700" onClick={()=>setShowPassword(value=>!value)} aria-label={showPassword ? 'Hide password' : 'Show password'}>{showPassword ? 'Hide' : 'Show'}</button></span></label>
       {error && <p role="alert" className="rounded-xl border border-rose-200 bg-rose-50 px-3 py-2.5 text-sm text-rose-800">{error}</p>}
       <button className="flex h-12 w-full items-center justify-center rounded-xl bg-indigo-600 px-5 text-sm font-semibold text-white shadow-sm transition hover:bg-indigo-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600 disabled:cursor-wait disabled:opacity-60" type="submit" disabled={submitting}>{submitting ? 'Signing in…' : 'Sign in'}</button>
      </form>
     </>}
     {!config?.configured && !config?.local_password_enabled && <p role="status" className="mt-6 rounded-xl bg-amber-50 p-4 text-sm text-amber-900">Sign-in is waiting for server configuration.</p>}
    </div>
   </div>
  </section>
 </main>;
}

export default function AuthGate({children}: {children: ReactNode}) {
 const [user, setUser] = useState<SignedInUser | null>(null);
 const [loading, setLoading] = useState(true);
 const [config, setConfig] = useState<SignInConfig | null>(null);
 useEffect(() => {
  let live = true;
  async function load() {
   try {
   const me = await api.get<SignedInUser>('/api/auth/me');
    if (live) {setCsrfToken(me.csrf_token);setUser(me);setLoading(false);}
   } catch {
    if (live) {setUser(null);setCsrfToken('');}
    try {const next = await api.get<SignInConfig>('/api/auth/config');if (live) setConfig(next);} catch { /* Sign-in shows server status. */ }
    if (live) setLoading(false);
   }
  }
  void load();
  const expired = () => {setCsrfToken('');setUser(null);void api.get<SignInConfig>('/api/auth/config').then(next=>{if(live)setConfig(next);}).catch(()=>{});};
  window.addEventListener('session-expired', expired);
  return () => {live = false;window.removeEventListener('session-expired', expired);};
 }, []);
 if (loading) return <div role="status" className="flex min-h-screen items-center justify-center bg-[#f5f7fa] text-sm font-medium text-slate-600"><span className="mr-3 h-5 w-5 animate-spin rounded-full border-2 border-indigo-200 border-t-indigo-600"/>Opening your workspace…</div>;
 if (!user) return <SignIn config={config}/>;
 return <AuthContext.Provider value={{user, signOut: async () => {
  await api.post('/api/auth/logout');setCsrfToken('');window.location.assign('/');
 }}}>{children}</AuthContext.Provider>;
}
