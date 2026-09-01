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


def calcular_ajuste_conjunto(
    df_asistencia,
    df_ponderaciones,
    eventos,
    presupuesto_total,
    factor_neto=None,
    w_C=0.700,
    w_D=0.600,
    w_E=0.500,
    categoria_col="Categoria",
    decimales=4,
):
    """Ajusta a la vez las ponderaciones y los presupuestos de varios actos.

    Encadenar "ponderación A automática" + "igualar presupuestos" deja a la
    categoría A cobrando distinto en cada acto: como A se despeja por acto para
    repartir el presupuesto entero, absorbe la diferencia de composición (un acto
    con pocos músicos A le da a cada uno una ponderación mayor). B, C, D y E sí
    coinciden porque son las mismas en todos los actos.

    Aquí se resuelven las dos cosas a la vez:

    1. Se calcula UNA ponderación base común a todos los actos seleccionados
       (C, D, E fijas; B la media ponderada por asistentes; A despejada sobre el
       conjunto para que la media de ponderaciones por asistente sea 1).
    2. Cada acto escala ese bloque completo por k = N_asistentes / masa_base, de
       forma que reparte exactamente su presupuesto (diferencia ≥ 0).
    3. El presupuesto de cada acto se fija en proporción a su masa base, que es
       justo lo que compensa el escalado.

    El resultado: (neto/N)·ponderación es idéntico en todos los actos para cada
    categoría — todos cobran lo mismo en todos los actos — sin dejar dinero sin
    repartir y manteniendo la misma proporción entre categorías.

    Parámetros:
    - factor_neto: {evento: 1 - retencion/100}; el reparto iguala el NETO, así
      que un acto con retención necesita un presupuesto bruto mayor.
    - presupuesto_total: total bruto a repartir entre los actos seleccionados.

    Retorna (resultados, saltados, resumen).
    """
    categorias = ['A', 'B', 'C', 'D', 'E']
    factor = 10 ** decimales
    factor_neto = factor_neto or {}

    validos = []
    saltados = []
    for evento in eventos:
        if evento not in df_ponderaciones.index:
            saltados.append({"Acto": evento, "Motivo": "Evento no encontrado en ponderaciones"})
            continue
        current_row = df_ponderaciones.loc[evento]
        if getattr(current_row, "ndim", 1) > 1:
            current_row = current_row.iloc[0]
        if all(float(current_row.get(c, 0) or 0) == 0 for c in categorias):
            saltados.append({"Acto": evento, "Motivo": "Acto oficial (todas las ponderaciones a 0)"})
            continue
        if evento not in df_asistencia.columns:
            saltados.append({"Acto": evento, "Motivo": "Evento no encontrado en asistencia"})
            continue

        attendees = df_asistencia[df_asistencia[evento] == 1]
        if len(attendees) == 0:
            saltados.append({"Acto": evento, "Motivo": "Sin asistentes"})
            continue

        cat_counts = attendees[categoria_col].value_counts().to_dict()
        n = {c: int(cat_counts.get(c, 0)) for c in categorias}
        if n['A'] == 0:
            saltados.append({"Acto": evento, "Motivo": "No hay asistentes de categoría A"})
            continue

        validos.append({
            "evento": evento,
            "n": n,
            # N incluye a TODOS los asistentes, igual que la fórmula de reparto,
            # que divide entre len(asistentes) aunque haya categorías fuera de A-E.
            "N": len(attendees),
            "w_B_actual": float(current_row['B']),
            "A_anterior": float(current_row['A']),
        })

    if not validos:
        raise ValueError("Ninguno de los actos seleccionados se puede ajustar.")

    # 1) Bloque base común: B media ponderada por músicos B; C, D, E fijas.
    total_nB = sum(v["n"]['B'] for v in validos)
    if total_nB:
        w_B_base = sum(v["n"]['B'] * v["w_B_actual"] for v in validos) / total_nB
    else:
        w_B_base = sum(v["w_B_actual"] for v in validos) / len(validos)

    fijas = {'B': w_B_base, 'C': w_C, 'D': w_D, 'E': w_E}
    N_pool = sum(v["N"] for v in validos)
    nA_pool = sum(v["n"]['A'] for v in validos)
    resto = sum(v["n"][c] * w for v in validos for c, w in fijas.items())
    w_A_base = (N_pool - resto) / nA_pool
    if w_A_base <= 0:
        raise ValueError(
            "La ponderación A común saldría negativa: revisa las categorías de los actos seleccionados."
        )

    base = {'A': w_A_base, **fijas}

    # 2) Escalado por acto + 3) presupuesto proporcional a la masa base
    for v in validos:
        v["masa_base"] = sum(v["n"][c] * base[c] for c in categorias)
        v["k"] = v["N"] / v["masa_base"]
        v["factor_neto"] = float(factor_neto.get(v["evento"], 1.0)) or 1.0

    denominador = sum(v["masa_base"] / v["factor_neto"] for v in validos)
    valor_unitario = presupuesto_total / denominador

    resultados = []
    for v in validos:
        # Truncar hacia abajo para que la diferencia por acto nunca sea negativa
        pesos = {c: math.floor(base[c] * v["k"] * factor) / factor for c in categorias}
        neto = valor_unitario * v["masa_base"]
        bruto = neto / v["factor_neto"]
        masa_final = sum(v["n"][c] * pesos[c] for c in categorias)
        repartido = (neto / v["N"]) * masa_final
        resultados.append({
            "Acto": v["evento"],
            "Asistentes": v["N"],
            "A anterior": v["A_anterior"],
            **{f"{c} nuevo": pesos[c] for c in categorias},
            "pesos": pesos,
            "Presupuesto nuevo": bruto,
            "Neto (€)": neto,
            "Total Repartido (€)": repartido,
            "Diff (€)": neto - repartido,
            **{f"Cobra {c}": (neto / v["N"]) * pesos[c] for c in categorias},
        })

    resumen = {
        "A_base": w_A_base,
        "B_base": w_B_base,
        "C_base": w_C,
        "D_base": w_D,
        "E_base": w_E,
        "valor_unitario": valor_unitario,
        "actos": len(validos),
        "pagos": {c: valor_unitario * base[c] for c in categorias},
    }
    return resultados, saltados, resumen
