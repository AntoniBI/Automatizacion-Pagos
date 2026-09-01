# CLAUDE.md

Guía para Claude Code (claude.ai/code) al trabajar en este repositorio.

## Visión general

Sistema de Cobro Musical: aplicación web para automatizar el cálculo de pagos a
músicos de sociedades musicales valencianas a partir de los datos de asistencia a
los actos.

Arquitectura **FastAPI + HTML/CSS/JS (vanilla)**. Migrada desde una versión
Streamlit, conservando **exactamente la misma lógica de cálculo** (verificada con
un test de paridad). La versión Streamlit se conserva en `legacy/` solo como
referencia de paridad.

## Puesta en marcha

```bash
pip install -r requirements.txt
python run.py              # arranca uvicorn en http://127.0.0.1:8000 y abre el navegador
# o doble clic en start_web.bat (Windows)
```

Desarrollo con recarga:

```bash
uvicorn backend.server:app --reload
```

Verificar que la lógica sigue siendo idéntica a la original:

```bash
python tests/parity_check.py
```

## Estructura del proyecto

```
backend/                 Paquete Python (servidor + lógica de negocio)
  core.py                Motor de cálculo (MusicianPaymentSystem), sin UI
  pricing.py             Ponderaciones automáticas, igualar presupuestos y ajuste conjunto
  excel_export.py        Generación de los ficheros Excel de resultados
  server.py              API REST (FastAPI) + servido del frontend estático
frontend/                Cliente web (servido en /static)
  index.html             SPA + sprite de iconos SVG (#i-*)
  assets/                logo.png, favicon.png, escudo-original.jpg
  css/styles.css         Tema visual (tokens en :root)
  js/api.js              Cliente HTTP
  js/ui.js               Helpers: formato, toasts, tablas, tabs, svgIcon()
  js/app.js              Router + controladores de página
Data/                    Archivos Excel de ejemplo (Actes.xlsx, Miembros.xlsx)
docs/                    Documentación de usuario
legacy/streamlit_app.py  App Streamlit original (referencia de paridad)
tests/parity_check.py    Compara backend.core con la lógica original
run.py / start_web.bat   Lanzadores
```

## Estructura de datos

El Excel de entrada tiene tres hojas:

1. **Asistencia**: músicos × actos, con asistencia binaria (1/0).
2. **Presupuesto**: importes por acto (`ACTES`, `A REPARTIR`, COBRAT, LLOGATS, TRANSPORT…).
3. **Configuracion_Precios**: ponderaciones por categoría (`ACTES`, A, B, C, D, E).

El número de actos es dinámico: la app se adapta a las columnas presentes.

## Arquitectura

- `backend/server.py`: API REST. Estado por usuario en sesiones en memoria
  identificadas por cookie (`cobro_session`); cada sesión tiene su propia
  instancia de `MusicianPaymentSystem`. Sirve `frontend/` en `/static` y el
  `index.html` en `/`.
- `backend/core.py`: toda la lógica de cálculo, carga de Excel y agregados, sin
  ninguna dependencia de UI. Importa `pricing` de forma perezosa donde hace falta.
- `frontend/js/app.js`: router de páginas (Dashboard, Ponderaciones, Retención,
  Análisis, Procesar) que consume la API y pinta tablas/gráficos (Plotly).

### Iconografía
Los iconos son SVG de línea definidos como `<symbol id="i-*">` en un sprite al
inicio de `index.html`. Se usan con `<svg class="ico"><use href="#i-nombre">` en
el HTML y con el helper `UI.svgIcon(nombre)` en el JS dinámico. **No usar emojis**
como iconos de interfaz.

## Fórmula de reparto

```
Importe individual = (A_REPARTIR_NETO / total_asistentes) × ponderación
```

donde `A_REPARTIR_NETO` aplica la retención de banda configurada para el acto.

### Ajuste conjunto de varios actos

`ponderación A automática` despeja A por acto, así que un músico de categoría A
cobra distinto en cada acto (A absorbe la composición del acto); B, C, D y E no,
porque son las mismas en todos. Para que **todas** las categorías cobren lo mismo
en varios actos sin dejar dinero sin repartir está `apply_ajuste_conjunto`: usa
una ponderación base común y cada acto escala ese bloque completo por
`N_asistentes / masa_base`, con el presupuesto fijado en proporción a esa masa.
El precio: C/D/E dejan de ser 0,700/0,600/0,500 exactos en cada acto, pero la
proporción entre categorías es idéntica en todos.

## Reglas al modificar

- Si cambias `backend/core.py` o `backend/pricing.py`, ejecuta
  `python tests/parity_check.py`: debe seguir dando **PARIDAD TOTAL**.
- `legacy/` es solo referencia; no añadir funcionalidad nueva ahí.
