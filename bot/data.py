"""Precios (diarios) y fundamentales (refresco escalonado) desde Yahoo Finance."""
import math
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import yfinance as yf

FIELDS = ["marketCap", "enterpriseValue", "ebitda", "freeCashflow", "totalDebt", "totalCash",
          "returnOnAssets", "returnOnEquity", "operatingMargins", "grossMargins",
          "revenueGrowth", "earningsGrowth", "trailingPE", "forwardPE",
          "heldPercentInsiders", "shortPercentOfFloat", "longName", "sector"]


def download_prices(tickers, period="14mo"):
    """Devuelve (close, volume) como DataFrames fecha x ticker."""
    closes, vols = [], []
    for i in range(0, len(tickers), 200):
        chunk = tickers[i:i + 200]
        for attempt in range(3):
            try:
                df = yf.download(chunk, period=period, auto_adjust=True, progress=False,
                                 threads=True, group_by="column")
                closes.append(df["Close"])
                vols.append(df["Volume"])
                break
            except Exception as e:  # noqa: BLE001
                print(f"[prices] reintento {attempt + 1}: {e}")
                time.sleep(5 * (attempt + 1))
    close = pd.concat(closes, axis=1)
    vol = pd.concat(vols, axis=1)
    close = close.loc[:, ~close.columns.duplicated()].dropna(how="all")
    vol = vol.loc[:, ~vol.columns.duplicated()].reindex(close.index)
    return close, vol


def _clean_num(v):
    if v is None:
        return None
    if isinstance(v, (int, float, np.floating)):
        return None if (isinstance(v, float) and (math.isnan(v) or math.isinf(v))) else float(v)
    return v


def _fetch_one(ticker):
    for attempt in range(2):
        try:
            info = yf.Ticker(ticker).info or {}
            data = {k: _clean_num(info.get(k)) for k in FIELDS}
            return ticker, data
        except Exception:  # noqa: BLE001
            time.sleep(2 * (attempt + 1))
    return ticker, None


def refresh_fundamentals(cache: dict, tickers, max_age_days: int, batch: int, must=()):
    """Actualiza en `cache` los tickers con datos más viejos de max_age_days (como máximo `batch`)."""
    now = datetime.now(timezone.utc)

    def age(t):
        c = cache.get(t)
        if not c or not c.get("updated_at"):
            return 10_000
        return (now - datetime.fromisoformat(c["updated_at"])).days

    stale = sorted([t for t in tickers if age(t) >= max_age_days], key=age, reverse=True)
    todo = list(dict.fromkeys(list(must) + stale[:batch]))
    print(f"[fundamentals] {len(stale)} desactualizados, refresco {len(todo)}")
    with ThreadPoolExecutor(max_workers=6) as ex:
        for t, d in ex.map(_fetch_one, todo):
            if d:
                cache[t] = {"data": d, "updated_at": now.isoformat()}
    return cache


def price_metrics(close: pd.DataFrame, vol: pd.DataFrame) -> pd.DataFrame:
    c = close.ffill()
    last = c.iloc[-1]

    def ret(days):
        return last / c.iloc[-days - 1] - 1 if len(c) > days else pd.Series(np.nan, index=c.columns)

    r12_1 = (c.iloc[-22] / c.iloc[-253] - 1) if len(c) > 253 else ret(min(len(c) - 1, 230))
    daily = c.pct_change()
    out = pd.DataFrame({
        "price": last,
        "ret_1m": ret(21),
        "ret_6m": ret(126),
        "ret_12_1": r12_1,
        "vol_60d": daily.iloc[-60:].std() * np.sqrt(252),
        "adv_usd": (close * vol).iloc[-20:].mean(),
        "dist_52w_high": last / c.iloc[-252:].max() - 1,
    })
    return out


def download_ohlcv(tickers, period="7mo"):
    """Devuelve dict campo -> DataFrame (fecha x ticker) con Open, High, Low, Close, Volume."""
    parts = {k: [] for k in ("Open", "High", "Low", "Close", "Volume")}
    for i in range(0, len(tickers), 250):
        chunk = tickers[i:i + 250]
        for attempt in range(3):
            try:
                df = yf.download(chunk, period=period, auto_adjust=True, progress=False,
                                 threads=True, group_by="column")
                for k in parts:
                    parts[k].append(df[k])
                break
            except Exception as e:  # noqa: BLE001
                print(f"[ohlcv] reintento {attempt + 1}: {e}")
                time.sleep(5 * (attempt + 1))
    out = {}
    for k, v in parts.items():
        d = pd.concat(v, axis=1)
        out[k] = d.loc[:, ~d.columns.duplicated()]
    idx = out["Close"].dropna(how="all").index
    return {k: v.reindex(idx) for k, v in out.items()}


def nasdaq_universe(min_mcap, max_mcap, min_price, exclude_countries=()):
    """Todas las acciones de NYSE/Nasdaq/AMEX del screener de Nasdaq, filtradas por tamaño y precio."""
    import requests
    r = requests.get("https://api.nasdaq.com/api/screener/stocks?tableonly=true&limit=10000&download=true",
                     headers={"User-Agent": "Mozilla/5.0"}, timeout=60)
    r.raise_for_status()

    def num(x):
        try:
            return float(str(x).replace("$", "").replace(",", ""))
        except ValueError:
            return None

    rows = []
    for x in r.json()["data"]["rows"]:
        mc, px = num(x.get("marketCap")), num(x.get("lastsale"))
        if not mc or not px or not x["symbol"].isalpha():
            continue
        if min_mcap <= mc <= max_mcap and px >= min_price and x.get("country") not in exclude_countries:
            rows.append({"ticker": x["symbol"].upper(), "name": x["name"], "sector": x.get("sector") or "",
                         "industry": x.get("industry") or "", "country": x.get("country") or "", "mcap": mc})
    return pd.DataFrame(rows)
