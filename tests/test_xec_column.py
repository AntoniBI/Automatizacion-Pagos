"""
tests/test_xec_column.py — Columna "Nª Xec" en la hoja Resumen_Musicos.

Verifica que create_excel_export añade la columna "Nª Xec" como última columna
de Resumen_Musicos: correlativa ascendente/descendente si se pasa xec_start,
y vacía si no se pasa. Ejecutar con: python tests/test_xec_column.py
"""

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.excel_export import create_excel_export


class FakeSystem:
    def __init__(self):
        self.presupuesto_df = pd.DataFrame({
            "ACTES": ["Acte 1", "Acte 2"],
            "A REPARTIR": [300.0, 200.0],
        })


def build_results():
    musician_summary = pd.DataFrame({
        "Musico": ["Ana", "Bernat", "Carla"],
        "Categoria": ["A", "B", "A"],
        "Importe_Individual": [120.0, 90.0, 110.0],
    })
    budget_comparison = pd.DataFrame({
        "ACTES": ["Acte 1", "Acte 2"],
        "A REPARTIR": [300.0, 200.0],
        "Distribuido_Real": [300.0, 200.0],
        "Diferencia": [0.0, 0.0],
    })
    payment_pivot = pd.DataFrame(
        {"Acte 1": [60.0, 45.0, 55.0], "Acte 2": [60.0, 45.0, 55.0]},
        index=["Ana", "Bernat", "Carla"],
    )
    musicians_by_category = pd.DataFrame({
        "Categoria": ["A", "B"],
        "Cantidad": [2, 1],
    })
    attendees_detail = pd.DataFrame({
        "Acto": ["Acte 1", "Acte 1", "Acte 2"],
        "Musico": ["Ana", "Bernat", "Carla"],
        "Importe_Individual": [60.0, 45.0, 55.0],
    })
    return {
        "musician_summary": musician_summary,
        "budget_comparison": budget_comparison,
        "payment_pivot": payment_pivot,
        "musicians_by_category": musicians_by_category,
        "attendees_detail": attendees_detail,
    }


def read_resumen(buffer):
    return pd.read_excel(buffer, sheet_name="Resumen_Musicos", engine="openpyxl")


def main():
    system = FakeSystem()

    # Ascendente
    warnings = []
    buffer = create_excel_export(build_results(), system, warnings=warnings, xec_start=100, xec_dir="asc")
    assert not warnings, f"Avisos inesperados: {warnings}"
    df = read_resumen(buffer)
    assert df.columns[-1] == "Nª Xec", f"Última columna: {df.columns[-1]!r}"
    assert list(df["Nª Xec"]) == [100, 101, 102], f"Asc: {list(df['Nª Xec'])}"

    # Descendente
    warnings = []
    buffer = create_excel_export(build_results(), system, warnings=warnings, xec_start=100, xec_dir="desc")
    assert not warnings, f"Avisos inesperados: {warnings}"
    df = read_resumen(buffer)
    assert list(df["Nª Xec"]) == [100, 99, 98], f"Desc: {list(df['Nª Xec'])}"

    # Sin número inicial: columna presente pero vacía
    warnings = []
    buffer = create_excel_export(build_results(), system, warnings=warnings)
    assert not warnings, f"Avisos inesperados: {warnings}"
    df = read_resumen(buffer)
    assert df.columns[-1] == "Nª Xec", f"Última columna: {df.columns[-1]!r}"
    assert df["Nª Xec"].isna().all(), f"Debería estar vacía: {list(df['Nª Xec'])}"

    print("OK: columna 'Nª Xec' correcta (asc, desc y vacía)")


if __name__ == "__main__":
    main()
