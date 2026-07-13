"""
backend/excel_export.py — Generación de los ficheros Excel de resultados.

Funciones idénticas a las del `legacy/streamlit_app.py` original (create_excel_export,
create_summary_sheet, create_simple_excel_export). Solo se han eliminado las
llamadas de UI `st.warning`: los avisos se acumulan en la lista `warnings`
opcional para que la capa que invoque decida cómo mostrarlos.
"""

from io import BytesIO

import pandas as pd


def create_excel_export(results, system, warnings=None, xec_start=None, xec_dir="asc"):
    """Crea el Excel completo con todas las hojas y formato profesional.

    xec_start/xec_dir controlan la columna "Nª Xec" de Resumen_Musicos:
    numeración correlativa desde xec_start (ascendente o descendente), o
    columna vacía si xec_start es None.
    """
    if warnings is None:
        warnings = []
    try:
        buffer = BytesIO()

        with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
            workbook = writer.book

            money_format = workbook.add_format({'num_format': '€#,##0.00'})
            header_format = workbook.add_format({
                'bold': True,
                'text_wrap': True,
                'valign': 'top',
                'fg_color': '#D7E4BC',
                'border': 1
            })

            # 1. HOJA RESUMEN GENERAL
            try:
                create_summary_sheet(writer, results, system, money_format, header_format, warnings)
            except Exception as e:
                warnings.append(f"Error creando hoja resumen: {e}")

            # 2. Format and write musician summary
            try:
                musician_summary = results['musician_summary'].copy()
                musician_summary['Importe_Individual'] = musician_summary['Importe_Individual'].round(2)

                if 'Penalizacion_Total' in musician_summary.columns:
                    musician_summary['Penalizacion_Total'] = musician_summary['Penalizacion_Total'].round(2)
                if 'Importe_Final' in musician_summary.columns:
                    musician_summary['Importe_Final'] = musician_summary['Importe_Final'].round(2)

                if xec_start is not None:
                    step = -1 if xec_dir == 'desc' else 1
                    musician_summary['Nª Xec'] = [int(xec_start) + i * step for i in range(len(musician_summary))]
                else:
                    musician_summary['Nª Xec'] = None

                musician_summary.to_excel(writer, sheet_name='Resumen_Musicos', index=False)

                worksheet = writer.sheets['Resumen_Musicos']

                for col_num, col_name in enumerate(musician_summary.columns):
                    if any(word in col_name for word in ['Importe', 'Penalizacion']):
                        worksheet.set_column(col_num, col_num, 15, money_format)

                for col_num, value in enumerate(musician_summary.columns.values):
                    worksheet.write(0, col_num, value, header_format)
            except Exception as e:
                warnings.append(f"Error creando hoja músicos: {e}")

            # 3. Format payment pivot
            try:
                payment_pivot = results['payment_pivot'].round(2)
                payment_pivot.to_excel(writer, sheet_name='Pagos_por_Acto')

                worksheet = writer.sheets['Pagos_por_Acto']
                for col in range(1, len(payment_pivot.columns) + 1):
                    worksheet.set_column(col, col, 12, money_format)
            except Exception as e:
                warnings.append(f"Error creando pivot de pagos: {e}")

            # 4. Format budget comparison (now includes band retention)
            try:
                budget_comparison = results['budget_comparison'].copy()
                for col in ['A REPARTIR', 'Distribuido_Real', 'Diferencia', 'Banda_Retencion_Amount', 'Neto_Para_Musicos']:
                    if col in budget_comparison.columns:
                        budget_comparison[col] = budget_comparison[col].round(2)

                budget_comparison.to_excel(writer, sheet_name='Comparacion_Presupuesto', index=False)

                worksheet = writer.sheets['Comparacion_Presupuesto']
                for col_num, col_name in enumerate(budget_comparison.columns):
                    if any(word in col_name.upper() for word in ['REPARTIR', 'DISTRIBUIDO', 'DIFERENCIA', 'RETENCION', 'NETO']):
                        worksheet.set_column(col_num, col_num, 15, money_format)
                    worksheet.write(0, col_num, col_name, header_format)
            except Exception as e:
                warnings.append(f"Error creando comparación presupuesto: {e}")

            # 5. Musicians by category
            try:
                results['musicians_by_category'].to_excel(writer, sheet_name='Musicos_por_Categoria', index=False)

                worksheet = writer.sheets['Musicos_por_Categoria']
                for col_num, value in enumerate(results['musicians_by_category'].columns.values):
                    worksheet.write(0, col_num, value, header_format)
            except Exception as e:
                warnings.append(f"Error creando músicos por categoría: {e}")

            # 6. Detailed attendance with proper formatting
            try:
                attendees_detail = results['attendees_detail'].copy()
                attendees_detail['Importe_Individual'] = attendees_detail['Importe_Individual'].round(2)
                attendees_detail.to_excel(writer, sheet_name='Detalle_Asistencia', index=False)

                worksheet = writer.sheets['Detalle_Asistencia']
                for col_num, col_name in enumerate(attendees_detail.columns):
                    if 'Importe' in col_name or 'REPARTIR' in col_name:
                        worksheet.set_column(col_num, col_num, 12, money_format)
                    worksheet.write(0, col_num, col_name, header_format)
            except Exception as e:
                warnings.append(f"Error creando detalle asistencia: {e}")

        buffer.seek(0)
        return buffer

    except Exception as e:
        raise e


