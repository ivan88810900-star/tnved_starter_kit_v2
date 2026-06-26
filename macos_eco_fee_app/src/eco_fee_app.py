import json
import math
import os
import sqlite3
import sys
import tkinter as tk
from dataclasses import dataclass
from tkinter import ttk, messagebox
import webbrowser


@dataclass(frozen=True)
class EcoFeeGroup:
    id: int
    name: str
    rate_2026: int
    rate_2027: int
    coeff_2026_plus: float

    def rate_for_year(self, year: int) -> int:
        if year == 2026:
            return self.rate_2026
        if year == 2027:
            return self.rate_2027
        raise ValueError(f"Unsupported year: {year}")

    def coeff_for_year(self, year: int) -> float:
        # По ПП РФ №1041 коэффициент задан "с 2026 года" (используем одинаково для 2026–2027)
        if year in (2026, 2027):
            return self.coeff_2026_plus
        raise ValueError(f"Unsupported year: {year}")


@dataclass(frozen=True)
class RatesDataset:
    title: str
    unit: str
    source_title: str
    source_url: str
    retrieved_at: str
    coefficients_source_title: str
    coefficients_source_url: str
    groups: list[EcoFeeGroup]
    assumptions_note_ru: str


@dataclass(frozen=True)
class HSCodeHit:
    code: str
    title_ru: str


class TnvedSearcher:
    def __init__(self, db_path: str):
        # Read-only connection (when supported)
        uri = f"file:{db_path}?mode=ro"
        self._conn = sqlite3.connect(uri, uri=True)
        self._conn.row_factory = sqlite3.Row

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass

    @staticmethod
    def _tokenize(q: str) -> list[str]:
        parts = [p.strip().lower() for p in q.replace(",", " ").split()]
        return [p for p in parts if len(p) >= 2]

    @staticmethod
    def _digits_prefix(q: str) -> str | None:
        digits = "".join(ch for ch in q if ch.isdigit())
        if len(digits) >= 2:
            return digits
        return None

    def search(self, query: str, limit: int = 25) -> list[HSCodeHit]:
        q = (query or "").strip()
        if not q:
            return []

        digits = self._digits_prefix(q)
        tokens = self._tokenize(q)

        # Prefer code prefix search when user types digits
        if digits and (not tokens or q.replace(" ", "").isdigit()):
            like_code = digits + "%"
            rows = self._conn.execute(
                """
                SELECT code, COALESCE(title_ru, '') AS title_ru
                FROM hs_codes
                WHERE code LIKE ?
                ORDER BY LENGTH(code) ASC, code ASC
                LIMIT ?
                """,
                (like_code, int(limit)),
            ).fetchall()
            return [HSCodeHit(code=str(r["code"]), title_ru=str(r["title_ru"])) for r in rows]

        # Text search: all tokens must match in RU or EN title
        # (simple LIKE, enough for ~20k rows)
        where = []
        params: list[str | int] = []
        for t in tokens[:6]:
            like = f"%{t}%"
            where.append("(LOWER(COALESCE(title_ru,'')) LIKE ? OR LOWER(COALESCE(title_en,'')) LIKE ?)")
            params.extend([like, like])

        # Optional: also allow partial code prefix if user mixed words+digits
        if digits:
            where.append("code LIKE ?")
            params.append(digits + "%")

        if not where:
            return []

        sql = f"""
        SELECT code, COALESCE(title_ru, '') AS title_ru
        FROM hs_codes
        WHERE {' AND '.join(where)}
        ORDER BY LENGTH(code) ASC, code ASC
        LIMIT ?
        """
        params.append(int(limit))
        rows = self._conn.execute(sql, params).fetchall()
        return [HSCodeHit(code=str(r["code"]), title_ru=str(r["title_ru"])) for r in rows]


def _resource_path(relative_path: str) -> str:
    """
    Support running from source and from a bundled app (py2app/PyInstaller style).
    """
    base_path = getattr(sys, "_MEIPASS", None)  # type: ignore[attr-defined]
    if base_path:
        return os.path.join(base_path, relative_path)
    return os.path.join(os.path.dirname(os.path.dirname(__file__)), relative_path)

def _repo_root_path(filename: str) -> str:
    # macos_eco_fee_app/src -> macos_eco_fee_app -> repo root
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    return os.path.join(repo_root, filename)


