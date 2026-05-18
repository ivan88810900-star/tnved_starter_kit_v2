import { useRef, useState, type DragEvent } from "react";
import { CloudUpload, X, FileText } from "lucide-react";
import { cn } from "../../lib/utils";

type UploadZoneProps = {
  file: File | null;
  onFileChange: (file: File | null) => void;
};

const ACCEPTED = ".xlsx,.xls,.csv,.pdf,.jpg,.jpeg,.png";

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function UploadZone({ file, onFileChange }: UploadZoneProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);

  const handleDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragging(false);
    const dropped = e.dataTransfer.files?.[0];
    if (dropped) onFileChange(dropped);
  };

  if (file) {
    return (
      <div className="flex items-center gap-4 rounded-xl border border-[#00F0FF]/20 bg-[#00F0FF]/[0.04] px-4 py-3">
        <FileText size={18} className="shrink-0 text-[#00F0FF]" />
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium text-white">{file.name}</p>
          <p className="text-xs text-[#4A5166]">{formatSize(file.size)}</p>
        </div>
        <button
          type="button"
          onClick={() => onFileChange(null)}
          className="rounded-lg p-1.5 text-[#4A5166] transition hover:bg-white/[0.08] hover:text-white"
          aria-label="Удалить файл"
        >
          <X size={14} />
        </button>
      </div>
    );
  }

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => inputRef.current?.click()}
      onKeyDown={(e) => e.key === "Enter" && inputRef.current?.click()}
      onDrop={handleDrop}
      onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
      onDragLeave={(e) => { e.preventDefault(); setDragging(false); }}
      className={cn(
        "flex cursor-pointer flex-col items-center justify-center gap-3 rounded-xl border-2 border-dashed px-6 py-9 text-center transition-all duration-200",
        dragging
          ? "border-[#00F0FF]/50 bg-[#00F0FF]/[0.05]"
          : "border-white/[0.1] bg-black/20 hover:border-white/[0.18] hover:bg-black/30",
      )}
    >
      <CloudUpload
        size={28}
        className={cn("transition-colors", dragging ? "text-[#00F0FF]" : "text-[#4A5166]")}
        style={dragging ? { filter: "drop-shadow(0 0 8px #00F0FF)" } : undefined}
      />
      <div>
        <p className="text-sm font-medium text-[#8B92A8]">
          Перетащите файл или{" "}
          <span className="text-[#00F0FF] underline underline-offset-2">выберите на диске</span>
        </p>
        <p className="mt-1 text-xs text-[#4A5166]">Excel, CSV, PDF, JPEG/PNG · до 20 МБ</p>
      </div>
      <input
        ref={inputRef}
        type="file"
        accept={ACCEPTED}
        className="hidden"
        onChange={(e) => onFileChange(e.target.files?.[0] ?? null)}
      />
    </div>
  );
}
