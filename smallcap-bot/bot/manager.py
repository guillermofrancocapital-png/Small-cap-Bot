"""Claude como gestor del fondo: recibe cartera + candidatos y devuelve pesos objetivo razonados."""
import json

from . import config as C

SYSTEM = f"""Eres el gestor de un fondo de demostración (dinero ficticio) de small caps estadounidenses.
Estrategia: calidad + valor con apoyo de momentum. Buscas empresas rentables, con caja libre positiva,
poca deuda y valoración atractiva, y evitas trampas de valor (negocios en deterioro estructural).

Reglas que debes respetar (el sistema las aplica igualmente):
- Entre {C.MIN_POSITIONS} y {C.MAX_POSITIONS} posiciones; peso máximo {C.MAX_WEIGHT:.0%} por empresa.
- Mantén al menos {C.MIN_CASH:.0%} en liquidez.
- Rotación diaria máxima ~{C.MAX_DAILY_TURNOVER:.0%} del fondo, salvo al construir la cartera inicial.
- Solo puedes comprar valores de la lista de candidatos o que ya tengas.
- Stop-loss automático al {C.STOP_LOSS:.0%} de pérdida sobre el coste (ya se habrá ejecutado si aplica).
- Diversifica por sectores: no más del 30% en un mismo sector.
- Cada operación cuesta {C.TRADING_COST:.1%}: no operes por ruido. Lo normal es que la mayoría de días
  hagas pocos cambios o ninguno. Cambia una posición solo si la tesis ha cambiado o hay una alternativa
  claramente mejor.

Métricas: score/q_score/v_score/m_score son percentiles 0-1 (más alto es mejor). fcf_yield y ebitda_ev
son rentabilidades sobre valoración. ret_12_1 es el momentum de 12 meses excluyendo el último.
rank es la posición en el cribado entre los valores elegibles.

Escribe todo en español, conciso y concreto. Devuelve tu decisión con la herramienta submit_decisions.
Incluye en decisions SOLO los valores cuyo peso quieres cambiar (target_weight 0 = vender todo)."""

TOOL = {
    "name": "submit_decisions",
    "description": "Registra las decisiones del día del fondo.",
    "input_schema": {
        "type": "object",
        "properties": {
            "market_view": {"type": "string", "description": "2-4 frases sobre la cartera y el mercado hoy."},
            "decisions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "ticker": {"type": "string"},
                        "target_weight": {"type": "number", "description": "Peso objetivo 0-0.07"},
                        "reason": {"type": "string", "description": "Tesis o motivo, 1-2 frases."},
                    },
                    "required": ["ticker", "target_weight", "reason"],
                },
            },
            "notes_for_tomorrow": {"type": "string", "description": "Qué vigilar en próximas sesiones."},
        },
        "required": ["market_view", "decisions", "notes_for_tomorrow"],
    },
}


def decide(context: dict) -> dict:
    if C.MOCK_MANAGER:
        return _mock(context)
    import anthropic
    client = anthropic.Anthropic()
    msg = client.messages.create(
        model=C.CLAUDE_MODEL,
        max_tokens=6000,
        system=SYSTEM,
        tools=[TOOL],
        tool_choice={"type": "tool", "name": "submit_decisions"},
        messages=[{"role": "user", "content": "Datos de hoy (JSON):\n" + json.dumps(context, ensure_ascii=False)}],
    )
    for block in msg.content:
        if block.type == "tool_use":
            out = dict(block.input)
            out["_usage"] = {"input": msg.usage.input_tokens, "output": msg.usage.output_tokens}
            return out
    raise RuntimeError("Claude no devolvió decisiones")


def _mock(ctx):
    """Gestor por reglas (sin API): 20 posiciones a pesos iguales con los mejores del cribado.
    Vende lo que cae fuera de los 60 primeros o deja de cumplir los filtros (margen para no rotar por ruido)."""
    target_n, keep_rank = 20, 60
    w = round((1 - C.MIN_CASH - 0.01) / target_n, 4)
    dec, keep = [], []
    for p in ctx["portfolio"]["positions"]:
        rank = p.get("rank")
        if rank is None or rank > keep_rank:
            why = "ya no cumple los filtros de calidad" if rank is None else f"cae al puesto {int(rank)} del cribado"
            dec.append({"ticker": p["ticker"], "target_weight": 0, "reason": f"Reglas: {why}."})
        else:
            keep.append(p["ticker"])
    for c in ctx["candidates"][: max(0, target_n - len(keep))]:
        dec.append({"ticker": c["ticker"], "target_weight": w, "reason": (
            f"Reglas: puesto {c.get('rank', '?')} del cribado (calidad {c.get('q_score', 0):.2f}, "
            f"valor {c.get('v_score', 0):.2f}, momentum {c.get('m_score', 0):.2f}).")})
    n_out = sum(1 for d in dec if d["target_weight"] == 0)
    n_in = len(dec) - n_out
    view = (f"Gestión por reglas: {n_in} entradas y {n_out} salidas." if dec
            else "Gestión por reglas: la cartera sigue dentro de los criterios, sin cambios.")
    return {"market_view": view, "decisions": dec, "notes_for_tomorrow": ""}


