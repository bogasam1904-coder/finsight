import React, { createContext, useContext, useState, useEffect, ReactNode } from 'react';
import { apiFetch, saveToken, clearToken } from '../api';

interface User { user_id: string; name: string; email: string; }
interface AuthContextType {
  user: User | null; loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (name: string, email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => { checkSession(); }, []);

  const checkSession = async () => {
    try {
      const res = await apiFetch('/auth/me');
      if (res.ok) setUser(await res.json());
    } catch (e) {} finally { setLoading(false); }
  };

  const login = async (email: string, password: string) => {
    const res = await apiFetch('/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) });
    if (!res.ok) { const err = await res.json().catch(() => ({})); throw new Error(err.detail || 'Login failed'); }
    const data = await res.json();
    await saveToken(data.token);
    setUser({ user_id: data.user_id, name: data.name, email: data.email });
  };

  const register = async (name: string, email: string, password: string) => {
    const res = await apiFetch('/auth/register', { method: 'POST', body: JSON.stringify({ name, email, password }) });
    if (!res.ok) { const err = await res.json().catch(() => ({})); throw new Error(err.detail || 'Registration failed'); }
    const data = await res.json();
    await saveToken(data.token);
    setUser({ user_id: data.user_id, name: data.name, email: data.email });
  };

  const logout = async () => { await clearToken(); setUser(null); };

  return <AuthContext.Provider value={{ user, loading, login, register, logout }}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
