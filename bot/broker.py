"""Broker simulado: aplica las reglas y ejecuta al cierre con costes."""
import math

from . import config as C


def nav(cash, positions, prices):
    return cash + sum(p["shares"] * prices.get(t, p["last_price"]) for t, p in positions.items())


def apply_stop_losses(date, cash, positions, prices):
    trades = []
    for t, p in list(positions.items()):
        px = prices.get(t)
        if px and px <= p["avg_cost"] * (1 - C.STOP_LOSS):
            value = p["shares"] * px
            cost = value * C.TRADING_COST
            cash += value - cost
            trades.append(_trade(date, t, "SELL", p["shares"], px, cost,
                                 f"Stop-loss automático (-{C.STOP_LOSS:.0%} sobre coste)", True))
            del positions[t]
    return cash, trades


def execute(date, decisions, cash, positions, prices, meta, allowed):
    """decisions: lista de {ticker, target_weight, reason}. Devuelve (cash, trades, rejected)."""
    total = nav(cash, positions, prices)
    invested = 1 - cash / total
    turnover_cap = max(C.MAX_DAILY_TURNOVER, 1 - C.MIN_CASH - invested)  # permite construir la cartera
    trades, rejected = [], []

    orders = []
    for d in decisions:
        t = d["ticker"].upper().strip()
        px = prices.get(t)
        if t not in allowed and t not in positions:
            rejected.append({**d, "why": "fuera de candidatos"}); continue
        if not px or math.isnan(px):
            rejected.append({**d, "why": "sin precio"}); continue
        tw = min(max(float(d["target_weight"]), 0.0), C.MAX_WEIGHT)
        cur = positions.get(t, {}).get("shares", 0) * px / total
        delta = tw - cur
        if abs(delta) < C.MIN_TRADE and tw > 0:
            continue
        orders.append((t, px, tw, delta, d.get("reason", "")))

    # Límite de posiciones: prioriza las compras nuevas con más peso objetivo
    closing = {o[0] for o in orders if o[2] == 0}
    slots = C.MAX_POSITIONS - len(set(positions) - closing)
    new_buys = sorted([o for o in orders if o[0] not in positions and o[2] > 0], key=lambda o: -o[2])
    drop = {o[0] for o in new_buys[max(slots, 0):]}
    rejected += [{"ticker": t, "why": "excede máximo de posiciones"} for t in drop]
    orders = [o for o in orders if o[0] not in drop]

    # Ventas primero
    budget = turnover_cap * total
    for t, px, tw, delta, reason in sorted(orders, key=lambda o: o[3]):
        if delta >= 0:
            continue
        p = positions[t]
        sh = p["shares"] if tw == 0 else min(p["shares"], math.floor(-delta * total / px))
        value = sh * px
        if sh <= 0 or value > budget:
            if value > budget:
                rejected.append({"ticker": t, "why": "límite de rotación diaria"})
            continue
        cost = value * C.TRADING_COST
        cash += value - cost
        budget -= value
        p["shares"] -= sh
        if p["shares"] <= 0:
            del positions[t]
        trades.append(_trade(date, t, "SELL" if t not in positions else "TRIM", sh, px, cost, reason))

    # Compras
    sector_w = _sector_weights(positions, prices, meta, total)
    for t, px, tw, delta, reason in sorted(orders, key=lambda o: -o[3]):
        if delta <= 0:
            continue
        spend = min(delta * total, cash - C.MIN_CASH * total, budget)
        sec = meta.get(t, {}).get("sector", "?")
        spend = min(spend, max(0, 0.30 * total - sector_w.get(sec, 0)))
        sh = math.floor(spend / (px * (1 + C.TRADING_COST)))
        if sh <= 0 or sh * px < C.MIN_TRADE * total * 0.5:
            rejected.append({"ticker": t, "why": "sin liquidez, rotación o límite sectorial"}); continue
        value = sh * px
        cost = value * C.TRADING_COST
        cash -= value + cost
        budget -= value
        sector_w[sec] = sector_w.get(sec, 0) + value
        p = positions.get(t)
        if p:
            p["avg_cost"] = (p["avg_cost"] * p["shares"] + value) / (p["shares"] + sh)
            p["shares"] += sh
            side = "ADD"
        else:
            positions[t] = {"shares": sh, "avg_cost": px, "opened_at": date, "last_price": px,
                            "name": meta.get(t, {}).get("name"), "sector": sec}
            side = "BUY"
        trades.append(_trade(date, t, side, sh, px, cost, reason))
    return cash, trades, rejected


def _sector_weights(positions, prices, meta, total):
    out = {}
    for t, p in positions.items():
        s = p.get("sector") or meta.get(t, {}).get("sector", "?")
        out[s] = out.get(s, 0) + p["shares"] * prices.get(t, p["last_price"])
    return out


def _trade(date, t, side, sh, px, cost, reason, auto=False):
    return {"date": date, "ticker": t, "side": side, "shares": int(sh), "price": round(px, 4),
            "value": round(sh * px, 2), "cost": round(cost, 2), "reason": reason, "auto": auto}
