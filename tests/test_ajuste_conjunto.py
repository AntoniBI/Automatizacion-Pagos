"""
tests/test_ajuste_conjunto.py — Ajuste conjunto de ponderaciones y presupuestos.

Cuando se ajustan varios actos a la vez, un músico de una categoría debe cobrar
LO MISMO en todos ellos (también los de categoría A, que es lo que fallaba al
encadenar "ponderación A automática" + "igualar presupuestos") y cada acto debe
seguir repartiendo su presupuesto entero.

El criterio: se calcula una ponderación base común a todos los actos y cada acto
escala ese bloque completo (A, B, C, D y E) por N_asistentes / masa_base, con el
presupuesto ajustado a esa masa. Así el importe por categoría es idéntico en
todos los actos y la diferencia por acto sigue siendo ≥ 0.

Ejecutar con: python tests/test_ajuste_conjunto.py
"""

import sys
from io import BytesIO
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.core import MusicianPaymentSystem

CATS = ["A", "B", "C", "D", "E"]
# Tres actos con composición muy distinta (la A pesa 40%, 52% y 25%)
ASISTENCIA = {
    "Acte 1": {"A": 16, "B": 7, "C": 6, "D": 3, "E": 8},
    "Acte 2": {"A": 22, "B": 6, "C": 6, "D": 3, "E": 5},
    "Acte 3": {"A": 5, "B": 5, "C": 4, "D": 3, "E": 3},
}
PRESUPUESTOS = {"Acte 1": 2650.0, "Acte 2": 1930.0, "Acte 3": 900.0}


def build_excel():
    filas = []
    for cat in CATS:
        for i in range(max(a[cat] for a in ASISTENCIA.values())):
            filas.append({"Nombre": f"{cat}{i}", "Apellidos": "X",
                          "Instrumento": "Flauta", "Categoria": cat,
                          **{acto: 1 if i < ASISTENCIA[acto][cat] else 0 for acto in ASISTENCIA}})
    asistencia = pd.DataFrame(filas)
    presupuesto = pd.DataFrame({
        "ACTES": list(ASISTENCIA),
        "A REPARTIR": [PRESUPUESTOS[a] for a in ASISTENCIA],
    })
    configuracion = pd.DataFrame({
        "ACTES": list(ASISTENCIA),
        "A": [1.29, 1.10, 1.20], "B": [0.80, 0.80, 0.80],
        "C": [0.70, 0.70, 0.70], "D": [0.60, 0.60, 0.60], "E": [0.50, 0.50, 0.50],
    })
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        asistencia.to_excel(writer, sheet_name="Asistencia", index=False)
        presupuesto.to_excel(writer, sheet_name="Presupuesto", index=False)
        configuracion.to_excel(writer, sheet_name="Configuracion_Precios", index=False)
    buffer.seek(0)
    return buffer


def pagos_por_categoria(system, actos):
    """Importe que cobra un músico de cada categoría en cada acto."""
    pesos = system.editing_weights.set_index("ACTES")
    presupuestos = system.presupuesto_df.set_index("ACTES")["A REPARTIR"]
    pagos = {}
    for acto in actos:
        asistentes = sum(ASISTENCIA[acto].values())
        retencion = system.get_band_retention_for_event(acto)
        neto = float(presupuestos[acto]) * (1 - retencion / 100)
        pagos[acto] = {c: (neto / asistentes) * float(pesos.loc[acto, c]) for c in CATS}
    return pagos


def comprobar(system, actos, total_esperado, tag, decimales=4):
    pagos = pagos_por_categoria(system, actos)
    referencia = pagos[actos[0]]
    for acto in actos[1:]:
        for c in CATS:
            assert abs(pagos[acto][c] - referencia[c]) < 0.01, (
                f"{tag}: la categoría {c} cobra distinto en {acto} "
                f"({pagos[acto][c]:.4f}) que en {actos[0]} ({referencia[c]:.4f})"
            )

    pesos = system.editing_weights.set_index("ACTES")
    presupuestos = system.presupuesto_df.set_index("ACTES")["A REPARTIR"]
    total = 0.0
    for acto in actos:
        asistentes = sum(ASISTENCIA[acto].values())
        neto = float(presupuestos[acto]) * (1 - system.get_band_retention_for_event(acto) / 100)
        repartido = sum(ASISTENCIA[acto][c] * pagos[acto][c] for c in CATS)
        diff = neto - repartido
        assert diff >= -1e-6, f"{tag}: {acto} reparte más que su neto (diff={diff:.6f})"
        # Las ponderaciones se truncan a `decimales` para no repartir de más, así
        # que lo que queda sin repartir no puede pasar de neto · 10^-decimales.
        tope = neto * 10 ** -decimales + 1e-9
        assert diff <= tope, f"{tag}: {acto} deja {diff:.4f} € sin repartir (tope {tope:.4f})"
        total += float(presupuestos[acto])
    assert abs(total - total_esperado) < 0.01, f"{tag}: el total cambió ({total:.2f} ≠ {total_esperado})"

    # La proporción entre categorías debe ser la misma en todos los actos
    for acto in actos:
        ratio = float(pesos.loc[acto, "A"]) / float(pesos.loc[acto, "C"])
        ref = float(pesos.loc[actos[0], "A"]) / float(pesos.loc[actos[0], "C"])
        assert abs(ratio - ref) < 1e-3, f"{tag}: {acto} rompe la proporción A/C ({ratio:.4f} ≠ {ref:.4f})"
    return pagos


def main():
    actos = list(ASISTENCIA)
    total = sum(PRESUPUESTOS.values())

    # --- Sin retención ---
    system = MusicianPaymentSystem()
    assert system.load_from_uploaded_file(build_excel()), system.messages
    cambios, saltados, resumen = system.apply_ajuste_conjunto(actos, total, decimales=4)
    assert not saltados, f"Actos saltados: {saltados}"
    assert len(cambios) == 3, f"Se esperaban 3 actos ajustados: {cambios}"
    pagos = comprobar(system, actos, total, "sin retención")
    print("  sin retención: " + " · ".join(f"{c}={pagos[actos[0]][c]:.2f} €" for c in CATS))

    # --- Con retención distinta por acto ---
    system = MusicianPaymentSystem()
    assert system.load_from_uploaded_file(build_excel()), system.messages
    system.set_band_retention([
        {"ACTES": "Acte 1", "BANDA_PORCENTAJE": 20.0},
        {"ACTES": "Acte 3", "BANDA_PORCENTAJE": 10.0},
    ])
    cambios, saltados, resumen = system.apply_ajuste_conjunto(actos, total, decimales=4)
    assert not saltados, f"Actos saltados: {saltados}"
    pagos = comprobar(system, actos, total, "con retención")
    print("  con retención: " + " · ".join(f"{c}={pagos[actos[0]][c]:.2f} €" for c in CATS))

    # El resumen describe el bloque base y lo que cobra cada categoría
    assert resumen["A_base"] > 0 and resumen["valor_unitario"] > 0, resumen
    for c in CATS:
        assert abs(resumen["pagos"][c] - pagos[actos[0]][c]) < 0.01, resumen

    print("OK: ajuste conjunto — todas las categorías cobran igual en todos los actos")


if __name__ == "__main__":
    main()
