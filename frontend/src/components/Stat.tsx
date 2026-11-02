import type { ReactNode } from 'react';

export default function Stat({
  icon,
  value,
  label,
  detail,
}: {
  icon: ReactNode;
  value: number | string;
  label: string;
  detail: string;
}) {
  return (
    <div className="stat-card">
      <span className="stat-icon">{icon}</span>
      <strong>{value}</strong>
      <h3>{label}</h3>
      <p>{detail}</p>
    </div>
  );
}
