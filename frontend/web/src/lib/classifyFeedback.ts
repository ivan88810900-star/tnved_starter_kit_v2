/**
 * Feedback loop: подтверждённая классификация → БД прецедентов (бэкенд /api/classify/feedback/approve).
 */

const rawBase = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "";

function apiBase(): string {
  return rawBase.replace(/\/+$/, "");
}

export type ApproveClassificationPayload = {
  original_description: string;
  approved_hs_code: string;
  user_note?: string;
  user_id?: string;
  invoice_context?: string;
};

export type ApproveClassificationResponse = {
  example_id: number;
  hs_code: string;
  description: string;
  source: string;
  created: boolean;
  embedding_scheduled: boolean;
};

export async function approveClassification(
  payload: ApproveClassificationPayload,
): Promise<ApproveClassificationResponse> {
  const base = apiBase();
  const url = `${base}/api/classify/feedback/approve`;
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      original_description: payload.original_description.trim(),
      approved_hs_code: payload.approved_hs_code.replace(/\D/g, "").slice(0, 10),
      user_note: payload.user_note?.trim() || undefined,
      user_id: payload.user_id?.trim() || undefined,
      invoice_context: payload.invoice_context?.trim() || undefined,
    }),
  });
  const text = await res.text();
  if (!res.ok) {
    throw new Error(text || `Ошибка ${res.status}: не удалось сохранить прецедент`);
  }
  return JSON.parse(text) as ApproveClassificationResponse;
}
