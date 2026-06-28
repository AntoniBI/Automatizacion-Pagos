"""
backend/server.py — API REST (FastAPI) del Sistema de Cobro Musical.

Envuelve el motor `core.MusicianPaymentSystem` (lógica intacta) y sirve el
frontend estático en `frontend/`. El estado por usuario se guarda en sesiones en
memoria, identificadas por una cookie. Cada sesión tiene su propia instancia del
sistema (equivalente a `st.session_state.payment_system` en Streamlit).
"""

import json
import uuid
from io import BytesIO
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, Form, Request, Response, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .core import MusicianPaymentSystem
from .excel_export import create_excel_export, create_simple_excel_export
from datetime import date

from .cheques import (
    ChequeError,
    generate_calibration_pdf,
    generate_cheques_pdf,
    get_default_calibration,
    get_sample_items,
    read_cheque_amounts,
)

# Rutas del frontend (resueltas respecto a la raíz del proyecto)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = PROJECT_ROOT / "frontend"

app = FastAPI(title="Sistema de Cobro Musical")

# ----------------------------------------------------------------------
# Gestión de sesiones en memoria
# ----------------------------------------------------------------------
SESSIONS: dict[str, MusicianPaymentSystem] = {}
COOKIE_NAME = "cobro_session"


def get_or_create_session(request: Request) -> tuple[MusicianPaymentSystem, str]:
    sid = request.cookies.get(COOKIE_NAME)
    if not sid or sid not in SESSIONS:
        sid = str(uuid.uuid4())
        SESSIONS[sid] = MusicianPaymentSystem()
    return SESSIONS[sid], sid


def require_session(request: Request) -> MusicianPaymentSystem:
    sid = request.cookies.get(COOKIE_NAME)
    if not sid or sid not in SESSIONS:
        raise HTTPException(status_code=400, detail="Sesión no iniciada. Recarga la página.")
    return SESSIONS[sid]


def require_data(system: MusicianPaymentSystem) -> None:
    if system.asistencia_df is None or system.presupuesto_df is None or system.configuracion_df is None:
        raise HTTPException(status_code=409, detail="No hay archivo cargado. Sube un Excel primero.")


def drain_messages(system: MusicianPaymentSystem) -> list:
    msgs = list(system.messages)
    system.reset_messages()
    return msgs


def with_session_cookie(payload: dict, sid: str) -> JSONResponse:
    response = JSONResponse(payload)
    response.set_cookie(COOKIE_NAME, sid, httponly=True, samesite="lax")
    return response


# ----------------------------------------------------------------------
# Modelos de petición
# ----------------------------------------------------------------------
class WeightsPayload(BaseModel):
    rows: list


class AutoPondPayload(BaseModel):
    eventos: list
    decimales: int = 4


class EqualizePayload(BaseModel):
    eventos: list
    presupuesto_total: float


class DefaultBudgetPayload(BaseModel):
    eventos: list


class RetentionPayload(BaseModel):
    rows: list


class ProcessPayload(BaseModel):
    penalty_criteria: str = "manual"
    fixed_penalty_amount: float = 0
    category_penalties: dict | None = None


# ----------------------------------------------------------------------
# Serializadores (DataFrame -> JSON)
# ----------------------------------------------------------------------
def weights_to_rows(df) -> list:
    return [
        {
            "ACTES": str(r["ACTES"]),
            "A": float(r["A"]),
            "B": float(r["B"]),
            "C": float(r["C"]),
            "D": float(r["D"]),
            "E": float(r["E"]),
        }
        for _, r in df.iterrows()
    ]


def retention_to_rows(df) -> list:
    return [
        {
            "ACTES": str(r["ACTES"]),
            "BANDA_PORCENTAJE": float(r["BANDA_PORCENTAJE"]),
            "DESCRIPCION": str(r["DESCRIPCION"]),
        }
        for _, r in df.iterrows()
    ]


def df_records(df) -> list:
    # to_json serializa NaN/NaT como null de forma fiable (evita el gotcha de
    # pandas donde asignar None a una columna float lo reconvierte en NaN).
    return json.loads(df.to_json(orient="records"))


