import { api } from './client';
import type { SanctionsRiskBlockData } from '../types/api.types';

export type RiskCheckRequest = {
  hs_code: string;
  description?: string;
  country?: string | null;
  destination_country?: string | null;
  counterparty_name?: string | null;
};

export async function fetchRiskCheck(payload: RiskCheckRequest): Promise<SanctionsRiskBlockData> {
  const { data } = await api.post<SanctionsRiskBlockData>('/risk/check', payload);
  return data;
}