# ---------------- Fondo de catalizadores ----------------
SYSTEM_EP = f"""Eres el gestor de un fondo de demostración (dinero ficticio) que opera "episodic pivots" en
small y microcaps de EE. UU.: acciones que abren con un hueco fuerte (>= {C.EP_MIN_GAP:.0%}) y volumen
anormal tras un catalizador que puede cambiar la percepción del negocio durante semanas.

Tu trabajo cada tarde, tras el cierre:
1. Revisar las posiciones abiertas y decidir si alguna debe venderse mañana en la apertura
   (además de los stops automáticos, que el sistema ya gestiona).
2. Elegir, entre los candidatos detectados hoy, cuáles comprar mañana en la apertura y con qué peso.

Criterios que valoras:
- Catalizador real y duradero: resultados muy por encima de lo esperado con crecimiento, guía al alza,
  contrato grande, aprobación regulatoria, adquisición estratégica. Desconfía de notas de prensa vacías,
  "alianzas" sin cifras, giros a cripto/IA sin negocio detrás.
- Dilución: formularios S-1/S-3/F-3/424B recientes, ventas no registradas de acciones (8-K 3.02), aumento
  fuerte del número de acciones o poca caja con pérdidas son señales de que la empresa venderá en la subida.
  Avisos de exclusión de cotización o contrasplits son bandera roja.
- Calidad de la subida: cierre en la parte alta del rango del día, volumen muy alto, la acción venía de
  consolidar o de tendencia alcista (no de un desplome de años).
- Es mejor no comprar nada que comprar algo mediocre. Muchos días lo correcto es cero compras.

Reglas del sistema: máximo {C.EP_MAX_POSITIONS} posiciones, peso máximo {C.EP_MAX_WEIGHT:.0%} por posición,
{C.EP_MIN_CASH:.0%} mínimo de liquidez. Stop inicial bajo el mínimo del día de la señal (nunca más del
{C.EP_MAX_STOP:.0%} bajo la entrada). Si abre más de un {C.EP_MAX_CHASE:.0%} por encima del cierre de la
señal, la compra se cancela. Al +{C.EP_TAKE_PROFIT:.0%} se vende un tercio y el stop sube a la entrada.
Tras 3 sesiones, un cierre bajo la media de 10 días provoca la venta.

Escribe en español, conciso. Usa la herramienta submit_ep_decisions."""

TOOL_EP = {
    "name": "submit_ep_decisions",
    "description": "Registra las órdenes para la apertura de mañana.",
    "input_schema": {
        "type": "object",
        "properties": {
            "market_view": {"type": "string", "description": "2-4 frases: qué ha pasado hoy y por qué decides lo que decides."},
            "buys": {"type": "array", "items": {"type": "object", "properties": {
                "ticker": {"type": "string"},
                "weight": {"type": "number", "description": "Peso objetivo, máximo 0.15"},
                "reason": {"type": "string", "description": "Catalizador y por qué es duradero, 1-2 frases."}},
                "required": ["ticker", "weight", "reason"]}},
            "sells": {"type": "array", "items": {"type": "object", "properties": {
                "ticker": {"type": "string"},
                "reason": {"type": "string"}},
                "required": ["ticker", "reason"]}},
            "rejected_notes": {"type": "string", "description": "Por qué descartas los candidatos principales que no compras."},
            "notes_for_tomorrow": {"type": "string"},
        },
        "required": ["market_view", "buys", "sells", "notes_for_tomorrow"],
    },
}


def decide_ep(context: dict) -> dict:
    if C.MOCK_MANAGER:
        return _rules_ep(context)
    import anthropic
    client = anthropic.Anthropic()
    msg = client.messages.create(
        model=C.CLAUDE_MODEL, max_tokens=6000, system=SYSTEM_EP, tools=[TOOL_EP],
        tool_choice={"type": "tool", "name": "submit_ep_decisions"},
        messages=[{"role": "user", "content": "Datos de hoy (JSON):\n" + json.dumps(context, ensure_ascii=False)}],
    )
    for block in msg.content:
        if block.type == "tool_use":
            out = dict(block.input)
            out["_usage"] = {"input": msg.usage.input_tokens, "output": msg.usage.output_tokens}
            return out
    raise RuntimeError("Claude no devolvió decisiones")


def _rules_ep(ctx):
    """Gestor por reglas para catalizadores (sin API). Compra hasta 3 al día si:
    hay un 8-K reciente (catalizador documentado), sin registros de ampliación en 6 meses,
    acciones en circulación +20% como mucho en un año, sin avisos de exclusión, y cierre en la mitad alta del día."""
    ok, why_not = [], []
    for c in ctx["candidates"]:
        items = [i for k in c.get("recent_8k", []) for i in k.get("items", [])]
        red = [i for i in items if "exclusión" in i or "contrasplit" in i or "venta no registrada" in i]
        fails = []
        if not c.get("recent_8k"):
            fails.append("sin 8-K reciente")
        if c.get("dilution_filings_180d"):
            fails.append("registros de ampliación")
        if (c.get("shares_change_1y") or 0) > 0.20:
            fails.append("muchas acciones nuevas")
        if red:
            fails.append("bandera roja en 8-K")
        if c.get("close_in_range", 0) < 0.5:
            fails.append("cierre débil")
        if fails:
            why_not.append(f"{c['ticker']} ({', '.join(fails)})")
        else:
            ok.append(c)
    ok.sort(key=lambda c: -(c["gap"] * c["rvol"]))
    buys = []
    for c in ok[:3]:
        items = ", ".join(i for i in c["recent_8k"][0].get("items", []) if i != "anexos")
        buys.append({"ticker": c["ticker"], "weight": 0.10, "reason": (
            f"Reglas: hueco {c['gap']:+.0%} con volumen {c['rvol']:.0f}x; 8-K: {items or 'sin detalle'}; "
            "sin ampliaciones registradas.")})
    view = (f"Gestión por reglas: {len(ctx['candidates'])} candidatos, {len(buys)} {'cumple' if len(buys) == 1 else 'cumplen'} todos los filtros."
            if ctx["candidates"] else "Gestión por reglas: sin candidatos hoy.")
    return {"market_view": view, "buys": buys, "sells": [], "notes_for_tomorrow": "",
            "rejected_notes": ("Descartados: " + "; ".join(why_not[:10])) if why_not else ""}
