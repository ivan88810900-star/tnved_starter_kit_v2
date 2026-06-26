import axios from 'axios';

export const api = axios.create({
  baseURL: '/api',
  withCredentials: true,
});

function removeLegacyTokenStorage(): void {
  try {
    localStorage.removeItem('cc_access_token');
    sessionStorage.removeItem('cc_access_token');
    localStorage.removeItem('cc_admin_token');
    sessionStorage.removeItem('cc_admin_token');
  } catch {
    /* ignore */
  }
}

removeLegacyTokenStorage();

function sessionFirst(key: string): string | null {
  const fromSession = sessionStorage.getItem(key);
  if (fromSession?.trim()) return fromSession.trim();
  const legacy = localStorage.getItem(key);
  if (legacy?.trim()) {
    // One-time migration for non-sensitive fields.
    sessionStorage.setItem(key, legacy.trim());
    localStorage.removeItem(key);
    return legacy.trim();
  }
  return null;
}

/** Пробрасывается в JSONL-аудит бэкенда (если AUDIT_LOG_ENABLED): X-Client-Id, X-Audit-Subject. */
api.interceptors.request.use((config) => {
  try {
    config.headers = config.headers ?? {};
    const h = config.headers as Record<string, string>;
    const id = sessionFirst('cc_audit_client_id');
    if (id?.trim()) h['X-Client-Id'] = id.trim().slice(0, 128);
    const sub = sessionFirst('cc_audit_subject');
    if (sub?.trim()) h['X-Audit-Subject'] = sub.trim().slice(0, 512);
  } catch {
    /* ignore */
  }
  return config;
});
