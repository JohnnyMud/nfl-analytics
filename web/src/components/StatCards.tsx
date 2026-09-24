import type { StatCard } from "../lib/statCards";

type StatCardsProps = {
  cards: StatCard[];
};

export function StatCards({ cards }: StatCardsProps) {
  return (
    <ul className="stat-cards">
      {cards.map((card) => (
        <li key={card.label} className="stat-card">
          <p className="stat-card-label">{card.label}</p>
          <p className={`stat-card-value${card.value === null ? " stat-card-unknown" : ""}`}>
            {card.value ?? "—"}
          </p>
          <p className="stat-card-detail">
            {card.value === null ? "not reported" : card.detail ?? "\u00a0"}
          </p>
        </li>
      ))}
    </ul>
  );
}
