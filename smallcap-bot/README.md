# Fondos demo de small caps gestionados por Claude

Dos fondos con dinero ficticio (100.000 $ cada uno) que se comparan en el mismo panel:

- **Calidad + valor** (`bot/run_daily.py`): cartera diversificada y paciente sobre el S&P 600.
- **Catalizadores** (`bot/catalyst.py`): episodic pivots en small y microcaps, concentrado y de días o semanas.

## Fondo 1: calidad + valor

Bot que cada día, tras el cierre de Wall Street, revisa las ~600 empresas del S&P SmallCap 600,
hace un cribado de calidad + valor + momentum, le pasa a Claude la cartera y los 40 mejores
candidatos, y ejecuta sus decisiones en un broker simulado con dinero ficticio (100.000 $).
Todo queda guardado en Supabase y se ve en un panel web, con el motivo de cada operación.

### Cómo funciona cada día

1. **Universo**: componentes del S&P 600 (descarga de SPDR; si falla, Wikipedia).
2. **Datos**: precios de 14 meses con Yahoo Finance; fundamentales refrescados por lotes (cada valor, como mucho, cada 7 días).
3. **Cribado**: filtra empresas con EBITDA y caja libre positivos, deuda neta/EBITDA < 3, precio > 3 $ y volumen > 3 M$/día. Puntúa 40 % calidad, 40 % valor y 20 % momentum.
4. **Stop-loss**: vende automáticamente lo que caiga un 25 % sobre su coste.
5. **Decisión**: Claude recibe cartera, rentabilidad frente a índices, candidatos y sus notas de los últimos 5 días, y devuelve pesos objetivo con su tesis.
6. **Broker**: aplica las reglas aunque Claude se equivoque (máx. 7 % por empresa, 15–25 posiciones, 30 % por sector, 2 % de liquidez, rotación diaria ≤ 25 %, coste 0,2 % por operación) y ejecuta al precio de cierre.
7. **Guardado**: patrimonio, operaciones, posiciones e informe del día en Supabase.

## Fondo 2: catalizadores (episodic pivots)

Busca acciones que abren con un hueco fuerte tras una noticia que puede cambiar el negocio, y trata de
capturar la continuación de los días o semanas siguientes. Cada tarde:

1. **Ejecuta las órdenes de ayer en la apertura de hoy**, con un 0,5 % de deslizamiento. Si la acción abre más de un 8 % por encima del cierre de la señal, cancela la compra para no perseguirla.
2. **Aplica los stops** con el mínimo del día. Si abre por debajo del stop, vende al precio de apertura.
3. **Programa salidas por reglas** para mañana: vende un tercio al +30 % y sube el stop a la entrada; tras 3 sesiones, un cierre bajo la media de 10 días provoca la venta.
4. **Escanea ~2.800 acciones** de 50 M$ a 5.000 M$ (sin China ni Hong Kong, por el historial de manipulaciones) buscando hueco ≥ 10 %, volumen ≥ 3 veces la media de 50 sesiones y más de 5 M$ negociados.
5. **Enriquece los 15 mejores** con fundamentales, evolución del número de acciones en el último año y la SEC: 8-K recientes con extracto de la nota de prensa, y formularios de ampliación de capital (S-1, S-3, 424B…) de los últimos 6 meses.
6. **Claude decide** qué comprar mañana y con qué peso (máx. 15 % por posición, 10 posiciones, 5 % de liquidez), y puede vender posiciones cuya tesis haya cambiado. Lo normal es que muchos días no compre nada.

El stop inicial va bajo el mínimo del día de la señal, y nunca más de un 12 % por debajo de la entrada.

### Qué esperar y cómo juzgarlo
Este estilo suele acertar solo en un 30-40 % de las operaciones y depende de que las ganadoras sean mucho
mayores que las perdedoras. Además de la rentabilidad frente al índice, fíjate en la caída máxima (aparece en
el panel) y en el historial de operaciones. Hacen falta al menos 6-12 meses para sacar conclusiones.

## Puesta en marcha (unos 20 minutos)

### 1. Supabase
1. Crea un proyecto nuevo.
2. En *SQL Editor*, pega y ejecuta `supabase/schema.sql`.
3. En *Project Settings → API* copia la **URL**, la **anon key** (para el panel) y la **service_role key** (para el bot; no la publiques nunca).

