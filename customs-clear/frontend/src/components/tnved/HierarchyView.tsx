import React from 'react';
import { formatCode, fetchTnvedChildren, type TnvedChildItem } from '../../api/tnvedCatalog';
import { PremiumCard } from '../PremiumCard';
import { RateBadges } from './RateBadges';
import { formatTnvedCommodityName, TNVED_COMMODITY_NAME_CLASS } from '../../utils/tnvedDisplayText';

type Props = {
  parentCode: string;
  onSelectCode: (code: string) => void;
  onDrill: (item: TnvedChildItem) => void;
};

function digitsOnly(s: string): string {
  return s.replace(/\D/g, '');
}

function displayCode(item: TnvedChildItem): string {
  if (item.is_codeless) return '';
  return item.display_code || formatCode(digitsOnly(item.code));
}

function CodelessRow({ name, depth = 0 }: { name: string; depth?: number }) {
  return (
    <div
      className="codeless-node flex items-start gap-2 py-2 text-[13px] italic text-cargo-light"
      style={{ paddingLeft: 8 + depth * 16 }}
    >
      <span className="shrink-0">–</span>
      <span className={`${TNVED_COMMODITY_NAME_CLASS} min-w-0 break-words`}>{formatTnvedCommodityName(name)}</span>
    </div>
  );
}

function HierarchyRow({
  item,
  depth,
  preview,
  onSelectCode,
  onDrill,
}: {
  item: TnvedChildItem;
  depth: number;
  preview?: TnvedChildItem[];
  onSelectCode: (code: string) => void;
  onDrill: (item: TnvedChildItem) => void;
}) {
  const [expanded, setExpanded] = React.useState(true);

  if (item.is_codeless && !item.has_children) {
    return <CodelessRow name={item.name} depth={depth} />;
  }

  if (item.is_leaf) {
    return (
      <button
        type="button"
        onClick={() => onSelectCode(digitsOnly(item.code))}
        className="flex w-full items-start justify-between gap-3 rounded-lg border border-transparent px-3 py-2.5 text-left transition-colors hover:border-cargo-trust/30 hover:bg-cargo-trust-light/40"
        style={{ marginLeft: depth * 16 }}
      >
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-[13px] font-semibold text-cargo-clear">{displayCode(item)}</span>
            <RateBadges dutyRate={item.duty_rate || item.import_duty} vatRate={item.vat_rate} />
          </div>
          {item.name ? (
            <p className={`mt-0.5 text-[12px] leading-snug text-cargo-mid ${TNVED_COMMODITY_NAME_CLASS}`}>
              {formatTnvedCommodityName(item.name)}
            </p>
          ) : null}
        </div>
      </button>
    );
  }

  const inlineLeaves = (preview || []).filter((p) => p.is_leaf);
  const hasDeeper = item.has_children && (preview || []).some((p) => !p.is_leaf || p.has_children);

  return (
    <div style={{ marginLeft: depth * 16 }}>
      <PremiumCard
        glow
        onClick={() => {
          if (hasDeeper) onDrill(item);
          else setExpanded((v) => !v);
        }}
      >
        <div className="flex items-start justify-between gap-3 p-4">
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              {!item.is_codeless ? (
                <span className="font-mono text-base font-semibold text-cargo-trust">{displayCode(item)}</span>
              ) : null}
            </div>
            {item.name ? (
              <p className={`mt-1 text-[13px] leading-snug text-cargo-mid ${TNVED_COMMODITY_NAME_CLASS}`}>
                {formatTnvedCommodityName(item.name)}
              </p>
            ) : null}
          </div>
          {item.has_children ? <span className="shrink-0 text-lg text-cargo-light">›</span> : null}
        </div>
      </PremiumCard>

      {expanded && inlineLeaves.length > 0 ? (
        <div className="mt-1 space-y-0.5 border-l border-cargo-border/70 pl-3">
          {inlineLeaves.map((leaf) => (
            <HierarchyRow
              key={leaf.code}
              item={leaf}
              depth={0}
              onSelectCode={onSelectCode}
              onDrill={onDrill}
            />
          ))}
        </div>
      ) : null}

      {expanded && (preview || []).filter((p) => !p.is_leaf).map((child) => (
        <div key={child.code} className="mt-1">
          {child.is_codeless ? (
            <CodelessRow name={child.name} depth={1} />
          ) : (
            <HierarchyRow
              item={child}
              depth={1}
              onSelectCode={onSelectCode}
              onDrill={onDrill}
            />
          )}
        </div>
      ))}
    </div>
  );
}

export const HierarchyView: React.FC<Props> = ({ parentCode, onSelectCode, onDrill }) => {
  const [items, setItems] = React.useState<TnvedChildItem[]>([]);
  const [previews, setPreviews] = React.useState<Record<string, TnvedChildItem[]>>({});
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    void fetchTnvedChildren(parentCode, 'direct')
      .then(async (res) => {
        if (cancelled) return;
        setItems(res.items);
        const parents = res.items.filter((x) => x.has_children && !x.is_leaf);
        const entries = await Promise.all(
          parents.map(async (node) => {
            try {
              const childRes = await fetchTnvedChildren(node.code, 'direct');
              return [node.code, childRes.items] as const;
            } catch {
              return [node.code, []] as const;
            }
          }),
        );
        if (!cancelled) setPreviews(Object.fromEntries(entries));
      })
      .catch(() => {
        if (!cancelled) setError('Не удалось загрузить иерархию');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [parentCode]);

  if (loading) return <p className="py-10 text-center text-sm text-cargo-mid">Загрузка…</p>;
  if (error) return <p className="py-6 text-center text-sm text-cargo-alert">{error}</p>;
  if (items.length === 0) return <p className="py-10 text-center text-sm text-cargo-mid">Нет элементов на этом уровне</p>;

  return (
    <div className="space-y-2">
      {items.map((item, idx) =>
        item.is_codeless && !item.has_children ? (
          <CodelessRow key={`${item.code}-${idx}`} name={item.name} />
        ) : (
          <HierarchyRow
            key={`${item.code}-${idx}`}
            item={item}
            depth={0}
            preview={previews[item.code]}
            onSelectCode={onSelectCode}
            onDrill={onDrill}
          />
        ),
      )}
    </div>
  );
};
