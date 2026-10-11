"""Cribado cuantitativo: calidad + valor + momentum. Claude decide sobre esta lista corta."""
import numpy as np
import pandas as pd

from . import config as C


def build_table(universe: pd.DataFrame, fund_cache: dict, pm: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, u in universe.iterrows():
        f = (fund_cache.get(u.ticker) or {}).get("data") or {}
        rows.append({"ticker": u.ticker, "name": f.get("longName") or u["name"],
                     "sector": f.get("sector") or u.sector, **{k: f.get(k) for k in f}})
    df = pd.DataFrame(rows).set_index("ticker")
    df = df.join(pm, how="left")
    num = ["marketCap", "enterpriseValue", "ebitda", "freeCashflow", "totalDebt", "totalCash",
           "returnOnAssets", "operatingMargins", "grossMargins", "trailingPE", "forwardPE",
           "revenueGrowth", "heldPercentInsiders", "shortPercentOfFloat"]
    for col in num:
        if col not in df:
            df[col] = np.nan
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df["fcf_yield"] = df.freeCashflow / df.marketCap
    df["ebitda_ev"] = np.where(df.ebitda > 0, df.ebitda / df.enterpriseValue, np.nan)
    df["earn_yield"] = np.where(df.trailingPE > 0, 1 / df.trailingPE, np.nan)
    df["net_debt_ebitda"] = np.where(df.ebitda > 0, (df.totalDebt.fillna(0) - df.totalCash.fillna(0)) / df.ebitda, np.nan)
    return df


def score(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d["eligible"] = (
        (d.price >= C.MIN_PRICE) & (d.adv_usd >= C.MIN_ADV_USD)
        & (d.ebitda > 0) & (d.freeCashflow > 0)
        & (d.net_debt_ebitda < C.MAX_NET_DEBT_EBITDA)
    )

    def rk(s, fill=0.3):
        return s.rank(pct=True).fillna(fill)

    quality = (rk(d.returnOnAssets) + rk(d.operatingMargins) + rk(d.grossMargins) + rk(-d.net_debt_ebitda)) / 4
    value = (rk(d.fcf_yield) + rk(d.ebitda_ev) + rk(d.earn_yield)) / 3
    momentum = rk(d.ret_12_1)
    d["q_score"], d["v_score"], d["m_score"] = quality, value, momentum
    d["score"] = 0.4 * quality + 0.4 * value + 0.2 * momentum
    d["rank"] = d.score.where(d.eligible).rank(ascending=False)
    return d.sort_values("score", ascending=False)


COLS = ["name", "sector", "price", "marketCap", "score", "rank", "q_score", "v_score", "m_score",
        "fcf_yield", "ebitda_ev", "trailingPE", "returnOnAssets", "operatingMargins",
        "net_debt_ebitda", "revenueGrowth", "ret_1m", "ret_6m", "ret_12_1", "vol_60d",
        "dist_52w_high", "heldPercentInsiders", "shortPercentOfFloat", "adv_usd"]


def compact(df: pd.DataFrame) -> list[dict]:
    """Filas redondeadas para mandar a Claude sin gastar tokens de más."""
    out = []
    for t, r in df[COLS].iterrows():
        row = {"ticker": t}
        for k, v in r.items():
            if isinstance(v, (float, np.floating)):
                if np.isnan(v):
                    continue
                if k == "marketCap":
                    v = round(v / 1e6)  # millones $
                    k = "mcap_musd"
                elif k == "adv_usd":
                    v = round(v / 1e6, 1)
                    k = "adv_musd"
                elif k == "rank":
                    v = int(v)
                else:
                    v = round(float(v), 3)
            row[k] = v
        out.append(row)
    return out