def load_tnved_mapping() -> dict:
    """Загружает маппинг ТН ВЭД → группа эко-сбора (ПП РФ №2414)."""
    path = _resource_path(os.path.join("data", "tnved_to_eco_group.json"))
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def resolve_eco_group(code: str, mapping: dict, groups_by_id: dict[int, EcoFeeGroup]) -> EcoFeeGroup | None:
    """
    Определяет группу эко-сбора по коду ТН ВЭД.
    Сначала ищет по префиксу (от длинного к короткому), затем по главе (2 цифры).
    """
    code_clean = "".join(c for c in code if c.isdigit())
    if not code_clean:
        return None

    by_prefix = mapping.get("by_prefix", {})
    fallback = mapping.get("fallback_by_chapter", {})

    for length in range(min(6, len(code_clean)), 0, -1):
        prefix = code_clean[:length]
        gid = by_prefix.get(prefix)
        if gid is not None:
            return groups_by_id.get(int(gid))

    chapter = code_clean[:2] if len(code_clean) >= 2 else code_clean
    gid = fallback.get(chapter)
    if gid is not None:
        return groups_by_id.get(int(gid))
    return None


def load_rates() -> RatesDataset:
    json_path = _resource_path(os.path.join("data", "eco_fee_rates_2026_2027.json"))
    with open(json_path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    meta = raw["meta"]
    legal_act = meta["legal_act"]
    coeff_meta = meta.get("coefficients_2026_plus", {}) or {}
    coeff_values = (coeff_meta.get("values", {}) or {})
    assumptions = meta.get("calculation_assumptions", {}) or {}

    groups: list[EcoFeeGroup] = []
    for g in raw["groups"]:
        rates = g["rates"]
        gid = int(g["id"])
        coeff = float(coeff_values.get(str(gid), 1.0))
        groups.append(
            EcoFeeGroup(
                id=gid,
                name=str(g["name"]),
                rate_2026=int(rates["2026"]),
                rate_2027=int(rates["2027"]),
                coeff_2026_plus=coeff,
            )
        )

    return RatesDataset(
        title=str(meta.get("title", "")),
        unit=str(meta.get("unit", "")),
        source_title=str(legal_act.get("source_title", "")),
        source_url=str(legal_act.get("source_url", "")),
        retrieved_at=str(meta.get("retrieved_at", "")),
        coefficients_source_title=str(coeff_meta.get("source_title", "")),
        coefficients_source_url=str(coeff_meta.get("source_url", "")),
        groups=sorted(groups, key=lambda x: x.id),
        assumptions_note_ru=str(assumptions.get("note_ru", "")),
    )


def parse_float(value: str) -> float:
    v = value.strip().replace(" ", "").replace(",", ".")
    if not v:
        return float("nan")
    return float(v)


def format_rub(value: float) -> str:
    if math.isnan(value) or math.isinf(value):
        return "—"
    return f"{value:,.2f}".replace(",", " ").replace(".", ",")


class EcoFeeApp(ttk.Frame):
    def __init__(self, master: tk.Tk, dataset: RatesDataset):
        super().__init__(master, padding=16)
        self.dataset = dataset
        self.searcher: TnvedSearcher | None = None
        self.tnved_mapping: dict = {}
        self._groups_by_id: dict[int, EcoFeeGroup] = {g.id: g for g in dataset.groups}

        self.var_hs_query = tk.StringVar(value="")
        self.var_hs_selected = tk.StringVar(value="—")
        self._hs_results: list[HSCodeHit] = []
        self._hs_debounce_after_id: str | None = None
        self._selected_hit: HSCodeHit | None = None
        self._selected_group: EcoFeeGroup | None = None

        self.var_year = tk.StringVar(value="2026")
        self.var_mass_kg = tk.StringVar(value="1000")
        self.var_group_info = tk.StringVar(value="Выберите товар по коду или наименованию.")

        self._build_ui()
        self._load_tnved_mapping()
        self._init_tnved_search()
        self._wire_events()
        self._recalc()

    def _build_ui(self) -> None:
        self.master.title("Эко-сбор РФ — калькулятор (2026–2027)")
        self.master.minsize(820, 520)

        # Layout grid
        self.grid(row=0, column=0, sticky="nsew")
        self.master.columnconfigure(0, weight=1)
        self.master.rowconfigure(0, weight=1)

        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=1)

        title = ttk.Label(self, text="Расчёт экологического сбора (РФ)", font=("SF Pro Text", 18, "bold"))
        subtitle = ttk.Label(
            self,
            text="Ставки 2026–2027 и коэффициенты (с 2026 года) — из ПП РФ №1041 (ред. от 25.12.2025).",
            foreground="#555",
        )
        title.grid(row=0, column=0, columnspan=2, sticky="w")
        subtitle.grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 16))

        # Left: Inputs
        inputs = ttk.LabelFrame(self, text="Параметры", padding=12)
        inputs.grid(row=2, column=0, sticky="nsew", padx=(0, 8))
        inputs.columnconfigure(1, weight=1)

        ttk.Label(inputs, text="Поиск ТН ВЭД (код или несколько слов)").grid(row=0, column=0, sticky="w")
        ttk.Entry(inputs, textvariable=self.var_hs_query).grid(row=0, column=1, sticky="ew")

        tree_frame = ttk.Frame(inputs)
        tree_frame.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=(8, 0))
        tree_frame.columnconfigure(0, weight=1)
        tree_frame.rowconfigure(0, weight=1)

        self.hits_tree = ttk.Treeview(
            tree_frame,
            columns=("code", "title"),
            show="headings",
            height=6,
            selectmode="browse",
        )
        self.hits_tree.heading("code", text="Код")
        self.hits_tree.heading("title", text="Наименование (RU)")
        self.hits_tree.column("code", width=110, minwidth=90, anchor="w", stretch=False)
        self.hits_tree.column("title", width=1, anchor="w", stretch=True)

        yscroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self.hits_tree.yview)
        self.hits_tree.configure(yscrollcommand=yscroll.set)

        self.hits_tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        inputs.rowconfigure(1, weight=1)

        self.lbl_hs_selected = ttk.Label(inputs, textvariable=self.var_hs_selected, foreground="#555", wraplength=380)
        self.lbl_hs_selected.grid(row=2, column=0, columnspan=2, sticky="w", pady=(8, 0))

        ttk.Separator(inputs).grid(row=3, column=0, columnspan=2, sticky="ew", pady=12)

        ttk.Label(inputs, text="Год").grid(row=4, column=0, sticky="w")
        year_box = ttk.Combobox(inputs, textvariable=self.var_year, values=["2026", "2027"], state="readonly", width=10)
        year_box.grid(row=4, column=1, sticky="w")

        ttk.Label(inputs, text="Группа (авто)").grid(row=5, column=0, sticky="w", pady=(8, 0))
        self.lbl_group_info = ttk.Label(inputs, textvariable=self.var_group_info, foreground="#555", wraplength=360)
        self.lbl_group_info.grid(row=5, column=1, sticky="w", pady=(8, 0))

        ttk.Label(inputs, text="Масса (кг)").grid(row=6, column=0, sticky="w", pady=(8, 0))
        self.entry_mass = ttk.Entry(inputs, textvariable=self.var_mass_kg)
        self.entry_mass.grid(row=6, column=1, sticky="ew", pady=(8, 0))

        # Right: Output
        output = ttk.LabelFrame(self, text="Результат", padding=12)
        output.grid(row=2, column=1, sticky="nsew", padx=(8, 0))
        output.columnconfigure(1, weight=1)

        self.lbl_rate = ttk.Label(output, text="—")
        self.lbl_coeff = ttk.Label(output, text="—")
        self.lbl_payable_mass = ttk.Label(output, text="—")
        self.lbl_fee = ttk.Label(output, text="—", font=("SF Pro Text", 18, "bold"))
        self.lbl_breakdown = ttk.Label(output, text="—", foreground="#555", wraplength=360)

        ttk.Label(output, text="Ставка (руб/т)").grid(row=0, column=0, sticky="w")
        self.lbl_rate.grid(row=0, column=1, sticky="e")

        ttk.Label(output, text="Коэффициент (с 2026)").grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.lbl_coeff.grid(row=1, column=1, sticky="e", pady=(8, 0))

        ttk.Label(output, text="Масса к оплате (кг)").grid(row=2, column=0, sticky="w", pady=(8, 0))
        self.lbl_payable_mass.grid(row=2, column=1, sticky="e", pady=(8, 0))

        ttk.Label(output, text="Экосбор (руб)").grid(row=3, column=0, sticky="w", pady=(12, 0))
        self.lbl_fee.grid(row=3, column=1, sticky="e", pady=(12, 0))

        ttk.Label(output, text="Формула").grid(row=4, column=0, sticky="w", pady=(12, 0))
        self.lbl_breakdown.grid(row=4, column=1, sticky="e", pady=(12, 0))

        buttons = ttk.Frame(output)
        buttons.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(16, 0))
        buttons.columnconfigure(0, weight=1)
        buttons.columnconfigure(1, weight=1)

        ttk.Button(buttons, text="Копировать расчёт", command=self._copy_result).grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ttk.Button(buttons, text="Открыть источник ставок", command=self._open_source).grid(row=0, column=1, sticky="ew", padx=(8, 0))

        footer = ttk.Label(self, text=self._footer_text(), foreground="#666", wraplength=780)
        footer.grid(row=3, column=0, columnspan=2, sticky="w", pady=(16, 0))

    def _footer_text(self) -> str:
        parts = [
            f"Ставки: {self.dataset.source_title}.",
            f"Коэффициенты: {self.dataset.coefficients_source_title}.",
            f"Дата выгрузки: {self.dataset.retrieved_at}.",
        ]
        if self.dataset.assumptions_note_ru:
            parts.append(self.dataset.assumptions_note_ru)
        return " ".join([p for p in parts if p])

    def _load_tnved_mapping(self) -> None:
        try:
            self.tnved_mapping = load_tnved_mapping()
        except Exception as e:
            self.tnved_mapping = {}
            print(f"Не удалось загрузить маппинг ТН ВЭД: {e}")

    def _init_tnved_search(self) -> None:
        """
        Подключаем локальную базу ТН ВЭД (repo root /tnved.db) и включаем автоподсказки.
        """
        db_path = _repo_root_path("tnved.db")
        if not os.path.exists(db_path):
            self.var_hs_selected.set("База ТН ВЭД не найдена (ожидался файл tnved.db в корне репозитория).")
            self.hits_tree.configure(selectmode="none")
            return

        try:
            self.searcher = TnvedSearcher(db_path)
            self.var_hs_selected.set("—")
        except Exception as e:
            self.searcher = None
            self.var_hs_selected.set(f"Не удалось открыть tnved.db: {e}")
            self.hits_tree.configure(selectmode="none")
            return

        self.var_hs_query.trace_add("write", lambda *_: self._schedule_hs_search())
        self.hits_tree.bind("<<TreeviewSelect>>", lambda _: self._on_hs_select())
        self.hits_tree.bind("<Double-Button-1>", lambda _: self._on_hs_select(force=True))
        self.hits_tree.bind("<Return>", lambda _: self._on_hs_select(force=True))

    def _schedule_hs_search(self) -> None:
        if not self.searcher:
            return
        if self._hs_debounce_after_id:
            try:
                self.after_cancel(self._hs_debounce_after_id)
            except Exception:
                pass
        self._hs_debounce_after_id = self.after(150, self._run_hs_search)

    def _run_hs_search(self) -> None:
        if not self.searcher:
            return
        q = self.var_hs_query.get().strip()
        if len(q) < 2:
            self._hs_results = []
            for iid in self.hits_tree.get_children(""):
                self.hits_tree.delete(iid)
            self.var_hs_selected.set("—")
            return
        try:
            self._hs_results = self.searcher.search(q, limit=25)
        except Exception as e:
            self._hs_results = []
            for iid in self.hits_tree.get_children(""):
                self.hits_tree.delete(iid)
            self.var_hs_selected.set(f"Ошибка поиска: {e}")
            return

        for iid in self.hits_tree.get_children(""):
            self.hits_tree.delete(iid)
        for i, hit in enumerate(self._hs_results):
            title = hit.title_ru.strip() or "(без названия)"
            self.hits_tree.insert("", "end", iid=str(i), values=(hit.code, title))

        if not self._hs_results:
            self.var_hs_selected.set("Ничего не найдено.")
        else:
            self.var_hs_selected.set("Выберите позицию из списка подсказок (Enter — применить).")

    def _on_hs_select(self, force: bool = False) -> None:
        if not self._hs_results:
            return
        selection = self.hits_tree.selection()
        if not selection:
            return
        idx = int(selection[0])
        if idx < 0 or idx >= len(self._hs_results):
            return
        hit = self._hs_results[idx]
        title = hit.title_ru.strip() or "(без названия)"
        self.var_hs_selected.set(f"Выбрано: {hit.code} — {title}")
        self._selected_hit = hit

        group = resolve_eco_group(hit.code, self.tnved_mapping, self._groups_by_id)
        self._selected_group = group
        if group:
            self.var_group_info.set(f"{group.id} — {group.name}")
        else:
            self.var_group_info.set("Группа не найдена в маппинге ТН ВЭД → группа (ПП РФ №2414).")

        if force:
            try:
                self.entry_mass.focus_set()
            except Exception:
                pass
        self._recalc()

    def _wire_events(self) -> None:
        for v in [self.var_year, self.var_mass_kg]:
            v.trace_add("write", lambda *_: self._recalc())

    def _recalc(self) -> None:
        group = self._selected_group
        if not group:
            self._set_error("Выберите товар по коду ТН ВЭД из списка подсказок.")
            return

        try:
            year = int(self.var_year.get())
        except Exception:
            year = 2026

        try:
            mass_kg = parse_float(self.var_mass_kg.get())
        except Exception:
            mass_kg = float("nan")

        if math.isnan(mass_kg) or mass_kg < 0:
            self._set_error("Некорректная масса (кг).")
            return

        rate_rub_per_ton = float(group.rate_for_year(year))
        coeff = float(group.coeff_for_year(year))

        # В этой версии считаем сценарий "утилизация не обеспечена" → к оплате 100% массы
        payable_mass_kg = mass_kg
        payable_mass_t = payable_mass_kg / 1000.0

        fee = rate_rub_per_ton * payable_mass_t * coeff

        self.lbl_rate.configure(text=f"{int(rate_rub_per_ton):,}".replace(",", " "))
        self.lbl_coeff.configure(text=str(coeff).replace(".", ","))
        self.lbl_payable_mass.configure(text=f"{payable_mass_kg:,.3f}".replace(",", " ").replace(".", ","))
        self.lbl_fee.configure(text=format_rub(fee))

        breakdown = f"{int(rate_rub_per_ton)} × ({payable_mass_kg:.3f} кг / 1000) × {coeff:g}"
        self.lbl_breakdown.configure(text=breakdown.replace(".", ","))

    def _set_error(self, msg: str) -> None:
        self.lbl_rate.configure(text="—")
        self.lbl_coeff.configure(text="—")
        self.lbl_payable_mass.configure(text="—")
        self.lbl_fee.configure(text="—")
        self.lbl_breakdown.configure(text=msg)

    def _copy_result(self) -> None:
        group = self._selected_group
        if not group:
            messagebox.showwarning("Нет данных", "Сначала выберите товар по коду ТН ВЭД.")
            return
        try:
            year = int(self.var_year.get())
        except Exception:
            year = 2026

        coeff = group.coeff_for_year(year)
        hit_info = ""
        if self._selected_hit:
            hit_info = f"Код ТН ВЭД: {self._selected_hit.code} — {self._selected_hit.title_ru or ''}\n"
        payload = (
            f"Эко-сбор РФ (год {year})\n"
            f"{hit_info}"
            f"Группа: {group.id} — {group.name}\n"
            f"Масса: {self.var_mass_kg.get()} кг\n"
            f"Сценарий: утилизация не обеспечена (к оплате 100% массы)\n"
            f"Ставка: {group.rate_for_year(year)} руб/т\n"
            f"Коэффициент (с 2026): {str(coeff).replace('.', ',')}\n"
            f"Итого: {self.lbl_fee.cget('text')} руб\n"
            f"Источник ставок: {self.dataset.source_url}\n"
        )

        self.master.clipboard_clear()
        self.master.clipboard_append(payload)
        messagebox.showinfo("Скопировано", "Расчёт скопирован в буфер обмена.")

    def _open_source(self) -> None:
        try:
            webbrowser.open(self.dataset.source_url)
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось открыть ссылку:\n{e}")


def main() -> None:
    dataset = load_rates()

    root = tk.Tk()
    try:
        # Use ttk theme if available
        style = ttk.Style(root)
        if "aqua" in style.theme_names():
            style.theme_use("aqua")
    except Exception:
        pass

    app = EcoFeeApp(root, dataset)
    app.mainloop()


if __name__ == "__main__":
    main()

