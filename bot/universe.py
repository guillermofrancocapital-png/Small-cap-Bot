"""Universo: componentes del S&P SmallCap 600 (exige beneficios para entrar, buen punto de partida)."""
import io
import pandas as pd
import requests

UA = {"User-Agent": "Mozilla/5.0"}
SPSM_URL = ("https://www.ssga.com/us/en/intermediary/library-content/products/"
            "fund-data/etfs/us/holdings-daily-us-en-spsm.xlsx")
WIKI_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_600_companies"


def _clean(t: str) -> str:
    return str(t).strip().upper().replace(".", "-").replace("/", "-")


def get_universe() -> pd.DataFrame:
    """Devuelve DataFrame con columnas ticker, name, sector."""
    try:
        r = requests.get(SPSM_URL, headers=UA, timeout=60)
        r.raise_for_status()
        df = pd.read_excel(io.BytesIO(r.content), skiprows=4)
        df = df[df["Ticker"].notna() & df["Sector"].notna()]
        df = df[~df["Ticker"].astype(str).str.upper().isin(["CASH_USD", "USD", "-"])]
        out = pd.DataFrame({"ticker": df["Ticker"].map(_clean),
                            "name": df["Name"].astype(str).str.title(),
                            "sector": df["Sector"].astype(str)})
        out = out[out["ticker"].str.match(r"^[A-Z][A-Z\-]{0,6}$")]
        if len(out) > 400:
            return out.drop_duplicates("ticker").reset_index(drop=True)
    except Exception as e:  # noqa: BLE001
        print(f"[universe] SPSM falló: {e}. Uso Wikipedia.")
    r = requests.get(WIKI_URL, headers=UA, timeout=60)
    t = pd.read_html(io.StringIO(r.text))[0]
    return pd.DataFrame({"ticker": t["Symbol"].map(_clean),
                         "name": t["Security"], "sector": t["GICS Sector"]}).drop_duplicates("ticker")
