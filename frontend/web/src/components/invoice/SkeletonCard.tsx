function Pulse({ className }: { className: string }) {
  return <div className={`animate-pulse rounded-lg bg-white/[0.06] ${className}`} />;
}

export function SkeletonCard() {
  return (
    <div className="flex flex-col gap-5 rounded-2xl border border-white/[0.07] bg-white/[0.03] p-6">
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1 space-y-2">
          <Pulse className="h-2.5 w-16" />
          <Pulse className="h-5 w-3/4" />
        </div>
        <Pulse className="h-14 w-32 rounded-xl" />
      </div>
      <div className="grid grid-cols-3 divide-x divide-white/[0.06] rounded-xl border border-white/[0.06] bg-black/20">
        {[0, 1, 2].map((i) => (
          <div key={i} className="space-y-2 px-4 py-3">
            <Pulse className="h-2 w-14" />
            <Pulse className="h-5 w-10" />
          </div>
        ))}
      </div>
      <div className="space-y-1.5">
        <Pulse className="h-2.5 w-24 mb-3" />
        <Pulse className="h-10 w-full rounded-xl" />
        <Pulse className="h-10 w-full rounded-xl" />
      </div>
      <Pulse className="h-10 w-full rounded-xl" />
    </div>
  );
}

export function EmptyState() {
  return (
    <div className="col-span-full flex items-center justify-center gap-4 rounded-xl border border-dashed border-white/[0.06] bg-white/[0.01] py-8 text-center">
      <span className="text-xl">📦</span>
      <p className="text-sm text-[#4A5166]">
        Загрузите инвойс и нажмите «Классифицировать» — ИИ присвоит коды ТН ВЭД и рассчитает платежи.
      </p>
    </div>
  );
}
