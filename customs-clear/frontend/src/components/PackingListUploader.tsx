import React, { useCallback, useEffect, useRef, useState } from 'react';
import axios from 'axios';
import { useNavigate } from 'react-router-dom';
import { Camera } from 'lucide-react';
import { api } from '../api/client';
import { getUserFacingApiError } from '../api/error';
import { CC_TNVED_SELECT_CODE_KEY } from '../constants/homeNav';

type Stage = 'upload' | 'processing' | 'results' | 'error';

type PackingListRow = {
  row_num?: number;
  article?: string;
  name_cn?: string;
  translation_used?: string;
  hs_code?: string;
  hs_confidence?: number;
  hs_description?: string;
  visual_analysis?: string;
  has_image?: boolean;
  classify_status?: string;
};

type TaskStatus = {
  task_id?: string;
  status?: string;
  processed?: number;
  total?: number;
  eta_seconds?: number;
  error?: string;
  original_filename?: string;
};

type UploadResponse = {
  task_id: string;
  status: string;
  total_rows: number;
  results?: PackingListRow[];
};

type ResultsResponse = {
  task_id: string;
  status?: string;
  processed?: number;
  total?: number;
  start: number;
  limit: number;
  results: PackingListRow[];
};

function formatEta(seconds: number | undefined): string {
  if (seconds == null || seconds <= 0) return 'скоро';
  const mins = Math.max(1, Math.ceil(seconds / 60));
  return `~${mins} мин`;
}

function imageAnalyzed(row: PackingListRow): boolean {
  return Boolean(row.visual_analysis?.trim() || (row.has_image && row.hs_code));
}

function confidencePct(row: PackingListRow): string {
  const c = row.hs_confidence;
  if (c == null || Number.isNaN(c)) return '—';
  const pct = c <= 1 ? c * 100 : c;
  return `${pct.toFixed(0)}%`;
}

