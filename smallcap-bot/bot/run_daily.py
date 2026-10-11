"""Fondo de calidad + valor. Ejecución diaria: datos -> cribado -> stop-loss -> decisión de Claude -> broker -> guardado."""
import os
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import numpy as np

from . import broker, config as C, data, manager, screen
from .store import get_store
from .universe import get_universe


def main():
    store = get_store("calidad")
    today_ny = datetime.now(ZoneInfo("America/New_York")).date().isoformat()

    state = store.load_state() or {"cash": C.INITIAL_CAPITAL, "initial_capital": C.INITIAL_CAPITAL,
                                    "inception": None}
    positions = store.load_positions()

    universe = get_universe()
    print(f"[universe] {len(universe)} valores")
    tickers = sorted(set(universe.ticker) | set(positions))
    close, vol = data.download_prices(tickers + C.BENCHMARKS)
    last_date = close.index[-1].date().isoformat()
    print(f"[prices] última sesión {last_date}")

    if last_date in {r["date"] for r in store.nav_history()} and os.getenv("FORCE") != "1":
        print("Esta sesión ya está procesada (¿festivo o fin de semana?). Salgo.")
        return

    prices = {t: float(v) for t, v in close.ffill().iloc[-1].items() if not np.isnan(v)}
    bench = {b: prices.get(b) for b in C.BENCHMARKS}

    fund = data.refresh_fundamentals(store.load_fundamentals(), list(universe.ticker),
                                     C.FUNDAMENTALS_MAX_AGE_DAYS, C.FUNDAMENTALS_BATCH, must=list(positions))
    store.save_fundamentals(fund)

    pm = data.price_metrics(close.drop(columns=C.BENCHMARKS, errors="ignore"), vol)
    table = screen.score(screen.build_table(universe, fund, pm))
    meta = {t: {"name": r["name"], "sector": r["sector"]} for t, r in table.iterrows()}

    # 1. Stop-loss automáticos
    cash, trades = broker.apply_stop_losses(last_date, state["cash"], positions, prices)

    # 2. Contexto para Claude
    total = broker.nav(cash, positions, prices)
    held_rows = {r["ticker"]: r for r in screen.compact(table[table.index.isin(positions)])}
    pos_view = []
    for t, p in positions.items():
        px = prices.get(t, p["last_price"])
        pos_view.append({"ticker": t, "weight": round(p["shares"] * px / total, 4),
                         "pnl": round(px / p["avg_cost"] - 1, 3), "opened_at": p["opened_at"],
                         **{k: v for k, v in held_rows.get(t, {}).items() if k != "ticker"}})
    cands = table[table.eligible & ~table.index.isin(positions)].head(C.N_CANDIDATES)
    hist = store.nav_history()
    perf = {}
    if hist:
        first = hist[0]
        perf = {"fund_since_inception": round(total / state["initial_capital"] - 1, 4),
                **{f"{b}_since_inception": round(bench[b] / first["bench"][b] - 1, 4)
                   for b in C.BENCHMARKS if first.get("bench", {}).get(b) and bench.get(b)}}
    context = {
        "date": last_date,
        "portfolio": {"nav": round(total, 2), "cash_weight": round(cash / total, 4),
                      "positions": pos_view, "performance": perf},
        "auto_trades_today": trades,
        "candidates": screen.compact(cands),
        "recent_notes": store.recent_reports(5),
    }

    # 3. Decisión
    decision = manager.decide(context)
    allowed = set(cands.index)
    cash, new_trades, rejected = broker.execute(last_date, decision["decisions"], cash, positions,
                                                prices, meta, allowed)
    trades += new_trades

    # 4. Valoración y guardado
    for t, p in positions.items():
        p["last_price"] = prices.get(t, p["last_price"])
    total = broker.nav(cash, positions, prices)
    state.update({"cash": round(cash, 2), "inception": state.get("inception") or last_date,
                  "updated_at": datetime.now(timezone.utc).isoformat()})
    store.save_state(state)
    store.save_positions(positions)
    store.add_trades(trades)
    store.add_nav({"date": last_date, "nav": round(total, 2), "cash": round(cash, 2),
                   "n_positions": len(positions), "bench": bench})
    store.add_report({"date": last_date, "market_view": decision.get("market_view"),
                      "notes": decision.get("notes_for_tomorrow"),
                      "decisions": decision.get("decisions"), "rejected": rejected,
                      "model": "reglas" if C.MOCK_MANAGER else C.CLAUDE_MODEL,
                      "usage": decision.get("_usage")})
    print(f"[ok] {last_date} NAV {total:,.0f} $ | {len(positions)} posiciones | "
          f"{len(trades)} operaciones | {len(rejected)} rechazadas")


if __name__ == "__main__":
    sys.exit(main())
