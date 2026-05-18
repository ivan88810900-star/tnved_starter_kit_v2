import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../../api/client';
import { getAdminToken } from '../../api/adminToken';
import { getApiErrorMessage } from '../../api/error';

type JobInfo = {
  id?: number;
  status?: string;
  total_files?: number;
  processed_files?: number;
  measures_applied?: number;
  current_file?: string;
  error_message?: string;
};

type StatusResp = {
  job?: JobInfo | null;
  worker_busy?: boolean;
};

export function BulkNormativeImport() {
  const [err, setErr] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [job, setJob] = useState<JobInfo | null>(null);
  const [workerBusy, setWorkerBusy] = useState(false);
  const [activeJobId, setActiveJobId] = useState<number | null>(null);
  const [uploading, setUploading] = useState(false);
  const [starting, setStarting] = useState(false);
  const folderInputRef = useRef<HTMLInputElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const token = () => getAdminToken().trim();

  const loadStatus = useCallback(
    async (jobId?: number | null) => {
      const t = token();
      if (!t) {
        setErr('Нужен X-Admin-Token (например, на странице «Платежи»).');
        return;
      }
      setErr(null);
      try {
        const q = jobId != null ? `?job_id=${jobId}` : '';
        const { data } = await api.get<StatusResp>(`/v1/admin/import/bulk/status${q}`, {
          headers: { 'X-Admin-Token': t },
        });
        setJob(data.job ?? null);
        setWorkerBusy(Boolean(data.worker_busy));
      } catch (e) {
        setErr(getApiErrorMessage(e, 'Ошибка статуса импорта'));
      }
    },
    [],
  );

  useEffect(() => {
    void loadStatus(activeJobId);
  }, [loadStatus, activeJobId]);

  useEffect(() => {
    const st = job?.status || '';
    if (st !== 'running' && st !== 'queued') return undefined;
    const id = window.setInterval(() => void loadStatus(activeJobId ?? job?.id ?? null), 2000);
    return () => window.clearInterval(id);
  }, [job?.status, job?.id, activeJobId, loadStatus]);

  const onUpload = async (list: FileList | null) => {
    if (!list?.length) return;
    const t = token();
    if (!t) {
      setErr('Нужен X-Admin-Token для загрузки.');
      return;
    }
    setUploading(true);
    setErr(null);
    setMsg(null);
    try {
      const fd = new FormData();
      for (let i = 0; i < list.length; i += 1) {
        fd.append('files', list[i]!);
      }
      const { data } = await api.post<{ saved?: string[]; count?: number; directory?: string }>(
        '/v1/admin/import/bulk/upload',
        fd,
        {
          headers: { 'X-Admin-Token': t },
        },
      );
      setMsg(`Загружено файлов: ${data.count ?? 0}. Каталог на сервере: ${data.directory ?? '—'}`);
    } catch (e) {
      setErr(getApiErrorMessage(e, 'Ошибка загрузки'));
    } finally {
      setUploading(false);
      if (folderInputRef.current) folderInputRef.current.value = '';
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  const startImport = async () => {
    const t = token();
    if (!t) {
      setErr('Нужен X-Admin-Token.');
      return;
    }
    setStarting(true);
    setErr(null);
    setMsg(null);
    try {
      const { data } = await api.post<{ job_id?: number }>(
        '/v1/admin/import/bulk/start',
        null,
        {
          params: { delay_sec: 4, skip_checkpoint: false },
          headers: { 'X-Admin-Token': t },
        },
      );
      const jid = data.job_id ?? null;
      setActiveJobId(jid);
      setMsg(`Запущена задача импорта #${jid ?? '?'}`);
      await loadStatus(jid);
    } catch (e) {
      setErr(getApiErrorMessage(e, 'Не удалось запустить импорт'));
    } finally {
      setStarting(false);
    }
  };

  const total = job?.total_files ?? 0;
  const done = job?.processed_files ?? 0;
  const pct = total > 0 ? Math.min(100, Math.round((done / total) * 100)) : 0;
  const measures = job?.measures_applied ?? 0;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="max-w-2xl text-[12px] leading-relaxed text-slate-500">
          Массовая загрузка базы: PDF / Word / HTML в каталог сервера, затем фоновый разбор через Gemini с паузами и
          чекпоинтами. Акцизы и пошлины пишутся в <span className="font-mono text-slate-600">hs_rates</span>, нетарифка
          и запреты — в <span className="font-mono text-slate-600">non_tariff_measures</span>, спецпошлины — в{' '}
          <span className="font-mono text-slate-600">special_duties</span>.
        </p>
        <Link to="/admin/system" className="cc-btn-ghost text-[11px]">
          ← Состояние системы
        </Link>
      </div>

      {err && (
        <div className="rounded-lg border border-red-500/30 bg-red-950/40 px-3 py-2 text-[12px] text-red-200">{err}</div>
      )}
      {msg && (
        <div className="rounded-lg border border-emerald-500/25 bg-emerald-950/30 px-3 py-2 text-[12px] text-emerald-100">
          {msg}
        </div>
      )}

      <div className="rounded-xl border border-white/[0.08] bg-black/20 px-3 py-3">
        <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-400">Файлы на сервер</div>
        <p className="mt-1 text-[11px] text-slate-500">
          Локальный CLI: <span className="font-mono text-slate-300">python3 scripts/bulk_ai_importer.py</span> из каталога{' '}
          <span className="font-mono text-slate-300">backend/</span> (переменные GEMINI_API_KEY, ADMIN не нужен для CLI).
        </p>
        <div className="mt-2 flex flex-wrap gap-2">
          <input
            ref={folderInputRef}
            type="file"
            className="hidden"
            {...{ webkitdirectory: '' }}
            multiple
            onChange={(e) => void onUpload(e.target.files)}
          />
          <input
            ref={fileInputRef}
            type="file"
            className="hidden"
            accept=".pdf,.docx,.html,.htm"
            multiple
            onChange={(e) => void onUpload(e.target.files)}
          />
          <button
            type="button"
            className="cc-btn-ghost text-[11px]"
            disabled={uploading}
            onClick={() => folderInputRef.current?.click()}
          >
            {uploading ? 'Загрузка…' : 'Выбрать папку'}
          </button>
          <button
            type="button"
            className="cc-btn-ghost text-[11px]"
            disabled={uploading}
            onClick={() => fileInputRef.current?.click()}
          >
            Выбрать файлы
          </button>
          <button
            type="button"
            className="rounded-lg border border-sky-500/35 bg-sky-600/25 px-3 py-1.5 text-[11px] font-medium text-sky-100 hover:bg-sky-600/35 disabled:opacity-50"
            disabled={starting || workerBusy}
            onClick={() => void startImport()}
          >
            {workerBusy ? 'Импорт выполняется…' : starting ? 'Запуск…' : 'Запустить обработку на сервере'}
          </button>
          <button type="button" className="cc-btn-ghost text-[11px]" onClick={() => void loadStatus(activeJobId)}>
            Обновить статус
          </button>
        </div>
      </div>

      <div className="rounded-xl border border-white/[0.08] bg-black/20 px-3 py-3">
        <div className="text-[11px] font-semibold text-slate-300">Прогресс</div>
        <div className="mt-2 h-2.5 w-full overflow-hidden rounded-full bg-white/[0.08]">
          <div
            className="h-full rounded-full bg-gradient-to-r from-sky-600 to-emerald-500 transition-all duration-500"
            style={{ width: `${pct}%` }}
          />
        </div>
        <p className="mt-2 font-mono text-[12px] text-slate-200">
          Обработано {done} из {total || '—'} документов. Найдено / применено мер (строк UPSERT): {measures}.
        </p>
        {job?.status && (
          <p className="mt-1 text-[11px] text-slate-500">
            Статус: <span className="text-slate-300">{job.status}</span>
            {job.id != null ? (
              <span className="ml-2">
                job_id=<span className="font-mono">{job.id}</span>
              </span>
            ) : null}
          </p>
        )}
        {job?.current_file ? (
          <p className="mt-1 truncate text-[10px] text-slate-500">
            Текущий файл: <span className="font-mono text-slate-400">{job.current_file}</span>
          </p>
        ) : null}
        {job?.error_message ? (
          <p className="mt-2 text-[11px] text-amber-200/90">Ошибка: {job.error_message}</p>
        ) : null}
      </div>
    </div>
  );
}