def preview_payload(system: MusicianPaymentSystem) -> dict:
    bc = system.compute_budget_comparison_preview()
    comparison = [
        {
            "Acto": str(r["ACTES"]),
            "Presupuesto": float(r["A REPARTIR"]),
            "Retencion_PCT": float(r["Banda_Retencion_PCT"]),
            "Retencion_Amount": float(r["Banda_Retencion_Amount"]),
            "Neto": float(r["Neto_Para_Musicos"]),
            "Total_Repartido": float(r["Total Repartido"]),
            "Diferencia": float(r["Diferencia_Neto"]),
        }
        for _, r in bc.iterrows()
    ]
    metrics = {
        "total_budget": float(bc["A REPARTIR"].sum()),
        "total_retention": float(bc["Banda_Retencion_Amount"].sum()),
        "total_net": float(bc["Neto_Para_Musicos"].sum()),
        "total_diff": float(bc["Diferencia_Neto"].sum()),
    }
    earnings = system.compute_earnings_by_category()
    return {"metrics": metrics, "comparison": comparison, "earnings": earnings}


# ----------------------------------------------------------------------
# Sesión / estado
# ----------------------------------------------------------------------
@app.get("/api/session")
def api_session(request: Request):
    system, sid = get_or_create_session(request)
    payload = {"loaded": system.asistencia_df is not None}
    if payload["loaded"]:
        payload["summary"] = system.get_data_summary()
    return with_session_cookie(payload, sid)


# ----------------------------------------------------------------------
# Carga de archivo
# ----------------------------------------------------------------------
@app.post("/api/upload")
async def api_upload(request: Request, file: UploadFile = File(...)):
    _, sid = get_or_create_session(request)

    contents = await file.read()
    buffer = BytesIO(contents)

    # Nueva carga: instancia limpia para descartar el estado previo
    fresh = MusicianPaymentSystem()
    ok = fresh.load_from_uploaded_file(buffer)
    messages = drain_messages(fresh)

    if ok:
        SESSIONS[sid] = fresh

    payload = {
        "ok": ok,
        "messages": messages,
        "filename": file.filename,
        "size_kb": round(len(contents) / 1024, 1),
    }
    if ok:
        payload["summary"] = fresh.get_data_summary()

    return with_session_cookie(payload, sid)


# ----------------------------------------------------------------------
# Dashboard
# ----------------------------------------------------------------------
@app.get("/api/dashboard")
def api_dashboard(request: Request):
    system = require_session(request)
    require_data(system)
    return system.dashboard_data()


# ----------------------------------------------------------------------
# Ponderaciones
# ----------------------------------------------------------------------
@app.get("/api/weights")
def api_get_weights(request: Request):
    system = require_session(request)
    require_data(system)
    return {
        "rows": weights_to_rows(system.editing_weights),
        "non_official_events": system.get_non_official_events(),
        "all_events": system.get_events_list(),
        "preview": preview_payload(system),
    }


@app.put("/api/weights")
def api_put_weights(request: Request, payload: WeightsPayload):
    system = require_session(request)
    require_data(system)
    system.set_weights(payload.rows)
    return {"rows": weights_to_rows(system.editing_weights), "preview": preview_payload(system)}


@app.post("/api/weights/save")
def api_save_weights(request: Request):
    system = require_session(request)
    require_data(system)
    system.save_weights()
    return {"ok": True}


@app.post("/api/weights/restore")
def api_restore_weights(request: Request):
    system = require_session(request)
    require_data(system)
    system.restore_weights()
    return {"rows": weights_to_rows(system.editing_weights), "preview": preview_payload(system)}


@app.post("/api/weights/auto-a")
def api_auto_a(request: Request, payload: AutoPondPayload):
    system = require_session(request)
    require_data(system)
    cambios, saltados = system.apply_auto_ponderacion(payload.eventos, payload.decimales)
    return {
        "cambios": cambios,
        "saltados": saltados,
        "decimales": payload.decimales,
        "rows": weights_to_rows(system.editing_weights),
        "preview": preview_payload(system),
    }


@app.post("/api/weights/default-budget")
def api_default_budget(request: Request, payload: DefaultBudgetPayload):
    system = require_session(request)
    require_data(system)
    return {"default_budget": system.get_default_budget_sum(payload.eventos)}


