import { type ReactNode } from 'react';
import { motion } from 'framer-motion';
import { useMouseGlow } from '../hooks/useMouseGlow';

interface Props {
  children: ReactNode;
  onClick?: () => void;
  glow?: boolean;
  index?: number;
}

export function PremiumCard({ children, onClick, glow = true, index = 0 }: Props) {
  const { ref, onMouseMove } = useMouseGlow();

  return (
    <motion.div
      ref={ref}
      onMouseMove={glow ? onMouseMove : undefined}
      onClick={onClick}
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{
        duration: 0.4,
        delay: index * 0.07,
        ease: [0.16, 1, 0.3, 1],
      }}
      whileHover={{ y: -2, scale: 1.005 }}
      className="premium-card"
      style={{
        position: 'relative',
        background: 'var(--cargo-surface)',
        border: '1px solid var(--cargo-border)',
        borderRadius: 'var(--radius-md)',
        boxShadow: 'var(--shadow-sm)',
        cursor: onClick ? 'pointer' : 'default',
        overflow: 'hidden',
        transition: 'box-shadow var(--duration-base) var(--ease-out-quint), border-color var(--duration-base)',
      }}
    >
      {glow && (
        <div
          className="premium-card-glow"
          style={{
            position: 'absolute',
            inset: 0,
            background:
              'radial-gradient(400px circle at var(--glow-x, 50%) var(--glow-y, 50%), var(--glow-trust), transparent 60%)',
            opacity: 0,
            transition: 'opacity var(--duration-base)',
            pointerEvents: 'none',
          }}
        />
      )}
      {children}
    </motion.div>
  );
}