def create_summary_sheet(writer, results, system, money_format, header_format, warnings=None):
    """Crea la hoja RESUMEN_GENERAL con métricas clave."""
    if warnings is None:
        warnings = []
    try:
        budget_summary = results['budget_comparison'][['ACTES', 'A REPARTIR', 'Distribuido_Real', 'Diferencia']].copy()
        budget_summary = budget_summary.round(2)

        total_budget = float(system.presupuesto_df['A REPARTIR'].sum())
        total_distributed = float(results['musician_summary']['Importe_Individual'].sum())
        total_musicians_paid = len(results['musician_summary'])
        avg_payment = float(results['musician_summary']['Importe_Individual'].mean())

        try:
            category_summary = results['musician_summary']['Categoria'].value_counts().reset_index()
            category_summary.columns = ['Categoria', 'Cantidad_Musicos']
            category_earnings = results['musician_summary'].groupby('Categoria')['Importe_Individual'].sum().reset_index()
            category_summary = category_summary.merge(category_earnings, on='Categoria')
            category_summary['Importe_Individual'] = category_summary['Importe_Individual'].round(2)
        except Exception as e:
            warnings.append(f"Error procesando categorías: {e}")
            category_summary = pd.DataFrame(columns=['Categoria', 'Cantidad_Musicos', 'Importe_Individual'])

        worksheet = writer.book.add_worksheet('RESUMEN_GENERAL')
        writer.sheets['RESUMEN_GENERAL'] = worksheet

        row = 0

        title_format = writer.book.add_format({
            'bold': True,
            'font_size': 16,
            'align': 'center',
            'fg_color': '#1f4e79',
            'font_color': 'white'
        })
        worksheet.merge_range(row, 0, row, 5, 'RESUMEN GENERAL - SISTEMA DE COBRO MUSICAL', title_format)
        row += 3

        worksheet.write(row, 0, 'MÉTRICAS PRINCIPALES', header_format)
        row += 1
        worksheet.write(row, 0, 'Total Presupuesto:')
        worksheet.write(row, 1, total_budget, money_format)
        row += 1
        worksheet.write(row, 0, 'Total Distribuido:')
        worksheet.write(row, 1, total_distributed, money_format)
        row += 1
        worksheet.write(row, 0, 'Diferencia:')
        worksheet.write(row, 1, total_budget - total_distributed, money_format)
        row += 1
        worksheet.write(row, 0, 'Músicos Pagados:')
        worksheet.write(row, 1, total_musicians_paid)
        row += 1
        worksheet.write(row, 0, 'Pago Promedio:')
        worksheet.write(row, 1, avg_payment, money_format)
        row += 3

        worksheet.write(row, 0, 'PRESUPUESTO VS DISTRIBUIDO POR ACTO', header_format)
        row += 1

        headers = ['Acto', 'A Repartir', 'Total Repartido', 'Diferencia']
        for col, header in enumerate(headers):
            worksheet.write(row, col, header, header_format)
        row += 1

        for _, event_row in budget_summary.iterrows():
            try:
                worksheet.write(row, 0, str(event_row['ACTES']))
                worksheet.write(row, 1, float(event_row['A REPARTIR']), money_format)
                worksheet.write(row, 2, float(event_row['Distribuido_Real']), money_format)
                worksheet.write(row, 3, float(event_row['Diferencia']), money_format)
                row += 1
            except Exception as e:
                warnings.append(f"Error escribiendo fila presupuesto: {e}")
                continue

        row += 2

        if not category_summary.empty:
            worksheet.write(row, 0, 'RESUMEN POR CATEGORÍA', header_format)
            row += 1

            cat_headers = ['Categoría', 'Cantidad Músicos', 'Total Ganado']
            for col, header in enumerate(cat_headers):
                worksheet.write(row, col, header, header_format)
            row += 1

            for _, cat_row in category_summary.iterrows():
                try:
                    worksheet.write(row, 0, str(cat_row['Categoria']))
                    worksheet.write(row, 1, int(cat_row['Cantidad_Musicos']))
                    worksheet.write(row, 2, float(cat_row['Importe_Individual']), money_format)
                    row += 1
                except Exception as e:
                    warnings.append(f"Error escribiendo fila categoría: {e}")
                    continue

        worksheet.set_column(0, 0, 40)
        worksheet.set_column(1, 4, 15)

    except Exception as e:
        raise e


def create_simple_excel_export(results):
    """Crea un Excel básico sin formato avanzado (respaldo)."""
    buffer = BytesIO()

    with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
        results['musician_summary'].to_excel(writer, sheet_name='Resumen_Musicos', index=False)
        results['payment_pivot'].to_excel(writer, sheet_name='Pagos_por_Acto')
        results['budget_comparison'].to_excel(writer, sheet_name='Comparacion_Presupuesto', index=False)
        results['musicians_by_category'].to_excel(writer, sheet_name='Musicos_por_Categoria', index=False)
        results['attendees_detail'].to_excel(writer, sheet_name='Detalle_Asistencia', index=False)

    buffer.seek(0)
    return buffer
