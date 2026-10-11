"""Parámetros del fondo de demo. Todo se puede sobrescribir con variables de entorno."""
import os


def _f(name, default):
    return float(os.getenv(name, default))


INITIAL_CAPITAL = _f("INITIAL_CAPITAL", 100_000)

# Reglas de cartera (las aplica el broker aunque Claude se equivoque)
MAX_WEIGHT = _f("MAX_WEIGHT", 0.07)          # máximo por empresa
MIN_POSITIONS = int(os.getenv("MIN_POSITIONS", 15))
MAX_POSITIONS = int(os.getenv("MAX_POSITIONS", 25))
MIN_CASH = _f("MIN_CASH", 0.02)              # colchón de liquidez
MAX_DAILY_TURNOVER = _f("MAX_DAILY_TURNOVER", 0.25)  # % del fondo que se puede mover al día
MIN_TRADE = _f("MIN_TRADE", 0.005)           # ignora operaciones < 0,5% del fondo
STOP_LOSS = _f("STOP_LOSS", 0.25)            # venta automática si cae 25% desde el coste
TRADING_COST = _f("TRADING_COST", 0.002)     # comisión + deslizamiento por operación

# Filtros del cribado
MIN_PRICE = _f("MIN_PRICE", 3)
MIN_ADV_USD = _f("MIN_ADV_USD", 3_000_000)   # volumen medio diario en dólares
MAX_NET_DEBT_EBITDA = _f("MAX_NET_DEBT_EBITDA", 3)
N_CANDIDATES = int(os.getenv("N_CANDIDATES", 40))

# Fundamentales: se refrescan por lotes para no saturar Yahoo
FUNDAMENTALS_MAX_AGE_DAYS = int(os.getenv("FUNDAMENTALS_MAX_AGE_DAYS", 7))
FUNDAMENTALS_BATCH = int(os.getenv("FUNDAMENTALS_BATCH", 250))

BENCHMARKS = ["IJR", "IWM"]  # S&P 600 y Russell 2000
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5")
STORE = os.getenv("STORE", "supabase")       # "supabase" o "local"
# "claude" = decide Claude por API; "reglas" = gestor por reglas fijas, gratis y sin API
MANAGER_MODE = os.getenv("MANAGER_MODE", "claude").strip().lower()
MOCK_MANAGER = MANAGER_MODE == "reglas" or os.getenv("MOCK_MANAGER", "0") == "1"

# ---------- Fondo de catalizadores (episodic pivots) ----------
EP_INITIAL_CAPITAL = _f("EP_INITIAL_CAPITAL", 100_000)
EP_MIN_MCAP = _f("EP_MIN_MCAP", 50e6)
EP_MAX_MCAP = _f("EP_MAX_MCAP", 5e9)
EP_MIN_PRICE = _f("EP_MIN_PRICE", 2)
EP_EXCLUDE_COUNTRIES = [c.strip() for c in os.getenv("EP_EXCLUDE_COUNTRIES", "China,Hong Kong").split(",") if c.strip()]
EP_MIN_GAP = _f("EP_MIN_GAP", 0.10)          # hueco de apertura mínimo
EP_MIN_RVOL = _f("EP_MIN_RVOL", 3)           # volumen del día / media 50 días
EP_MIN_DOLLAR_VOL = _f("EP_MIN_DOLLAR_VOL", 5e6)
EP_MAX_CANDIDATES = int(os.getenv("EP_MAX_CANDIDATES", 15))
EP_MAX_WEIGHT = _f("EP_MAX_WEIGHT", 0.15)
EP_MAX_POSITIONS = int(os.getenv("EP_MAX_POSITIONS", 10))
EP_MIN_CASH = _f("EP_MIN_CASH", 0.05)
EP_MAX_STOP = _f("EP_MAX_STOP", 0.12)        # el stop nunca más lejos del 12% de la entrada
EP_MAX_CHASE = _f("EP_MAX_CHASE", 0.08)      # cancela la compra si abre >8% sobre el cierre de la señal
EP_TAKE_PROFIT = _f("EP_TAKE_PROFIT", 0.30)  # vende 1/3 al +30% y sube el stop a la entrada
EP_SLIPPAGE = _f("EP_SLIPPAGE", 0.005)       # deslizamiento en microcaps
EP_COST = _f("EP_COST", 0.001)
SEC_USER_AGENT = os.getenv("SEC_USER_AGENT", "smallcap-bot demo contacto@example.com")
