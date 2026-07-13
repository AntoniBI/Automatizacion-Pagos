# Columna "Nª Xec" en el Excel de resultados

**Fecha:** 2026-07-13 · **Estado:** aprobado

## Objetivo

Numerar los cheques de los músicos directamente en el Excel de resultados.
En la página **Procesar** (tarjeta "Descargar Resultados") el usuario puede
indicar el primer número de cheque y la dirección de la numeración; la hoja
**Resumen_Musicos** (segunda hoja del Excel Completo) sale con una columna
**"Nª Xec"** correlativa.

## Decisiones

- **Posición:** "Nª Xec" es la **última columna** de `Resumen_Musicos`.
- **Alcance:** solo el **Excel Completo** (`/api/export/full`). El Excel
  Básico no cambia.
- **Campo vacío:** la columna aparece **siempre** en el Excel Completo; si no
  se indica número inicial, sale vacía para rellenarla a mano.
- **Dirección:** ascendente (100, 101, 102…) o descendente (100, 99, 98…),
  ascendente por defecto. En descendente se sigue restando aunque se llegue a
  números negativos (el usuario controla el rango de su talonario).
- **Orden:** la numeración sigue el orden de las filas de la hoja (una por
  músico).

## Diseño

- **Transporte:** parámetros de query en la descarga:
  `GET /api/export/full?xec_start=<int>&xec_dir=asc|desc`. Sin estado nuevo en
  sesión ni endpoints nuevos; la descarga sigue siendo un enlace directo.
- **`backend/excel_export.py`:** `create_excel_export(..., xec_start=None,
  xec_dir="asc")` añade la columna al DataFrame `musician_summary` antes de
  escribir la hoja.
- **`backend/server.py`:** `api_export` acepta los query params opcionales y
  los pasa solo cuando `kind == "full"`. Valida `xec_start` entero ≥ 0.
- **Frontend:** en `index.html`, encima de los botones de descarga, un input
  numérico "Primer Nº de cheque" y un select Ascendente/Descendente; en
  `app.js`, `download("full")` añade los params solo si hay número.
- **Sin cambios en `core.py`/`pricing.py`** → `tests/parity_check.py` debe
  seguir dando PARIDAD TOTAL.

## Pruebas

Test nuevo (`tests/test_xec_column.py`): genera el Excel con resultados
sintéticos y comprueba la columna en `Resumen_Musicos` en tres casos:
ascendente, descendente y sin número (columna vacía). Además, verificación
manual del flujo completo en la app.
