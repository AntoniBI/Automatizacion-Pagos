import math


def calcular_ponderaciones_automaticas(
    df_asistencia,
    df_ponderaciones,
    eventos,
    w_C=0.700,
    w_D=0.600,
    w_E=0.500,
    categoria_col="Categoria",
    decimales=4,
):
    """
    Calcula automáticamente la ponderación A por evento, de forma que
    Total Repartido == Neto Para Músicos (diferencia = 0), nunca por debajo de 0.

    Reglas:
    - C, D, E se fijan a valores constantes (default 0.700 / 0.600 / 0.500).
    - B se mantiene con su valor actual en df_ponderaciones.
    - A se despeja desde:  Σ (n_cat · w_cat) = N_total
        => w_A = (N_total - n_B·w_B - n_C·w_C - n_D·w_D - n_E·w_E) / n_A
    - El resultado se trunca hacia abajo a `decimales` decimales para
      garantizar que la diferencia (Neto - Total Repartido) sea ≥ 0.
    - Se saltan actos con todas sus ponderaciones a 0 (oficiales).
    - Se saltan actos sin asistentes o sin asistentes de categoría A.

    Parámetros:
    - df_asistencia: DataFrame con columna `categoria_col` y una columna 1/0 por evento.
    - df_ponderaciones: DataFrame con ACTES como índice y columnas A,B,C,D,E.
    - eventos: lista de nombres de eventos a recalcular.

    Retorna:
    - dict {evento: {...}} con claves:
        * skipped: bool
        * reason: str (si skipped=True)
        * A_anterior, A_nuevo, B, C, D, E: floats
        * A_exacto: float (sin truncar)
        * n_A, n_B, n_C, n_D, n_E, N_total: int
    """
    resultados = {}
    categorias = ['A', 'B', 'C', 'D', 'E']
    factor = 10 ** decimales

    for evento in eventos:
        # 1) Acto oficial -> saltar
        if evento in df_ponderaciones.index:
            current_row = df_ponderaciones.loc[evento]
            # Si el acto aparece repetido en la configuración, .loc devuelve un
            # DataFrame; nos quedamos con la primera fila para no romper.
            if getattr(current_row, "ndim", 1) > 1:
                current_row = current_row.iloc[0]
            if all(float(current_row.get(c, 0) or 0) == 0 for c in categorias):
                resultados[evento] = {
                    "skipped": True,
                    "reason": "Acto oficial (todas las ponderaciones a 0)",
                }
                continue
        else:
            resultados[evento] = {
                "skipped": True,
                "reason": "Evento no encontrado en ponderaciones",
            }
            continue

        # 2) Asistencia
        if evento not in df_asistencia.columns:
            resultados[evento] = {
                "skipped": True,
                "reason": "Evento no encontrado en asistencia",
            }
            continue

        attendees = df_asistencia[df_asistencia[evento] == 1]
        if len(attendees) == 0:
            resultados[evento] = {
                "skipped": True,
                "reason": "Sin asistentes",
            }
            continue

        cat_counts = attendees[categoria_col].value_counts().to_dict()
        n_A = int(cat_counts.get('A', 0))
        n_B = int(cat_counts.get('B', 0))
        n_C = int(cat_counts.get('C', 0))
        n_D = int(cat_counts.get('D', 0))
        n_E = int(cat_counts.get('E', 0))
        n_ABCDE = n_A + n_B + n_C + n_D + n_E
        # IMPORTANT: total_assistentes incluye TODOS los asistentes (también los que
        # no son ABCDE), porque la fórmula de reparto divide entre len(asistentes)
        # pero solo paga a ABCDE. Si N_total no incluyera a esos, A no compensaría
        # el "hueco" y la diferencia se quedaría muy lejos de 0.
        N_total = len(attendees)

        if n_A == 0:
            resultados[evento] = {
                "skipped": True,
                "reason": "No hay asistentes de categoría A; no se puede recalcular",
            }
            continue

        # 3) Mantener B actual
        w_B = float(current_row['B'])

        # 4) Despejar A
        w_A_exacto = (
            N_total - n_B * w_B - n_C * w_C - n_D * w_D - n_E * w_E
        ) / n_A
        # Truncar hacia abajo para asegurar diff >= 0
        w_A_truncado = math.floor(w_A_exacto * factor) / factor

        resultados[evento] = {
            "skipped": False,
            "A_anterior": float(current_row['A']),
            "A_nuevo": w_A_truncado,
            "A_exacto": w_A_exacto,
            "B": w_B,
            "C": w_C,
            "D": w_D,
            "E": w_E,
            "n_A": n_A, "n_B": n_B, "n_C": n_C, "n_D": n_D, "n_E": n_E,
            "N_total": N_total,
        }

    return resultados


def calcular_presupuestos_iguales(
    df_asistencia,
    df_ponderaciones,
    eventos,
    categorias,
    presupuesto_total_max,
    categoria_col="Categoria"
):
    """
    Calcula los presupuestos por evento para que el valor unitario ponderado sea igual en todos,
    respetando un presupuesto total máximo.

    Parámetros:
    - df_asistencia: DataFrame con asistencia (1/0) y columna 'Categoria'
    - df_ponderaciones: DataFrame con eventos como índice y categorías como columnas
    - eventos: lista de nombres de eventos (columnas en df_asistencia)
    - categorias: lista de nombres de categorías (ej: ['A','B','C','D','E'])
    - presupuesto_total_max: presupuesto total máximo a repartir (ej: 1800)
    - categoria_col: nombre de la columna con la categoría en df_asistencia

    Retorna:
    - dict: {evento: presupuesto_calculado}
    - float: valor unitario común
    """
    # Asegurar que ponderaciones y categorías coincidan
    df_ponderaciones = df_ponderaciones[categorias].copy()

    # Ignorar los actos que no existen en las dos hojas: si se colaran, su masa
    # sería 0 y el reparto les asignaría un presupuesto de 0 €.
    eventos = [e for e in eventos
               if e in df_asistencia.columns and e in df_ponderaciones.index]
    if not eventos:
        raise ValueError(
            "Ninguno de los actos seleccionados existe a la vez en Asistencia y "
            "en Configuración de Precios."
        )

    # Calcular la "masa ponderada" de cada evento
    masas = {}
    for evento in eventos:
        masa = 0.0
        for _, row in df_asistencia.iterrows():
            if row[evento] == 1:  # si asistió
                cat = row[categoria_col]
                if cat in categorias:
                    masa += df_ponderaciones.loc[evento, cat]
        masas[evento] = masa

    # Calcular factor común
    masa_total = sum(masas.values())
    if masa_total == 0:
        raise ValueError("No hay asistencia en ningún evento. Masa total = 0.")

    valor_unitario = presupuesto_total_max / masa_total

    # Calcular presupuestos finales
    presupuestos = {evento: valor_unitario * masas[evento] for evento in eventos}

    return presupuestos, valor_unitario