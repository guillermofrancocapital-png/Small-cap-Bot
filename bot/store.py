"""Persistencia por fondo: Supabase en producción, ficheros JSON en local para pruebas."""
import json
import os
from pathlib import Path

from . import config as C


class LocalStore:
    def __init__(self, fund_id, path="data"):
        self.fund = fund_id
        self.root = Path(path)
        self.p = self.root / fund_id
        self.p.mkdir(parents=True, exist_ok=True)

    def _r(self, name, default, shared=False):
        f = (self.root if shared else self.p) / f"{name}.json"
        return json.loads(f.read_text()) if f.exists() else default

    def _w(self, name, obj, shared=False):
        ((self.root if shared else self.p) / f"{name}.json").write_text(json.dumps(obj, indent=1, default=str))

    def load_state(self):
        return self._r("fund_state", None)

    def save_state(self, s):
        self._w("fund_state", s)

    def load_positions(self):
        return self._r("positions", {})

    def save_positions(self, p):
        self._w("positions", p)

    def load_fundamentals(self):
        return self._r("fundamentals", {}, shared=True)

    def save_fundamentals(self, f):
        self._w("fundamentals", f, shared=True)

    def add_trades(self, trades):
        self._w("trades", self._r("trades", []) + trades)

    def nav_history(self):
        return self._r("nav_history", [])

    def add_nav(self, row):
        h = [r for r in self.nav_history() if r["date"] != row["date"]]
        self._w("nav_history", h + [row])

    def recent_reports(self, n=5):
        return [{k: r.get(k) for k in ("date", "market_view", "notes")} for r in self._r("daily_reports", [])[-n:]]

    def add_report(self, row):
        self._w("daily_reports", [r for r in self._r("daily_reports", []) if r["date"] != row["date"]] + [row])


class SupabaseStore:
    def __init__(self, fund_id):
        from supabase import create_client
        self.fund = fund_id
        self.db = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])

    def _t(self, name):
        return self.db.table(name)

    def load_state(self):
        r = self._t("fund_state").select("*").eq("fund_id", self.fund).execute().data
        return r[0] if r else None

    def save_state(self, s):
        self._t("fund_state").upsert({**s, "fund_id": self.fund}).execute()

    def load_positions(self):
        rows = self._t("positions").select("*").eq("fund_id", self.fund).execute().data
        return {r["ticker"]: {k: v for k, v in r.items() if k not in ("ticker", "fund_id")} for r in rows}

    def save_positions(self, p):
        gone = set(self.load_positions()) - set(p)
        if gone:
            self._t("positions").delete().eq("fund_id", self.fund).in_("ticker", list(gone)).execute()
        if p:
            self._t("positions").upsert([{**v, "ticker": k, "fund_id": self.fund} for k, v in p.items()]).execute()

    def load_fundamentals(self):
        out, start = {}, 0
        while True:
            rows = self._t("fundamentals").select("*").range(start, start + 999).execute().data
            for r in rows:
                out[r["ticker"]] = {"data": r["data"], "updated_at": r["updated_at"]}
            if len(rows) < 1000:
                return out
            start += 1000

    def save_fundamentals(self, f):
        rows = [{"ticker": t, "data": v["data"], "updated_at": v["updated_at"]} for t, v in f.items()]
        for i in range(0, len(rows), 500):
            self._t("fundamentals").upsert(rows[i:i + 500]).execute()

    def add_trades(self, trades):
        if trades:
            self._t("trades").insert([{**t, "fund_id": self.fund} for t in trades]).execute()

    def nav_history(self):
        return self._t("nav_history").select("*").eq("fund_id", self.fund).order("date").execute().data

    def add_nav(self, row):
        self._t("nav_history").upsert({**row, "fund_id": self.fund}).execute()

    def recent_reports(self, n=5):
        r = (self._t("daily_reports").select("date,market_view,notes").eq("fund_id", self.fund)
             .order("date", desc=True).limit(n).execute().data)
        return list(reversed(r))

    def add_report(self, row):
        self._t("daily_reports").upsert({**row, "fund_id": self.fund}).execute()


def get_store(fund_id):
    return LocalStore(fund_id) if C.STORE == "local" else SupabaseStore(fund_id)