@app.post("/api/weights/equalize")
def api_equalize(request: Request, payload: EqualizePayload):
    system = require_session(request)
    require_data(system)
    if not payload.eventos:
        raise HTTPException(status_code=400, detail="Selecciona al menos un acto.")
    try:
        changes_log, valor_unitario = system.apply_equalize_budgets(payload.eventos, payload.presupuesto_total)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error al calcular: {str(e)}")
    return {
        "changes_log": changes_log,
        "valor_unitario": valor_unitario,
        "preview": preview_payload(system),
    }


# ----------------------------------------------------------------------
# Retención de banda
# ----------------------------------------------------------------------
@app.get("/api/retention")
def api_get_retention(request: Request):
    system = require_session(request)
    require_data(system)
    return {
        "rows": retention_to_rows(system.band_retention_config),
        "impact": system.compute_retention_impact(),
    }


@app.put("/api/retention")
def api_put_retention(request: Request, payload: RetentionPayload):
    system = require_session(request)
    require_data(system)
    system.set_band_retention(payload.rows)
    return {
        "rows": retention_to_rows(system.band_retention_config),
        "impact": system.compute_retention_impact(),
    }


@app.post("/api/retention/save")
def api_save_retention(request: Request):
    system = require_session(request)
    require_data(system)
    system.save_band_retention()
    return {"ok": True}


@app.post("/api/retention/reset")
def api_reset_retention(request: Request):
    system = require_session(request)
    require_data(system)
    system.reset_band_retention()
    return {
        "rows": retention_to_rows(system.band_retention_config),
        "impact": system.compute_retention_impact(),
    }


@app.post("/api/retention/template")
def api_template_retention(request: Request):
    system = require_session(request)
    require_data(system)
    system.apply_band_retention_template()
    return {
        "rows": retention_to_rows(system.band_retention_config),
        "impact": system.compute_retention_impact(),
    }


# ----------------------------------------------------------------------
# Análisis por actos
# ----------------------------------------------------------------------
@app.get("/api/events")
def api_events(request: Request):
    system = require_session(request)
    require_data(system)
    return {"events": system.get_events_list()}


@app.get("/api/events/analysis")
def api_event_analysis(request: Request, event: str):
    system = require_session(request)
    require_data(system)
    return system.event_analysis(event)


# ----------------------------------------------------------------------
# Procesar y descargar
# ----------------------------------------------------------------------
@app.post("/api/process")
def api_process(request: Request, payload: ProcessPayload):
    system = require_session(request)
    require_data(system)
    system.reset_messages()

    results = system.process_payments(
        payload.penalty_criteria,
        payload.fixed_penalty_amount,
        payload.category_penalties,
    )
    messages = drain_messages(system)

    if results is None:
        return {"ok": False, "messages": messages}

    # Guardar resultados en la sesión para la descarga posterior
    system.last_results = results

    musician_summary = results["musician_summary"]
    summary = {
        "musicians_paid": int(len(musician_summary)),
        "total_band_retention": float(results.get("total_band_retention", 0)),
    }
    if "Importe_Final" in musician_summary.columns:
        summary["total_final"] = float(musician_summary["Importe_Final"].sum())
        summary["avg_payment"] = float(musician_summary["Importe_Final"].mean())
        summary["has_penalties"] = True
        summary["total_penalties"] = float(musician_summary["Penalizacion_Total"].sum())
        penalized = musician_summary[musician_summary["Penalizacion_Total"] > 0]
        summary["musicians_penalized"] = int(len(penalized))
        summary["avg_penalty"] = float(penalized["Penalizacion_Total"].mean()) if len(penalized) else 0.0
    else:
        summary["total_distributed"] = float(musician_summary["Importe_Individual"].sum())
        summary["avg_payment"] = float(musician_summary["Importe_Individual"].mean())
        summary["has_penalties"] = False

    # Detalle de retención por acto (pestaña Retención Banda)
    retention_detail = []
    detail = results.get("attendees_detail")
    if detail is not None and not detail.empty:
        rd = detail[["Acto", "A REPARTIR", "BANDA_RETENCION_PCT", "BANDA_RETENCION_AMOUNT", "A_REPARTIR_NETO"]].drop_duplicates("Acto")
        retention_detail = [
            {
                "Acto": str(r["Acto"]),
                "Presupuesto_Original": float(r["A REPARTIR"]),
                "Retencion_PCT": float(r["BANDA_RETENCION_PCT"]),
                "Retencion_Amount": float(r["BANDA_RETENCION_AMOUNT"]),
                "Neto": float(r["A_REPARTIR_NETO"]),
            }
            for _, r in rd.iterrows()
        ]

    return {
        "ok": True,
        "messages": messages,
        "summary": summary,
        "tables": {
            "musician_summary": df_records(musician_summary),
            "budget_comparison": df_records(results["budget_comparison"]),
            "musicians_by_category": df_records(results["musicians_by_category"]),
            "retention_detail": retention_detail,
        },
    }


