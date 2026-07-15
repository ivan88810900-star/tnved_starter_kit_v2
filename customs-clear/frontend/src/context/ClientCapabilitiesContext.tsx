import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { api } from '../api/client';

export type ApiHealthStatus = 'loading' | 'ok' | 'degraded' | 'down';

type ReadyResponse = {
  status?: string;
  database?: boolean;
  redis?: boolean | null;
  assistant_llm_configured?: boolean;
};

type CapabilitiesValue = {
  health: ApiHealthStatus;
  assistantLlmConfigured: boolean;
  refetchHealth: () => void;
};

const ClientCapabilitiesContext = createContext<CapabilitiesValue>({
  health: 'loading',
  assistantLlmConfigured: false,
  refetchHealth: () => {},
});

export function ClientCapabilitiesProvider({ children }: { children: React.ReactNode }) {
  const [health, setHealth] = useState<ApiHealthStatus>('loading');
  const [assistantLlmConfigured, setAssistantLlmConfigured] = useState(false);

  const load = useCallback(() => {
    setHealth('loading');
    api
      .get<ReadyResponse>('/health/ready')
      .then(({ data }) => {
        const db = data?.database === true;
        const ready = (data?.status || '') === 'ready';
        setAssistantLlmConfigured(Boolean(data?.assistant_llm_configured));
        if (db && ready) setHealth('ok');
        else if (db) setHealth('degraded');
        else setHealth('degraded');
      })
      .catch(() => {
        setHealth('down');
        setAssistantLlmConfigured(false);
      });
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const value = useMemo(
    () => ({ health, assistantLlmConfigured, refetchHealth: load }),
    [health, assistantLlmConfigured, load],
  );

  return <ClientCapabilitiesContext.Provider value={value}>{children}</ClientCapabilitiesContext.Provider>;
}

export function useClientCapabilities(): CapabilitiesValue {
  return useContext(ClientCapabilitiesContext);
}

/** Ассистент работает на серверных фактах; LLM — необязательный слой формулировки. */
export function useAssistantSurfaceVisible(): boolean {
  const { health } = useClientCapabilities();

  if (health === 'loading') return false;
  return health !== 'down';
}
