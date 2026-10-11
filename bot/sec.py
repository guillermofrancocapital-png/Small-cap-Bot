"""SEC EDGAR: catalizadores (8-K recientes) y riesgo de dilución (shelf, folletos, ventas de acciones)."""
import re
import time
from datetime import date, timedelta
from html import unescape

import requests

from . import config as C

H = {"User-Agent": C.SEC_USER_AGENT}
_CIK = None

ITEMS_8K = {
    "1.01": "acuerdo material", "1.02": "fin de acuerdo material", "2.01": "compra/venta de activos",
    "2.02": "resultados", "2.03": "nueva deuda", "3.01": "aviso de exclusión de cotización",
    "3.02": "venta no registrada de acciones (dilución)", "3.03": "cambio en derechos de accionistas",
    "5.02": "cambios en directivos", "5.03": "cambio de estatutos (posible contrasplit)",
    "7.01": "comunicación al mercado", "8.01": "otros hechos relevantes", "9.01": "anexos",
}
DILUTION_FORMS = ("S-1", "S-1/A", "S-3", "S-3/A", "F-1", "F-3", "424B1", "424B3", "424B4", "424B5", "424B7", "S-8")


def _get(url):
    time.sleep(0.15)  # la SEC permite ~10 peticiones/segundo
    r = requests.get(url, headers=H, timeout=30)
    r.raise_for_status()
    return r


def cik_for(ticker):
    global _CIK
    if _CIK is None:
        d = _get("https://www.sec.gov/files/company_tickers.json").json()
        _CIK = {v["ticker"].upper().replace(".", "-"): int(v["cik_str"]) for v in d.values()}
    return _CIK.get(ticker.upper())


def _text(html, limit):
    html = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
    t = unescape(re.sub(r"(?s)<[^>]+>", " ", html))
    return re.sub(r"\s+", " ", t).strip()[:limit]


def filings_summary(ticker, days_8k=5, days_dilution=180, excerpt_chars=2500):
    """Resumen para Claude: 8-K recientes (con extracto de la nota de prensa) y formularios de dilución."""
    cik = cik_for(ticker)
    if not cik:
        return {"sec": "sin CIK (posible emisor extranjero o ticker no encontrado)"}
    try:
        f = _get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json").json()["filings"]["recent"]
    except Exception as e:  # noqa: BLE001
        return {"sec": f"error: {e}"}
    today = date.today()
    recent_8k, dilution = [], []
    for i, form in enumerate(f["form"]):
        fd = date.fromisoformat(f["filingDate"][i])
        if form in ("8-K", "6-K") and (today - fd).days <= days_8k:
            items = [ITEMS_8K.get(x.strip(), x.strip()) for x in (f["items"][i] or "").split(",") if x.strip()]
            recent_8k.append({"date": f["filingDate"][i], "form": form, "items": items,
                              "acc": f["accessionNumber"][i]})
        if form in DILUTION_FORMS and (today - fd).days <= days_dilution:
            dilution.append(f"{f['filingDate'][i]} {form}")
    # Extracto de la nota de prensa del 8-K más reciente (anexo 99.1)
    if recent_8k:
        acc = recent_8k[0]["acc"].replace("-", "")
        try:
            idx = _get(f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/index.json").json()
            files = [x["name"] for x in idx["directory"]["item"]]
            ex = next((n for n in files if re.search(r"ex-?99", n, re.I) and n.endswith((".htm", ".html", ".txt"))), None)
            if ex:
                html = _get(f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{ex}").text
                recent_8k[0]["press_release_excerpt"] = _text(html, excerpt_chars)
        except Exception:  # noqa: BLE001
            pass
    for r in recent_8k:
        r.pop("acc", None)
    return {"recent_8k": recent_8k[:3], "dilution_filings_180d": dilution[:10]}
