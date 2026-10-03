import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import {useState} from 'react';
import {useAuth} from './AuthContext';

const navItems = [
  { to: "/", label: "My companies", end: true },
  { to: "/leads", label: "Discover", end: false },
];

export default function Layout() {
  const {pathname}=useLocation();
  const {user,signOut}=useAuth();
  const [signingOut,setSigningOut]=useState(false);
  const [signOutError,setSignOutError]=useState('');
  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <header className="border-b border-slate-200 bg-white shadow-[0_1px_2px_rgba(15,23,42,0.03)]">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-7 gap-y-3 px-4 py-3 sm:px-6">
          <Link to="/" className="flex shrink-0 items-center gap-2.5" aria-label="AInvestify home">
            <span className="flex h-9 w-9 items-center justify-center overflow-hidden rounded-xl border border-slate-100 bg-white p-0.5"><img src="/favicon.png" alt="" className="h-full w-full object-contain"/></span>
            <span className="text-base font-bold tracking-tight text-slate-900">AInvestify</span>
          </Link>
          <nav className="order-3 flex w-full gap-1 sm:order-none sm:w-auto" aria-label="Main navigation">
            {navItems.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  `rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
                    (isActive || (item.to === "/" && (pathname.startsWith("/operations") || pathname.startsWith("/deals"))))
                      ? "bg-indigo-50 text-indigo-700"
                      : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"
                  }`
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-2 sm:gap-3">
            <div className="flex items-center gap-2.5 rounded-xl border border-slate-200 bg-slate-50 px-2.5 py-1.5 sm:px-3" title={`Signed in as ${user.display_name} (${user.user_id})`}>
              <span aria-hidden="true" className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-indigo-100 text-sm font-bold uppercase text-indigo-700">{user.display_name.charAt(0)}</span>
              <div className="min-w-0"><p className="max-w-28 truncate text-xs font-semibold leading-4 text-slate-900 sm:max-w-40">{user.display_name}</p><p className="text-[11px] leading-4 text-slate-500">{user.sign_in_method === 'local' ? 'Local account' : `Account · ${user.user_id.slice(-8)}`}</p></div>
            </div>
            <button type="button" disabled={signingOut} onClick={async()=>{setSigningOut(true);setSignOutError('');try{await signOut();}catch{setSignOutError('Could not sign out. Try again.');setSigningOut(false);}}} className="inline-flex h-11 items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 text-xs font-semibold text-slate-700 transition hover:border-slate-300 hover:bg-slate-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600 disabled:opacity-60 sm:px-4 sm:text-sm" aria-label="Sign out">
              <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-4 w-4"><path strokeLinecap="round" strokeLinejoin="round" d="M9 7V5a2 2 0 0 1 2-2h7a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-7a2 2 0 0 1-2-2v-2M4 12h11m-4-4 4 4-4 4"/></svg>
              <span>{signingOut ? 'Signing out…' : 'Sign out'}</span>
            </button>
          </div>
        </div>
        {signOutError && <p role="alert" className="mx-auto max-w-6xl px-4 pb-2 text-sm text-rose-700 sm:px-6">{signOutError}</p>}
      </header>
      <main className="mx-auto max-w-6xl px-4 py-6 sm:px-6">
        <Outlet />
      </main>
    </div>
  );
}
