/**
 * Событие «применить строку из инвойса» в калькулятор (как ручной ввод + расчёт).
 * Подписчик — страница «Платежи» (Calculator).
 */

export type CalculatorPrefillPayload = {
  hs_code: string;
  /** Сумма в валюте инвойса (как в форме «таможенная стоимость») */
  customs_value: number;
  invoice_currency: string;
  net_weight_kg?: number | null;
  /** Если пусто на форме — подставится CN при расчёте */
  country?: string;
};

type Listener = (payload: CalculatorPrefillPayload) => void;

const listeners = new Set<Listener>();

export function subscribeCalculatorPrefill(cb: Listener): () => void {
  listeners.add(cb);
  return () => {
    listeners.delete(cb);
  };
}

export function requestCalculatorPrefill(payload: CalculatorPrefillPayload): void {
  listeners.forEach((cb) => {
    try {
      cb(payload);
    } catch (e) {
      console.error(e);
    }
  });
}