export const PackingListUploader: React.FC = () => {
  const navigate = useNavigate();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const pollRef = useRef<number | null>(null);

  const [stage, setStage] = useState<Stage>('upload');
  const [taskId, setTaskId] = useState<string | null>(null);
  const [progress, setProgress] = useState({ processed: 0, total: 0, eta: 0 });
  const [results, setResults] = useState<PackingListRow[]>([]);
  const [hasMore, setHasMore] = useState(false);
  const [fileName, setFileName] = useState('');
  const [dragOver, setDragOver] = useState(false);
  const [errorMsg, setErrorMsg] = useState('');
  const [loadingMore, setLoadingMore] = useState(false);

  const clearPolling = useCallback(() => {
    if (pollRef.current != null) {
      window.clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const loadResults = useCallback(async (id: string, start: number) => {
    const { data } = await api.get<ResultsResponse>(`/invoice/task/${id}/results`, {
      params: { start, limit: 50 },
    });
    const batch = data.results || [];
    setResults((prev) => (start === 0 ? batch : [...prev, ...batch]));
    const total = data.total ?? progress.total;
    setHasMore(start + batch.length < total);
    return data;
  }, [progress.total]);

  const finishTask = useCallback(
    async (id: string) => {
      clearPolling();
      try {
        await loadResults(id, 0);
        setStage('results');
      } catch (e: unknown) {
        setErrorMsg(getUserFacingApiError(e, 'Не удалось загрузить результаты.'));
        setStage('error');
      }
    },
    [clearPolling, loadResults],
  );

  const pollTask = useCallback(
    async (id: string) => {
      try {
        const { data } = await api.get<TaskStatus>(`/invoice/task/${id}`);
        setProgress({
          processed: data.processed ?? 0,
          total: data.total ?? 0,
          eta: data.eta_seconds ?? 0,
        });
        if (data.status === 'done') {
          await finishTask(id);
        } else if (data.status === 'error') {
          clearPolling();
          setErrorMsg(data.error || 'Ошибка классификации');
          setStage('error');
        }
      } catch (e: unknown) {
        clearPolling();
        setErrorMsg(getUserFacingApiError(e, 'Не удалось получить статус задачи.'));
        setStage('error');
      }
    },
    [clearPolling, finishTask],
  );

  const startPolling = useCallback(
    (id: string) => {
      clearPolling();
      void pollTask(id);
      pollRef.current = window.setInterval(() => {
        void pollTask(id);
      }, 5000);
    },
    [clearPolling, pollTask],
  );

  const uploadFile = async (file: File) => {
    if (!file.name.toLowerCase().endsWith('.xlsx')) {
      setErrorMsg('Поддерживается только формат .xlsx');
      setStage('error');
      return;
    }

    setFileName(file.name);
    setErrorMsg('');
    setResults([]);
    setHasMore(false);
    setStage('processing');

    const form = new FormData();
    form.append('file', file);
    form.append('classify', 'true');

    try {
      const { data } = await api.post<UploadResponse>('/invoice/upload-packing-list', form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });

      if (!data.task_id) {
        setErrorMsg('Сервер не вернул идентификатор задачи');
        setStage('error');
        return;
      }

      setTaskId(data.task_id);
      setProgress({ processed: 0, total: data.total_rows ?? 0, eta: 0 });

      if (data.status === 'done') {
        if (data.results?.length) {
          setResults(data.results);
          setHasMore(false);
          setStage('results');
        } else {
          await finishTask(data.task_id);
        }
      } else if (data.status === 'processing') {
        startPolling(data.task_id);
      } else {
        setErrorMsg('Неожиданный статус ответа сервера');
        setStage('error');
      }
    } catch (e: unknown) {
      if (axios.isAxiosError(e) && e.response?.status === 401) {
        setErrorMsg('Войдите в систему для загрузки и классификации пакинг-листа.');
      } else {
        setErrorMsg(getUserFacingApiError(e, 'Не удалось загрузить файл.'));
      }
      setStage('error');
    }
  };

  const reset = () => {
    clearPolling();
    setStage('upload');
    setTaskId(null);
    setProgress({ processed: 0, total: 0, eta: 0 });
    setResults([]);
    setHasMore(false);
    setFileName('');
    setErrorMsg('');
  };

  const downloadExcel = () => {
    if (!taskId) return;
    window.open(`/api/invoice/download/${taskId}`, '_blank');
  };

  const openHsCard = (code: string) => {
    const digits = code.replace(/\D/g, '').slice(0, 10);
    if (digits.length < 10) return;
    try {
      sessionStorage.setItem(CC_TNVED_SELECT_CODE_KEY, digits);
    } catch {
      /* ignore */
    }
    navigate('/tnved');
  };

  const loadMore = async () => {
    if (!taskId || loadingMore) return;
    setLoadingMore(true);
    try {
      await loadResults(taskId, results.length);
    } catch (e: unknown) {
      setErrorMsg(getUserFacingApiError(e, 'Не удалось загрузить следующую страницу.'));
    } finally {
      setLoadingMore(false);
    }
  };

  useEffect(() => () => clearPolling(), [clearPolling]);

  if (stage === 'upload') {
    return (
      <div
        className={`rounded-xl border-2 border-dashed p-8 text-center transition-colors ${
          dragOver ? 'border-indigo-500 bg-indigo-50' : 'border-slate-300 bg-white'
        }`}
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragOver(false);
          const file = e.dataTransfer.files?.[0];
          if (file) void uploadFile(file);
        }}
      >
        <p className="text-sm font-medium text-slate-700">Перетащите пакинг-лист .xlsx</p>
        <p className="mt-1 text-xs text-slate-500">Поддерживается: Chinese packing list с фото</p>
        <input
          ref={fileInputRef}
          type="file"
          accept=".xlsx"
          className="hidden"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) void uploadFile(file);
            e.target.value = '';
          }}
        />
        <button
          type="button"
          className="cc-btn-primary mt-4"
          onClick={() => fileInputRef.current?.click()}
        >
          Выбрать файл
        </button>
      </div>
    );
  }

  if (stage === 'processing') {
    const pct = progress.total > 0 ? Math.min(100, Math.round((progress.processed / progress.total) * 100)) : 0;
    return (
      <div className="cc-card-soft space-y-4 p-5">
        <p className="truncate text-sm font-medium text-slate-800">{fileName}</p>
        <div className="h-2 overflow-hidden rounded-full bg-slate-200">
          <div
            className="h-full rounded-full bg-indigo-600 transition-all duration-500"
            style={{ width: `${pct}%` }}
          />
        </div>
        <p className="text-sm text-slate-600">
          Классифицировано {progress.processed} из {progress.total} товаров
        </p>
        <p className="text-xs text-slate-500">Осталось {formatEta(progress.eta)}</p>
      </div>
    );
  }

  if (stage === 'error') {
    return (
      <div className="rounded-xl border border-red-200 bg-red-50 p-5 text-center">
        <p className="text-sm text-red-800">{errorMsg || 'Произошла ошибка'}</p>
        <button type="button" className="cc-btn-primary mt-4" onClick={reset}>
          Попробовать снова
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-slate-600">
          Файл: <span className="font-medium text-slate-800">{fileName}</span>
        </p>
        <div className="flex flex-wrap gap-2">
          <button type="button" className="cc-btn-secondary text-sm" onClick={downloadExcel}>
            Скачать Excel
          </button>
          <button type="button" className="cc-btn-ghost text-sm" onClick={reset}>
            Загрузить новый файл
          </button>
        </div>
      </div>

      <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white">
        <table className="min-w-[960px] w-full text-left text-xs">
          <thead className="bg-slate-50 text-[10px] uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-2 py-2">#</th>
              <th className="px-2 py-2">Артикул</th>
              <th className="px-2 py-2">Название (CN)</th>
              <th className="px-2 py-2">Перевод (RU)</th>
              <th className="px-2 py-2 text-center">📷</th>
              <th className="px-2 py-2">Код ТН ВЭД</th>
              <th className="px-2 py-2">%</th>
              <th className="px-2 py-2">Описание</th>
            </tr>
          </thead>
          <tbody>
            {results.map((row, idx) => (
              <tr key={`${row.row_num ?? idx}-${row.article ?? idx}`} className="border-t border-slate-100">
                <td className="px-2 py-2 text-slate-500">{row.row_num ?? idx + 1}</td>
                <td className="px-2 py-2 font-mono">{row.article || '—'}</td>
                <td className="max-w-[160px] px-2 py-2">{row.name_cn || '—'}</td>
                <td className="max-w-[160px] px-2 py-2">{row.translation_used || '—'}</td>
                <td className="px-2 py-2 text-center">
                  {imageAnalyzed(row) ? (
                    <Camera className="mx-auto h-4 w-4 text-indigo-600" aria-label="Фото проанализировано" />
                  ) : (
                    <span className="text-slate-300">—</span>
                  )}
                </td>
                <td className="px-2 py-2">
                  {row.hs_code ? (
                    <button
                      type="button"
                      className="font-mono text-indigo-700 hover:underline"
                      onClick={() => openHsCard(row.hs_code!)}
                    >
                      {row.hs_code}
                    </button>
                  ) : (
                    '—'
                  )}
                </td>
                <td className="px-2 py-2">{confidencePct(row)}</td>
                <td className="max-w-[220px] px-2 py-2 text-slate-600">
                  {row.hs_description || row.classify_status || '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {hasMore ? (
        <button
          type="button"
          className="cc-btn-secondary text-sm"
          disabled={loadingMore}
          onClick={() => void loadMore()}
        >
          {loadingMore ? 'Загрузка…' : 'Ещё 50'}
        </button>
      ) : null}
    </div>
  );
};

export default PackingListUploader;