@app.get("/api/export/{kind}")
def api_export(request: Request, kind: str):
    system = require_session(request)
    require_data(system)
    results = system.last_results
    if results is None:
        raise HTTPException(status_code=409, detail="Procesa los datos antes de descargar.")

    if kind == "full":
        buffer = create_excel_export(results, system, warnings=[])
        filename = "cobro_musical_resultados.xlsx"
    elif kind == "basic":
        buffer = create_simple_excel_export(results)
        filename = "cobro_musical_basico.xlsx"
    else:
        raise HTTPException(status_code=404, detail="Tipo de export desconocido")

    return StreamingResponse(
        BytesIO(buffer.getvalue()),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ----------------------------------------------------------------------
# Cheques (PDF) — módulo independiente: lee un Excel ya editado y genera el PDF
# ----------------------------------------------------------------------
@app.post("/api/cheques/preview")
async def api_cheques_preview(file: UploadFile = File(...)):
    contents = await file.read()
    try:
        items, info = read_cheque_amounts(contents)
    except ChequeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {
        "items": items,
        "info": info,
        "total": sum(i["importe"] for i in items),
        "count": len(items),
    }


def _parse_calibration(raw: str | None):
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return None


@app.post("/api/cheques/pdf")
async def api_cheques_pdf(
    file: UploadFile = File(...),
    fecha: str = Form(...),
    serie_inicial: str | None = Form(None),
    calibration: str | None = Form(None),
    incluir_dorso: bool = Form(False),
):
    contents = await file.read()
    try:
        items, _ = read_cheque_amounts(contents)
        pdf = generate_cheques_pdf(
            items, fecha, serie_inicial or None, _parse_calibration(calibration),
            incluir_dorso=incluir_dorso,
        )
    except ChequeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return StreamingResponse(
        BytesIO(pdf),
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="cheques.pdf"'},
    )


@app.get("/api/cheques/calibration-defaults")
def api_cheques_calibration_defaults():
    return get_default_calibration()


@app.post("/api/cheques/ejemplo")
async def api_cheques_ejemplo(request: Request):
    """PDF de cheques con datos simulados, para probar la calibración."""
    try:
        data = await request.json()
    except (ValueError, TypeError):
        data = {}
    fecha = data.get("fecha") or date.today().isoformat()
    try:
        pdf = generate_cheques_pdf(
            get_sample_items(),
            fecha,
            data.get("serie_inicial") or None,
            data.get("calibration"),
            incluir_dorso=bool(data.get("incluir_dorso")),
        )
    except ChequeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return StreamingResponse(
        BytesIO(pdf),
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="cheques_ejemplo.pdf"'},
    )


@app.post("/api/cheques/calibracion")
async def api_cheques_calibracion(request: Request):
    raw = await request.body()
    calibration = None
    if raw:
        try:
            calibration = json.loads(raw)
        except (ValueError, TypeError):
            calibration = None
    incluir_dorso = bool(calibration.get("incluir_dorso")) if calibration else False
    pdf = generate_calibration_pdf(calibration, incluir_dorso=incluir_dorso)
    return StreamingResponse(
        BytesIO(pdf),
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="cheques_calibracion.pdf"'},
    )


# ----------------------------------------------------------------------
# Estáticos / SPA
# ----------------------------------------------------------------------
@app.get("/")
def index():
    return FileResponse(FRONTEND_DIR / "index.html")


app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
