import React, { useCallback, useEffect, useState } from 'react';
import { api } from '../api/client';
import { getApiErrorMessage } from '../api/error';
import type { AuthLoginResponse, AuthSessionResponse } from '../types/api.types';

export function AuthBar() {
  const [open, setOpen] = useState(false);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [checking, setChecking] = useState(true);
  const [session, setSession] = useState<{ username: string; role: string } | null>(null);

  const refreshSession = useCallback(async () => {
    setChecking(true);
    try {
      const { data } = await api.get<AuthSessionResponse>('/auth/me');
      const uname = data.username?.trim();
      const role = data.role?.trim();
      if (data.authenticated && uname) {
        setSession({ username: uname, role: role || 'viewer' });
      } else {
        setSession(null);
      }
    } catch {
      setSession(null);
    } finally {
      setChecking(false);
    }
  }, []);

  useEffect(() => {
    void refreshSession();
  }, [refreshSession]);

  const logout = useCallback(async () => {
    setBusy(true);
    setErr(null);
    try {
      await api.post('/auth/logout');
    } catch {
      // Даже если запрос logout упал, локально считаем сессию завершённой.
    } finally {
      setSession(null);
      setOpen(false);
      setPassword('');
      setBusy(false);
    }
  }, []);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr(null);
    setBusy(true);
    try {
      const body = new URLSearchParams();
      body.set('username', username.trim());
      body.set('password', password);
      const { data } = await api.post<AuthLoginResponse>('/auth/login', body, {
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      });
      if ((data.status || '').toUpperCase() !== 'OK') {
        setErr('Ошибка входа');
        return;
      }
      const uname = data.username?.trim();
      if (uname) {
        setSession({ username: uname, role: (data.role || 'viewer').trim() || 'viewer' });
      } else {
        await refreshSession();
      }
      setPassword('');
      setOpen(false);
    } catch (e) {
      setErr(getApiErrorMessage(e, 'Ошибка входа'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex items-center gap-2">
      {session ? (
        <span className="text-[10px] font-semibold uppercase tracking-[0.14em] text-emerald-400/90">
          {session.role}
        </span>
      ) : checking ? (
        <span className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">…</span>
      ) : null}
      <button type="button" className="cc-btn-ghost text-[11px]" onClick={() => setOpen(true)}>
        {session ? 'Сменить' : 'Вход'}
      </button>
      {session ? (
        <button type="button" className="cc-btn-ghost text-[11px] text-slate-500" onClick={() => void logout()}>
          Выйти
        </button>
      ) : null}

      {open && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/20 p-4 backdrop-blur-sm"
          role="dialog"
          aria-modal="true"
          aria-labelledby="cc-auth-title"
          onClick={() => setOpen(false)}
        >
          <div className="cc-card w-full max-w-sm p-5 shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <h3 id="cc-auth-title" className="text-[14px] font-semibold text-slate-900">
              Вход в систему
            </h3>
            <p className="mt-1 text-[11px] text-slate-500">
              Сеанс безопасно сохраняется в браузере после авторизации.
            </p>
            <form className="mt-4 space-y-3" onSubmit={(e) => void submit(e)}>
              <div>
                <label className="text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-500">Логин</label>
                <input
                  className="cc-input mt-1 w-full"
                  autoComplete="username"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                />
              </div>
              <div>
                <label className="text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-500">Пароль</label>
                <input
                  type="password"
                  className="cc-input mt-1 w-full"
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
              </div>
              {err && <div className="text-[11px] text-red-700">{err}</div>}
              <div className="flex justify-end gap-2 pt-1">
                <button type="button" className="cc-btn-ghost text-[11px]" onClick={() => setOpen(false)}>
                  Отмена
                </button>
                <button type="submit" className="cc-btn-primary text-[11px]" disabled={busy}>
                  {busy ? '…' : 'Войти'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