### 2. GitHub
1. Crea un repositorio y sube esta carpeta.
2. En *Settings → Secrets and variables → Actions → Secrets* añade:
   - `ANTHROPIC_API_KEY`
   - `SUPABASE_URL`
   - `SUPABASE_SERVICE_KEY` (la service_role)
3. En *Variables* añade `SEC_USER_AGENT` con un nombre y tu email (la SEC lo exige para identificar a quien consulta), por ejemplo `Guillermo bot demo tu@email.com`. Opcional: `CLAUDE_MODEL` para cambiar de modelo (por defecto `claude-sonnet-5-5`).
4. Ve a *Actions → Fondos small caps diarios → Run workflow* para lanzar la primera sesión. Tarda unos 15 minutos. A partir de ahí se ejecuta solo de lunes a viernes a las 22:30 UTC.

### 3. Panel
1. Abre `docs/index.html` y rellena `SUPABASE_URL` y `SUPABASE_ANON_KEY` al principio del archivo.
2. Actívalo en *Settings → Pages → Branch: main, carpeta /docs*.
   Sin configurar, el panel muestra datos de ejemplo.

La anon key solo permite leer (las políticas de `schema.sql` lo garantizan), así que puede ir en el panel.
Si el repositorio es público, cualquiera con el enlace verá el fondo.

## Funcionar sin API (gratis)

Crea en GitHub la variable `MANAGER_MODE` con el valor `reglas` y no necesitarás `ANTHROPIC_API_KEY`.
En ese modo las decisiones las toman reglas fijas:

- **Calidad + valor**: 20 posiciones a pesos iguales con los mejores del cribado; vende lo que cae fuera de los 60 primeros o deja de cumplir los filtros.
- **Catalizadores**: compra hasta 3 al día (10 % cada una) entre los candidatos que tengan un 8-K reciente, ningún registro de ampliación en 6 meses, menos de un 20 % de acciones nuevas en un año, ningún aviso de exclusión o contrasplit y cierre en la mitad alta del día.

Para pasar a que decida Claude, cambia la variable a `claude` y añade el secreto con la clave de la API.

## Probar en local sin API ni Supabase

```bash
pip install -r requirements.txt
STORE=local MOCK_MANAGER=1 python -m bot.run_daily
STORE=local MOCK_MANAGER=1 python -m bot.catalyst
```
Guarda todo en `data/` y usa gestores de prueba sencillos en lugar de la API.

## Ajustar la estrategia

Todas las reglas de ambos fondos están en `bot/config.py` (las del segundo empiezan por `EP_`) y se pueden cambiar con variables de entorno
(por ejemplo `MAX_WEIGHT=0.05`, `STOP_LOSS=0.2`, `INITIAL_CAPITAL=50000`).
El criterio del gestor está en los prompts de `bot/manager.py`, y la fórmula del cribado en `bot/screen.py`.

## Coste

Dos llamadas a la API al día (una por fondo), de 15 a 40 mil tokens de entrada cada una. Con Sonnet son céntimos al día;
consulta los precios actuales en la web de Anthropic. GitHub Actions y el plan gratuito de Supabase sobran.

## Limitaciones a tener en cuenta

- Datos gratuitos de Yahoo: a veces faltan o vienen con errores en empresas pequeñas.
- El fondo de calidad ejecuta al cierre del mismo día, algo optimista; el de catalizadores ejecuta en la apertura siguiente, más realista.
- Los stops se simulan con datos diarios: si el mínimo del día toca el stop, se asume la venta a ese precio, aunque en la realidad podría salir peor.
- En microcaps el deslizamiento real puede superar el 0,5 % simulado, sobre todo en aperturas con mucho movimiento.
- Los precios están ajustados por dividendos, así que los dividendos se reflejan de forma aproximada.
- El universo es el S&P 600 actual (sesgo de supervivencia leve para comparar con el pasado, no afecta a la simulación hacia delante).
- GitHub desactiva los workflows programados de repositorios públicos tras 60 días sin actividad; haz algún commit de vez en cuando.
- Es una simulación educativa, no asesoramiento financiero.
