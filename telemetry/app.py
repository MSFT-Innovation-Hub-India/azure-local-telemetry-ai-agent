import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import json
import logging
import threading
import time
import uuid
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
import httpx
import psycopg
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from telemetry import datastore, monitor
from telemetry.knowledge import DependencyError, Knowledge, ROOT, complete, load_models, seed_documents
from telemetry.rules import FIELDS, summarize
from telemetry.store import connect, detect_tick


LOG = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


@asynccontextmanager
async def lifespan(app):
    passages, digest = seed_documents()
    app.state.passages = passages
    app.state.models = load_models()
    app.state.knowledge = Knowledge()
    app.state.collection = None
    app.state.index_error = "SOP index is initializing"
    app.state.detector_error = "Detector is initializing"
    app.state.last_tick = None
    app.state.model_lock = threading.Lock()
    stop = threading.Event()

    def detector():
        while not stop.is_set():
            try:
                detect_tick()
                app.state.last_tick = datetime.now(timezone.utc)
                app.state.detector_error = None
            except psycopg.Error as exc:
                app.state.detector_error = f"Database evaluation failed ({type(exc).__name__})"
                LOG.exception("Deterministic alert evaluation failed")
            stop.wait(5)

    def indexer():
        while not stop.is_set():
            try:
                app.state.collection = app.state.knowledge.index(passages, digest)
                app.state.index_error = None
                LOG.info("Indexed %d SOP passages into %s", len(passages), app.state.collection)
                return
            except (DependencyError, httpx.HTTPError, psycopg.Error, KeyError) as exc:
                app.state.index_error = f"SOP indexing failed ({type(exc).__name__}); retrying in 60 seconds"
                LOG.exception("SOP indexing failed; deterministic alerts remain independent")
                stop.wait(60)

    threads = [threading.Thread(target=target, daemon=True) for target in (detector, indexer)]
    for thread in threads:
        thread.start()
    yield
    stop.set()
    for thread in threads:
        await asyncio.to_thread(thread.join, 2)


