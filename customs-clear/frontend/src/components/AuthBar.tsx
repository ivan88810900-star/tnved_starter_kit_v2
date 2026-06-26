import React, { useCallback, useEffect, useState } from 'react';
import { api } from '../api/client';
import { getApiErrorMessage } from '../api/error';
import type { AuthLoginResponse, AuthSessionResponse } from '../types/api.types';

type Props = {
  variant?: 'default' | 'cargo';
};

export function AuthBar({ variant = 'default' }: Props) {
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
      /* ignore */
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

  const isCargo = variant === 'cargo';

  return (
    <div className="flex items-center gap-2">
      {session ? (
        <>
          <span className={`hidden text-[11px] font-medium uppercase tracking-[0.06em] sm:inline ${isCargo ? 'text-cargo-clear' : 'text-emerald-600'}`}>
            {session.username} · {session.role}
          </span>
          <button type="button" className={isCargo ? 'cc-btn-secondary text-xs' : 'cc-btn-ghost text-[11px]'} onClick={() => void logout()}>
            Выйти
          </button>
        </>
      ) : checking ? (
        <span className="cc-spinner" aria-label="Проверка сессии" />
      ) : isCargo ? (
        <>
          <button
            type="button"
            className="h-8 rounded-md border border-[var(--cargo-border)] bg-transparent px-3.5 text-[13px] text-[var(--cargo-mid)] transition-all duration-150 hover:border-[var(--cargo-trust)] hover:text-[var(--cargo-trust)]"
            onClick={() => setOpen(true)}
          >
            Войти
          </button>
          <button
            type="button"
            className="h-8 rounded-md border-none bg-[var(--cargo-trust)] px-3.5 text-[13px] font-medium text-white transition-all duration-150 hover:bg-[var(--cargo-trust-hover)]"
            onClick={() => setOpen(true)}
          >
            Регистрация
          </button>
        </>
      ) : (
        <button type="button" className="cc-btn-ghost text-[11px]" onClick={() => setOpen(true)}>
          Вход
        </button>
      )}

      {open && (
        <div
          className="fixed inset-0 z-[60] flex items-center justify-center bg-cargo-deep/30 p-4 backdrop-blur-sm"
          role="dialog"
          aria-modal="true"
          aria-labelledby="cc-auth-title"
          onClick={() => setOpen(false)}
        >
          <div className="cc-card w-full max-w-sm p-5 shadow-xl" onClick={(e) => e.stopPropagation()}>
            <h3 id="cc-auth-title" className="text-base font-medium text-cargo-deep">
              Вход в систему
            </h3>
            <p className="mt-1 text-xs text-cargo-mid">
              Сеанс сохраняется в браузере после авторизации. Для регистрации обратитесь к администратору.
            </p>
            <form className="mt-4 space-y-3" onSubmit={(e) => void submit(e)}>
              <div>
                <label className="cc-label">Логин</label>
                <input
                  className="cc-input mt-1 w-full"
                  autoComplete="username"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                />
              </div>
              <div>
                <label className="cc-label">Пароль</label>
                <input
                  type="password"
                  className="cc-input mt-1 w-full"
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
              </div>
              {err && <div className="text-xs text-cargo-alert">{err}</div>}
              <div className="flex justify-end gap-2 pt-1">
                <button type="button" className="cc-btn-secondary text-xs" onClick={() => setOpen(false)}>
                  Отмена
                </button>
                <button type="submit" className="cc-btn-primary text-xs" disabled={busy}>
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
