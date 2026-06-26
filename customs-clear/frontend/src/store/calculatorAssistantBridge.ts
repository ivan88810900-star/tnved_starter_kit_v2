import type { AssistantCalculationCurrentContext } from '../types/api.types';

type VoidFn = () => void;

const navListeners = new Set<VoidFn>();
const ctxListeners = new Set<VoidFn>();

export type AssistantNavigationJob = {
  id: number;
  /** Подставить текст в поле чата (старый сценарий) */
  chatPrefillText?: string;
  /** Открытие из калькулятора: контекст + приветствие на странице ассистента */
  calculatorConsult?: { context: AssistantCalculationCurrentContext };
};

const navigationQueue: AssistantNavigationJob[] = [];
let jobCounter = 0;

let calculationContext: AssistantCalculationCurrentContext | null = null;

export function setAssistantCalculationContext(ctx: AssistantCalculationCurrentContext | null): void {
  calculationContext = ctx;
  ctxListeners.forEach((fn) => fn());
}

export function getAssistantCalculationContext(): AssistantCalculationCurrentContext | null {
  return calculationContext;
}

export function subscribeAssistantCalculationContext(fn: VoidFn): () => void {
  ctxListeners.add(fn);
  return () => ctxListeners.delete(fn);
}

/** Открыть вкладку ассистента и передать текст в поле чата. */
export function requestAssistantWithPrefill(message: string): void {
  const text = (message || '').trim();
  if (!text) return;
  jobCounter += 1;
  navigationQueue.push({ id: jobCounter, chatPrefillText: text });
  navListeners.forEach((fn) => fn());
}

/** Открыть ассистента с контекстом расчёта (приветствие «Вижу ваш расчёт…»). */
export function requestAssistantCalculatorConsult(context: AssistantCalculationCurrentContext): void {
  setAssistantCalculationContext(context);
  jobCounter += 1;
  navigationQueue.push({ id: jobCounter, calculatorConsult: { context } });
  navListeners.forEach((fn) => fn());
}

export function drainAssistantNavigationJob(): AssistantNavigationJob | null {
  return navigationQueue.shift() ?? null;
}

/** @deprecated используйте drainAssistantNavigationJob */
export function drainAssistantPrefillJob(): AssistantNavigationJob | null {
  return drainAssistantNavigationJob();
}

export function subscribeAssistantNavigation(fn: VoidFn): () => void {
  navListeners.add(fn);
  return () => navListeners.delete(fn);
}
