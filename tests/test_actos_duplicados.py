"""
tests/test_actos_duplicados.py — Actos con nombre repetido y espacios sobrantes.

Reproduce dos fallos vistos con ficheros reales:

  1. Dos actos con el MISMO nombre ("Festes Olleria" en dos ediciones distintas).
     pandas renombra la segunda columna de Asistencia a "Festes Olleria.1" pero
     deja las dos filas duplicadas en Presupuesto/Configuración, así que
     `set_index('ACTES').loc[acto]` devolvía un DataFrame y el cálculo automático
     de ponderaciones reventaba con "The truth value of a Series is ambiguous".

  2. Nombres con espacios sobrantes en las cabeceras de Asistencia
     ("Mig any a Castello ") que no casaban con la fila ya recortada de
     Configuración, y hacían que igualar presupuestos lanzara un KeyError.

Ejecutar con: python tests/test_actos_duplicados.py
"""

import sys
from io import BytesIO
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.core import MusicianPaymentSystem


ACTOS = ["Festes Olleria", "Festes Olleria", "Mig any a Castello", "Acte Oficial"]


def build_excel():
    """Excel con un acto duplicado y cabeceras con espacios sobrantes."""
    asistencia = pd.DataFrame({
        "Nombre": ["Ana", "Bernat", "Carla", "David"],
        "Apellidos": ["U", "D", "T", "Q"],
        "Instrumento": ["Flauta", "Clarinet", "Trompeta", "Bombo"],
        "Categoria": ["A", "A", "B", "C"],
        # Duplicado exacto: la cabecera se reescribe abajo para que las dos
        # columnas se llamen igual y pandas lea la segunda como "Festes Olleria.1"
        "Festes Olleria": [1, 1, 1, 0],
        "Festes Olleria (dup)": [1, 0, 1, 1],
        # Espacios sobrantes que no están en las otras hojas
        " Mig any a Castello ": [1, 1, 0, 1],
        "Acte Oficial": [1, 1, 1, 1],
    })
    presupuesto = pd.DataFrame({
        "ACTES": ACTOS,
        "A REPARTIR": [2650.0, 1930.0, 800.0, 0.0],
    })
    configuracion = pd.DataFrame({
        "ACTES": ACTOS,
        "A": [1.29, 1.10, 1.00, 0.0],
        "B": [0.80, 0.80, 0.80, 0.0],
        "C": [0.70, 0.70, 0.70, 0.0],
        "D": [0.60, 0.60, 0.60, 0.0],
        "E": [0.50, 0.50, 0.50, 0.0],
    })

    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        asistencia.to_excel(writer, sheet_name="Asistencia", index=False)
        # Cabecera duplicada literal (columna F), como en los ficheros reales
        writer.sheets["Asistencia"].cell(row=1, column=6, value="Festes Olleria")
        presupuesto.to_excel(writer, sheet_name="Presupuesto", index=False)
        configuracion.to_excel(writer, sheet_name="Configuracion_Precios", index=False)
    buffer.seek(0)
    return buffer


def main():
    system = MusicianPaymentSystem()
    assert system.load_from_uploaded_file(build_excel()), \
        f"No se pudo cargar el Excel: {system.messages}"

    eventos = system.get_events_list()
    assert len(set(eventos)) == len(eventos), f"Actos repetidos tras la carga: {eventos}"
    assert "Festes Olleria" in eventos and "Festes Olleria (2)" in eventos, \
        f"El acto duplicado no se ha desambiguado: {eventos}"
    assert "Mig any a Castello" in eventos, \
        f"Los espacios sobrantes no se han limpiado: {eventos}"

    # Las tres hojas deben hablar de los mismos actos
    assert set(system.presupuesto_df["ACTES"]) == set(eventos), \
        f"Presupuesto descuadrado: {sorted(set(system.presupuesto_df['ACTES']))}"
    assert set(system.configuracion_df["ACTES"]) == set(eventos), \
        f"Configuración descuadrada: {sorted(set(system.configuracion_df['ACTES']))}"

    # Cada edición conserva su propio presupuesto
    importes = system.presupuesto_df.set_index("ACTES")["A REPARTIR"]
    assert float(importes["Festes Olleria"]) == 2650.0
    assert float(importes["Festes Olleria (2)"]) == 1930.0

    no_oficiales = system.get_non_official_events()
    assert "Acte Oficial" not in no_oficiales, f"Acto oficial incluido: {no_oficiales}"

    # 1) Ponderación automática (antes: ValueError Series ambiguous)
    cambios, saltados = system.apply_auto_ponderacion(no_oficiales, decimales=4)
    recalculados = {c["Acto"] for c in cambios}
    assert {"Festes Olleria", "Festes Olleria (2)"} <= recalculados, \
        f"Faltan actos por recalcular: {recalculados} / saltados={saltados}"
    for cambio in cambios:
        assert cambio["Diff (€)"] >= -1e-9, f"Diferencia negativa en {cambio['Acto']}: {cambio}"

    # 2) Igualar presupuestos (antes: KeyError por el nombre con espacios)
    changes_log, valor_unitario = system.apply_equalize_budgets(no_oficiales, 6000.0)
    assert valor_unitario > 0, f"Valor unitario inválido: {valor_unitario}"
    total = sum(c["Nuevo"] for c in changes_log)
    assert abs(total - 6000.0) < 1e-6, f"El reparto no suma el presupuesto: {total}"

    print("OK: actos duplicados y con espacios sobrantes tratados correctamente")


if __name__ == "__main__":
    main()
