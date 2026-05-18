import { useState, useMemo } from "react";
import type { AnalyzeResponse } from "../types";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "";

export function useInvoiceAnalysis() {
  const [result, setResult] = useState<AnalyzeResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string>("");

  const stats = useMemo(() => {
    const items = result?.items ?? [];
    return {
      total: items.length,
      validCodes: items.filter((i) => /^\d{10}$/.test(i.hs_code ?? "")).length,
      totalRisks: items.reduce((acc, i) => acc + (i.risks?.length ?? 0), 0),
      hasWarning: !!result?.warning,
    };
  }, [result]);

  const analyze = async (file: File | null) => {
    setLoading(true);
    setError("");
    try {
      const formData = new FormData();
      if (file) formData.append("file", file);
      formData.append("use_mock", String(!file));

      const res = await fetch(`${API_BASE_URL}/api/analyze-invoice`, {
        method: "POST",
        body: formData,
      });

      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || `Ошибка сервера: ${res.status}`);
      }

      const data = (await res.json()) as AnalyzeResponse;
      setResult(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Неизвестная ошибка запроса.");
      setResult(null);
    } finally {
      setLoading(false);
    }
  };

  const reset = () => {
    setResult(null);
    setError("");
  };

  return { result, loading, error, stats, analyze, reset };
}
