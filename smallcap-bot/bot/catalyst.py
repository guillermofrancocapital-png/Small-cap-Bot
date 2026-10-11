"""Fondo de catalizadores (episodic pivots). Se ejecuta tras el cierre:
1) ejecuta en la apertura de hoy las órdenes decididas ayer, 2) aplica stops con el mínimo del día,
3) programa salidas por reglas, 4) detecta nuevos huecos con volumen, 5) Claude decide las compras de mañana."""
import math
import os
from datetime import datetime, timezone

import numpy as np
import yfinance as yf

from . import config as C, data, manager, sec
from .store import get_store

FUND = "catalizadores"


def _trade(date, t, side, sh, px, reason, auto):
    value = sh * px
    return {"date": date, "ticker": t, "side": side, "shares": int(sh), "price": round(px, 4),
            "value": round(value, 2), "cost": round(value * C.EP_COST, 2), "reason": reason, "auto": auto}


def _nav(cash, positions):
    return cash + sum(p["shares"] * p["last_price"] for p in positions.values())


def _f(x):
    return None if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))) else x


def main():
    store = get_store(FUND)
    state = store.load_state() or {"cash": C.EP_INITIAL_CAPITAL, "initial_capital": C.EP_INITIAL_CAPITAL,
                                    "inception": None, "pending": []}
    state.setdefault("pending", [])
    positions = store.load_positions()

    uni = data.nasdaq_universe(C.EP_MIN_MCAP, C.EP_MAX_MCAP, C.EP_MIN_PRICE, C.EP_EXCLUDE_COUNTRIES)
    meta = {r.ticker: r._asdict() for r in uni.itertuples(index=False)}
    tickers = sorted(set(uni.ticker) | set(positions) | {o["ticker"] for o in state["pending"]})
    print(f"[universo] {len(tickers)} valores")
    px = data.download_ohlcv(tickers + C.BENCHMARKS)
    O, H, L, Cl, V = (px[k] for k in ("Open", "High", "Low", "Close", "Volume"))
    day = Cl.index[-1].date().isoformat()
    print(f"[precios] última sesión {day}")
    if day in {r["date"] for r in store.nav_history()} and os.getenv("FORCE") != "1":
        print("Sesión ya procesada. Salgo.")
        return

    def bar(t, field, i=-1):
        try:
            v = float(px[field][t].iloc[i])
            return None if np.isnan(v) else v
        except (KeyError, IndexError):
            return None

    trades, log = [], []
    nav_prev = _nav(state["cash"], positions)
    cash = state["cash"]

    # 1. Órdenes pendientes en la apertura de hoy (ventas primero)
    for o in sorted(state["pending"], key=lambda x: x["side"] == "BUY"):
        t, op = o["ticker"], bar(o["ticker"], "Open")
        if op is None:
            log.append(f"{t}: sin precio de apertura, orden cancelada"); continue
        if o["side"] in ("SELL", "TRIM") and t in positions:
            p = positions[t]
            sh = p["shares"] if o["side"] == "SELL" else max(1, p["shares"] // 3)
            fill = op * (1 - C.EP_SLIPPAGE)
            trades.append(_trade(day, t, o["side"], sh, fill, o["reason"], o.get("auto", False)))
            cash += sh * fill * (1 - C.EP_COST)
            p["shares"] -= sh
            if o["side"] == "TRIM":
                p["stop"] = max(p["stop"], p["extra"]["entry"])
                p["extra"]["tp_done"] = True
            if p["shares"] <= 0:
                del positions[t]
        elif o["side"] == "BUY":
            if op > o["signal_close"] * (1 + C.EP_MAX_CHASE):
                log.append(f"{t}: abrió {op / o['signal_close'] - 1:+.1%} sobre la señal, compra cancelada"); continue
            fill = op * (1 + C.EP_SLIPPAGE)
            budget = min(o["weight"] * nav_prev, cash - C.EP_MIN_CASH * nav_prev)
            sh = math.floor(budget / (fill * (1 + C.EP_COST)))
            if sh <= 0:
                log.append(f"{t}: sin liquidez para comprar"); continue
            cash -= sh * fill * (1 + C.EP_COST)
            stop = max(o["signal_low"], fill * (1 - C.EP_MAX_STOP))
            positions[t] = {"shares": sh, "avg_cost": round(fill, 4), "opened_at": day, "last_price": fill,
                            "name": o.get("name"), "sector": o.get("sector"), "stop": round(stop, 4),
                            "extra": {"entry": fill, "days_held": 0, "tp_done": False, "thesis": o["reason"]}}
            trades.append(_trade(day, t, "BUY", sh, fill, o["reason"], False))

    # 2. Stops con el rango del día
    for t, p in list(positions.items()):
        lo, op = bar(t, "Low"), bar(t, "Open")
        if lo is not None and lo <= p["stop"]:
            fill = min(op or p["stop"], p["stop"]) * (1 - C.EP_SLIPPAGE)
            trades.append(_trade(day, t, "SELL", p["shares"], fill, f"Stop tocado ({p['stop']:.2f} $)", True))
            cash += p["shares"] * fill * (1 - C.EP_COST)
            del positions[t]

    # 3. Valoración y salidas por reglas para mañana
    pending = []
    for t, p in positions.items():
        c = bar(t, "Close") or p["last_price"]
        p["last_price"] = c
        if p["opened_at"] != day:
            p["extra"]["days_held"] = p["extra"].get("days_held", 0) + 1
        sma10 = float(Cl[t].iloc[-10:].mean()) if t in Cl else None
        if not p["extra"].get("tp_done") and c >= p["extra"]["entry"] * (1 + C.EP_TAKE_PROFIT):
            pending.append({"ticker": t, "side": "TRIM", "auto": True,
                            "reason": f"Toma de beneficios parcial (+{C.EP_TAKE_PROFIT:.0%}); stop a la entrada"})
        elif p["extra"]["days_held"] >= 3 and sma10 and c < sma10:
            pending.append({"ticker": t, "side": "SELL", "auto": True, "reason": "Cierre bajo la media de 10 sesiones"})
    nav = _nav(cash, positions)

    # 4. Detección de episodic pivots de hoy
    cands = []
    vol50 = V.iloc[-51:-1].mean()
    for t in uni.ticker:
        if t in positions or t not in Cl:
            continue
        o, h, lo, c, v = (bar(t, k) for k in ("Open", "High", "Low", "Close", "Volume"))
        pc = bar(t, "Close", -2)
        if None in (o, h, lo, c, v, pc) or pc <= 0:
            continue
        gap, rvol = o / pc - 1, v / vol50.get(t, np.nan) if vol50.get(t) else np.nan
        if gap < C.EP_MIN_GAP or not rvol or np.isnan(rvol) or rvol < C.EP_MIN_RVOL or c * v < C.EP_MIN_DOLLAR_VOL:
            continue
        hist = Cl[t].iloc[:-1].dropna()
        cands.append({"ticker": t, "name": meta[t]["name"], "sector": meta[t]["sector"], "industry": meta[t]["industry"],
                      "country": meta[t]["country"], "mcap_musd": round(meta[t]["mcap"] / 1e6),
                      "prev_close": round(pc, 3), "open": round(o, 3), "high": round(h, 3), "low": round(lo, 3),
                      "close": round(c, 3), "gap": round(gap, 3), "day_return": round(c / pc - 1, 3),
                      "close_in_range": round((c - lo) / (h - lo), 2) if h > lo else 1.0,
                      "rvol": round(rvol, 1), "dollar_vol_musd": round(c * v / 1e6, 1),
                      "ret_3m_before": round(hist.iloc[-1] / hist.iloc[-64] - 1, 3) if len(hist) > 64 else None,
                      "vs_6m_high_before": round(hist.iloc[-1] / hist.max() - 1, 3) if len(hist) else None})
    cands.sort(key=lambda x: -(x["gap"] * math.log1p(x["rvol"]) * x["close_in_range"]))
    print(f"[escáner] {len(cands)} huecos detectados")
    cands = cands[:C.EP_MAX_CANDIDATES]

    # 5. Enriquecer: fundamentales, evolución de acciones y SEC
    for cd in cands:
        t = cd["ticker"]
        try:
            info = yf.Ticker(t).info or {}
            for k in ("floatShares", "sharesOutstanding", "shortPercentOfFloat", "totalCash", "freeCashflow",
                      "revenueGrowth", "earningsGrowth", "profitMargins", "totalRevenue"):
                cd[k] = _f(info.get(k))
            sh = yf.Ticker(t).get_shares_full(start=(Cl.index[-1] - np.timedelta64(400, "D")).strftime("%Y-%m-%d"))
            if sh is not None and len(sh) > 1:
                cd["shares_change_1y"] = round(float(sh.iloc[-1]) / float(sh.iloc[0]) - 1, 3)
        except Exception as e:  # noqa: BLE001
            cd["fundamentals_error"] = str(e)[:100]
        cd.update(sec.filings_summary(t))

    # 6. Decisión de Claude
    perf = {}
    hist_nav = store.nav_history()
    bench = {b: bar(b, "Close") for b in C.BENCHMARKS}
    if hist_nav:
        f0 = hist_nav[0]
        perf = {"fund_since_inception": round(nav / state["initial_capital"] - 1, 4),
                **{f"{b}_since_inception": round(bench[b] / f0["bench"][b] - 1, 4) for b in C.BENCHMARKS
                   if f0.get("bench", {}).get(b) and bench.get(b)}}
    ctx = {
        "date": day,
        "portfolio": {"nav": round(nav, 2), "cash_weight": round(cash / nav, 3), "performance": perf,
                      "positions": [{"ticker": t, "weight": round(p["shares"] * p["last_price"] / nav, 3),
                                     "pnl": round(p["last_price"] / p["extra"]["entry"] - 1, 3),
                                     "days_held": p["extra"]["days_held"], "stop": p["stop"],
                                     "thesis": p["extra"].get("thesis")} for t, p in positions.items()]},
        "executed_today": trades, "execution_notes": log,
        "rule_orders_for_tomorrow": pending,
        "candidates": cands,
        "recent_notes": store.recent_reports(5),
    }
    dec = manager.decide_ep(ctx) if cands or positions else {
        "market_view": "Sin huecos que cumplan los criterios y sin posiciones abiertas.",
        "buys": [], "sells": [], "notes_for_tomorrow": ""}

    # 7. Validar y programar órdenes de mañana
    rejected = []
    scheduled = {o["ticker"] for o in pending}
    for s in dec.get("sells", []):
        t = s["ticker"].upper()
        if t in positions and t not in scheduled:
            pending.append({"ticker": t, "side": "SELL", "reason": s["reason"], "auto": False})
            scheduled.add(t)
    by_t = {c["ticker"]: c for c in cands}
    open_after = len([t for t in positions if not any(o["ticker"] == t and o["side"] == "SELL" for o in pending)])
    free_w = cash / nav - C.EP_MIN_CASH
    for b in sorted(dec.get("buys", []), key=lambda x: -x["weight"]):
        t, w = b["ticker"].upper(), min(max(float(b["weight"]), 0), C.EP_MAX_WEIGHT)
        if t not in by_t:
            rejected.append({"ticker": t, "why": "no estaba entre los candidatos"}); continue
        if open_after >= C.EP_MAX_POSITIONS or w > free_w + 1e-9 or w <= 0:
            rejected.append({"ticker": t, "why": "límite de posiciones o liquidez"}); continue
        c = by_t[t]
        pending.append({"ticker": t, "side": "BUY", "weight": w, "reason": b["reason"],
                        "signal_close": c["close"], "signal_low": c["low"], "name": c["name"], "sector": c["sector"]})
        open_after += 1
        free_w -= w

    state.update({"cash": round(cash, 2), "pending": pending, "inception": state.get("inception") or day,
                  "updated_at": datetime.now(timezone.utc).isoformat()})
    store.save_state(state)
    store.save_positions(positions)
    store.add_trades(trades)
    store.add_nav({"date": day, "nav": round(nav, 2), "cash": round(cash, 2), "n_positions": len(positions), "bench": bench})
    store.add_report({"date": day, "market_view": dec.get("market_view"),
                      "notes": " ".join(x for x in (dec.get("notes_for_tomorrow"), dec.get("rejected_notes")) if x),
                      "decisions": {"buys": dec.get("buys"), "sells": dec.get("sells"), "pending": pending,
                                    "candidates": [{k: c.get(k) for k in ("ticker", "name", "gap", "rvol", "close")} for c in cands],
                                    "execution_notes": log},
                      "rejected": rejected, "model": "reglas" if C.MOCK_MANAGER else C.CLAUDE_MODEL,
                      "usage": dec.get("_usage")})
    print(f"[ok] {day} NAV {nav:,.0f} $ | {len(positions)} posiciones | {len(trades)} ejecutadas | "
          f"{len(pending)} órdenes para mañana | {len(cands)} candidatos")


if __name__ == "__main__":
    main()
