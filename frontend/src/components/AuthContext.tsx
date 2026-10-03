import {createContext, useContext} from 'react';

export type SignedInUser = {
 user_id: string;
 tenant_id: string;
 role: string;
 csrf_token: string;
 display_name: string;
 sign_in_method: 'google' | 'local';
};

export const AuthContext = createContext<{user: SignedInUser; signOut: () => Promise<void>} | null>(null);

export function useAuth() {
 const context = useContext(AuthContext);
 if (!context) throw new Error('Account context is unavailable');
 return context;
}
