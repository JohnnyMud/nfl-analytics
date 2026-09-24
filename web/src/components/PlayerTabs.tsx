export type PlayerTab = "overview" | "performance" | "matchups" | "predictions";

const TABS: { id: PlayerTab; label: string; enabled: boolean; note: string }[] = [
  { id: "overview", label: "Overview", enabled: true, note: "" },
  { id: "performance", label: "Performance", enabled: false, note: "game log and rolling form" },
  { id: "matchups", label: "Matchups", enabled: false, note: "opponent defense vs position" },
  { id: "predictions", label: "Predictions", enabled: false, note: "model output vs actual" },
];

type PlayerTabsProps = {
  active: PlayerTab;
  onChange: (tab: PlayerTab) => void;
};

/**
 * Section navigation for the player page. Tabs without a data source yet are
 * rendered disabled so the layout is stable as sections land.
 */
export function PlayerTabs({ active, onChange }: PlayerTabsProps) {
  return (
    <nav className="tabs" aria-label="Player sections">
      {TABS.map((tab) => (
        <button
          key={tab.id}
          type="button"
          className={`tab${tab.id === active ? " tab-active" : ""}`}
          aria-current={tab.id === active ? "page" : undefined}
          disabled={!tab.enabled}
          title={tab.enabled ? undefined : `Coming soon: ${tab.note}`}
          onClick={() => onChange(tab.id)}
        >
          {tab.label}
        </button>
      ))}
    </nav>
  );
}
