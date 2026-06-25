import { useCountUp } from '../hooks/useCountUp';

interface Props {
  value: number;
  format?: 'currency' | 'percent' | 'number';
  duration?: number;
}

export function AnimatedNumber({ value, format = 'number', duration = 800 }: Props) {
  const animated = useCountUp(value, duration);

  const formatted = (() => {
    const rounded = Math.round(animated);
    if (format === 'currency') {
      return new Intl.NumberFormat('ru-RU').format(rounded) + ' ₽';
    }
    if (format === 'percent') {
      return animated.toFixed(1) + '%';
    }
    return new Intl.NumberFormat('ru-RU').format(rounded);
  })();

  return <span className="tabular-nums">{formatted}</span>;
}
