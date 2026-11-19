import React from 'react';

interface ConfidenceBadgeProps {
  confidence: number; // 0.0 to 1.0 or 0 to 100
  showPercent?: boolean;
  className?: string;
}

export const ConfidenceBadge: React.FC<ConfidenceBadgeProps> = ({
  confidence,
  showPercent = true,
  className = '',
}) => {
  const norm = confidence > 1 ? confidence / 100 : confidence;
  const percent = Math.round(norm * 100);

  let colorClasses = 'bg-rose-950/60 text-rose-300 border-rose-800/60';
  let dotColor = 'bg-rose-400';

  if (percent >= 90) {
    colorClasses = 'bg-emerald-950/60 text-emerald-300 border-emerald-800/60';
    dotColor = 'bg-emerald-400';
  } else if (percent >= 75) {
    colorClasses = 'bg-amber-950/60 text-amber-300 border-amber-800/60';
    dotColor = 'bg-amber-400';
  }

  return (
    <span
      data-testid="confidence-badge"
      className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium border ${colorClasses} ${className}`}
    >
      <span className={`w-1.5 h-1.5 rounded-full ${dotColor}`} />
      {showPercent ? `${percent}%` : norm.toFixed(2)}
    </span>
  );
};