app = FastAPI(title="Azure Local equipment telemetry", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


@app.middleware("http")
async def same_origin(request: Request, call_next):
    origin = request.headers.get("origin")
    if request.method not in ("GET", "HEAD", "OPTIONS") and origin:
        if urlparse(origin).netloc != request.url.netloc:
            return JSONResponse(status_code=403, content={"detail": "Cross-origin mutation is not allowed."})
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


@app.exception_handler(psycopg.Error)
async def database_failure(request, exc):
    LOG.error("Database request failed: %s", type(exc).__name__, exc_info=exc)
    return JSONResponse(status_code=503, content={"detail": "Telemetry database request failed. Check application logs."})


@app.get("/")
def home():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/healthz")
def health():
    return {"status": "ok"}


@app.get("/readyz")
def ready():
    last_tick = app.state.last_tick
    if not last_tick or (datetime.now(timezone.utc) - last_tick).total_seconds() > 25:
        raise HTTPException(503, "Alert detector has not completed a recent database evaluation.")
    return {"status": "ok"}


@app.get("/api/overview")
def overview():
    with connect() as conn:
        now = conn.execute("SELECT clock_timestamp() AS now").fetchone()["now"]
        rows = conn.execute(
            "SELECT equipment_id,measured_at,quality,operating_state," + ",".join(FIELDS) + " FROM telemetry.latest ORDER BY equipment_id",
        ).fetchall()
        alerts = conn.execute(
            """SELECT * FROM analysis.alerts ORDER BY (resolved_at IS NULL) DESC, opened_at DESC LIMIT 100""",
        ).fetchall()
        documents = conn.execute(
            """SELECT d.document_id,d.revision,d.title,d.sha256 FROM analysis.sop_documents d
               JOIN analysis.sop_active a USING (document_id,revision) ORDER BY d.document_id""",
        ).fetchall()
        index = conn.execute("SELECT * FROM analysis.index_status WHERE singleton").fetchone()
    return {
        "server_time": now, "equipment": rows, "alerts": alerts, "documents": documents,
        "models": [{"id": m["id"], "label": m["label"]} for m in app.state.models.values()],
        "detector": {"last_tick": app.state.last_tick, "error": app.state.detector_error},
        "index": {"ready": app.state.collection is not None, "error": app.state.index_error, "details": index},
        "diagnosis_busy": app.state.model_lock.locked(),
    }


@app.get("/api/trends")
def trends(seconds: int = Query(default=600, ge=60, le=1800)):
    fields = ",".join(f"avg({field}) AS {field}" for field in FIELDS)
    with connect() as conn:
        return conn.execute(
            f"""SELECT equipment_id,time_bucket('5 seconds',measured_at) AS measured_at,{fields}
                FROM telemetry.samples WHERE measured_at > now() - %s * INTERVAL '1 second'
                GROUP BY equipment_id,time_bucket('5 seconds',measured_at)
                ORDER BY measured_at""", (seconds,),
        ).fetchall()


@app.get("/api/rules/monitor")
def rules_monitor(minutes: int = Query(default=10, ge=1, le=30)):
    return monitor.monitor(minutes)


@app.get("/api/data/summary")
def data_summary():
    return datastore.summary()


@app.get("/api/data/recent")
def data_recent(equipment_id: str = Query(min_length=1, max_length=40), limit: int = Query(default=20, ge=1, le=100)):
    rows = datastore.recent(equipment_id, limit)
    if rows is None:
        raise HTTPException(404, "Equipment not found")
    return rows


@app.get("/api/documents/{document_id}")
def document(document_id: str, revision: str = "1.0"):
    with connect() as conn:
        row = conn.execute(
            "SELECT content FROM analysis.sop_documents WHERE document_id=%s AND revision=%s",
            (document_id, revision),
        ).fetchone()
    if not row:
        raise HTTPException(404, "SOP revision not found")
    return PlainTextResponse(row["content"], media_type="text/markdown")


@app.get("/api/alerts/{alert_id}")
def alert_detail(alert_id: uuid.UUID):
    with connect() as conn:
        alert = conn.execute("SELECT * FROM analysis.alerts WHERE id=%s", (alert_id,)).fetchone()
        if not alert:
            raise HTTPException(404, "Alert not found")
        events = conn.execute(
            "SELECT event_type,created_at,detail FROM analysis.alert_events WHERE alert_id=%s ORDER BY id", (alert_id,),
        ).fetchall()
        diagnoses = conn.execute(
            "SELECT * FROM analysis.diagnoses WHERE alert_id=%s ORDER BY created_at DESC LIMIT 20", (alert_id,),
        ).fetchall()
    return {"alert": alert, "events": events, "diagnoses": diagnoses}


class Acknowledgement(BaseModel):
    note: str = Field(default="", max_length=500)


@app.post("/api/alerts/{alert_id}/acknowledge")
def acknowledge(alert_id: uuid.UUID, request: Acknowledgement):
    with connect() as conn:
        row = conn.execute("SELECT * FROM analysis.alerts WHERE id=%s FOR UPDATE", (alert_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Alert not found")
        if row["resolved_at"]:
            raise HTTPException(409, "Resolved alerts cannot be acknowledged.")
        if not row["acknowledged_at"]:
            conn.execute(
                "UPDATE analysis.alerts SET acknowledged_at=now(),acknowledgement_note=%s WHERE id=%s",
                (request.note.strip(), alert_id),
            )
            conn.execute(
                "INSERT INTO analysis.alert_events (alert_id,event_type,detail) VALUES (%s,'acknowledged',%s)",
                (alert_id, request.note.strip() or "Reviewed by demo operator; not a clearance"),
            )
    return {"status": "acknowledged"}


class DiagnosisRequest(BaseModel):
    model: str = Field(min_length=1, max_length=60)


@app.post("/api/alerts/{alert_id}/diagnose")
def diagnose(alert_id: uuid.UUID, request: DiagnosisRequest):
    model = app.state.models.get(request.model)
    if model is None:
        raise HTTPException(422, "Choose one of the configured models.")
    if app.state.collection is None:
        raise HTTPException(503, app.state.index_error or "SOP index is unavailable")
    if not app.state.model_lock.acquire(blocking=False):
        raise HTTPException(409, "A diagnosis is already running. Retry after it completes.")
    try:
        with connect() as conn:
            alert = conn.execute("SELECT * FROM analysis.alerts WHERE id=%s", (alert_id,)).fetchone()
            if not alert:
                raise HTTPException(404, "Alert not found")
            now = conn.execute("SELECT clock_timestamp() AS now").fetchone()["now"]
            rows = conn.execute(
                "SELECT * FROM telemetry.samples WHERE equipment_id=%s AND measured_at > %s - INTERVAL '90 seconds' ORDER BY measured_at",
                (alert["equipment_id"], now),
            ).fetchall()
        evidence = {
            "equipment_id": alert["equipment_id"], "rule_id": alert["rule_id"],
            "rule_revision": alert["rule_revision"], "severity": alert["severity"],
            "opened_at": str(alert["opened_at"]), "resolved_at": str(alert["resolved_at"]) if alert["resolved_at"] else None,
            "possible_impact": alert["impact"], "trigger_observations": alert["evidence"],
            "current_observations": summarize(rows, now),
            "related_parameters_to_validate": alert["related_parameters"],
            "not_measured_requires_operator_validation": alert["missing_evidence"],
        }
        anchor = next(
            (p for p in app.state.passages if p["document_id"] == alert["source_document"]
             and p["revision"] == alert["source_revision"] and p["section"] == alert["source_section"]), None,
        )
        if anchor is None:
            raise DependencyError("The exact SOP revision supporting this alert is not available in the active package.")
        retrieved = app.state.knowledge.retrieve(
            app.state.collection, alert["title"] + " " + " ".join(alert["related_parameters"]),
        )
        sources = [anchor]
        for passage in retrieved:
            if not any((p["document_id"], p["section"]) == (passage["document_id"], passage["section"]) for p in sources):
                sources.append(passage)
            if len(sources) == 3:
                break
        sources = [dict(p, citation=f"S{i}") for i, p in enumerate(sources, 1)]
        started = time.monotonic()
        text, usage = complete(model, evidence, sources)
        elapsed = round(time.monotonic() - started, 2)
        identifier = uuid.uuid4()
        with connect() as conn:
            conn.execute(
                """INSERT INTO analysis.diagnoses (id,alert_id,model_id,result,evidence,sources,usage,elapsed_seconds)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                (identifier, alert_id, model["id"], text, Jsonb(evidence), Jsonb(sources), Jsonb(usage) if usage else None, elapsed),
            )
        return {"id": identifier, "model_id": model["id"], "result": text, "evidence": evidence,
                "sources": sources, "usage": usage, "elapsed_seconds": elapsed}
    except (DependencyError, httpx.HTTPError) as exc:
        LOG.exception("SOP-grounded diagnosis failed")
        raise HTTPException(503, "Diagnosis failed: " + str(exc)) from exc
    finally:
        app.state.model_lock.release()
