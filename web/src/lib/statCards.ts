import type { PlayerSeasonSummary } from "../types/player";

export type StatCard = {
  label: string;
  /** Formatted value, or null when the underlying sum is unknown. */
  value: string | null;
  /** Short context under the value, e.g. a per-game rate. */
  detail: string | null;
};

type SumKey = Exclude<keyof PlayerSeasonSummary, "season" | "season_type" | "games">;

type CardSpec =
  | { kind: "sum"; label: string; key: SumKey; perGame?: boolean }
  | { kind: "rate"; label: string; numerator: SumKey; denominator: SumKey; digits: number }
  | { kind: "pair"; label: string; left: SumKey; right: SumKey };

const RUSHING: CardSpec[] = [
  { kind: "sum", label: "Rush yards", key: "rushing_yards", perGame: true },
  { kind: "sum", label: "Carries", key: "carries", perGame: true },
  { kind: "rate", label: "Yards / carry", numerator: "rushing_yards", denominator: "carries", digits: 1 },
  { kind: "sum", label: "Rush TD", key: "rushing_tds" },
];

const RECEIVING: CardSpec[] = [
  { kind: "sum", label: "Rec yards", key: "receiving_yards", perGame: true },
  { kind: "pair", label: "Rec / targets", left: "receptions", right: "targets" },
  { kind: "rate", label: "Yards / rec", numerator: "receiving_yards", denominator: "receptions", digits: 1 },
  { kind: "sum", label: "Rec TD", key: "receiving_tds" },
];

const PASSING: CardSpec[] = [
  { kind: "sum", label: "Pass yards", key: "passing_yards", perGame: true },
  { kind: "pair", label: "Comp / att", left: "completions", right: "attempts" },
  { kind: "sum", label: "Pass TD", key: "passing_tds" },
  { kind: "sum", label: "INT", key: "passing_interceptions" },
];

/**
 * Position-aware card sets. A known position keeps its cards even when a
 * value is unknown, so a gap is visible. Other positions show every skill
 * stat that has data, since we do not know which ones matter.
 */
function specsFor(position: string | null): { specs: CardSpec[]; pruneUnknown: boolean } {
  switch (position) {
    case "RB":
    case "FB":
      return { specs: [...RUSHING, ...RECEIVING.slice(0, 2)], pruneUnknown: false };
    case "WR":
    case "TE":
      return { specs: [...RECEIVING, RUSHING[0]], pruneUnknown: false };
    case "QB":
      return { specs: [...PASSING, RUSHING[0], RUSHING[3]], pruneUnknown: false };
    default:
      return { specs: [...RUSHING, ...RECEIVING, ...PASSING], pruneUnknown: true };
  }
}

export function buildStatCards(
  summary: PlayerSeasonSummary,
  position: string | null,
): StatCard[] {
  const { specs, pruneUnknown } = specsFor(position);
  const cards = specs.map((spec) => toCard(spec, summary));
  if (!pruneUnknown) {
    return cards;
  }
  const known = cards.filter((card) => card.value !== null);
  return known.length > 0 ? known : cards.slice(0, 4);
}

function toCard(spec: CardSpec, s: PlayerSeasonSummary): StatCard {
  switch (spec.kind) {
    case "sum": {
      const total = s[spec.key];
      return {
        label: spec.label,
        value: total === null ? null : formatInt(total),
        detail:
          spec.perGame && total !== null && s.games > 0
            ? `${(total / s.games).toFixed(1)} / game`
            : null,
      };
    }
    case "rate": {
      const num = s[spec.numerator];
      const den = s[spec.denominator];
      if (num === null || den === null || den === 0) {
        return { label: spec.label, value: null, detail: null };
      }
      return { label: spec.label, value: (num / den).toFixed(spec.digits), detail: null };
    }
    case "pair": {
      const left = s[spec.left];
      const right = s[spec.right];
      if (left === null && right === null) {
        return { label: spec.label, value: null, detail: null };
      }
      const value = `${left === null ? "—" : formatInt(left)} / ${right === null ? "—" : formatInt(right)}`;
      const detail =
        left !== null && right !== null && right > 0
          ? `${Math.round((left / right) * 100)}%`
          : null;
      return { label: spec.label, value, detail };
    }
  }
}

function formatInt(value: number): string {
  return value.toLocaleString("en-US");
}
