from collections.abc import Sequence
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "guardiao.db"

EVENT_TYPES = ("possible_intrusion", "sensor_change", "system_status")
EVENT_STATUSES = ("needs_review", "confirmed", "false_alarm", "info")

MAX_LIMIT = 200
DEFAULT_LIMIT = 50
MAX_WINDOW_HOURS = 24 * 30


def connect_db() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_db() -> None:
    with connect_db() as connection:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                detail TEXT,
                timestamp TEXT NOT NULL,
                vibration_detected INTEGER NOT NULL,
                hand_detected INTEGER NOT NULL,
                status TEXT NOT NULL
            )
            """
        )

        colunas = {
            linha["name"]
            for linha in connection.execute("PRAGMA table_info(events)").fetchall()
        }
        if "detail" not in colunas:
            connection.execute("ALTER TABLE events ADD COLUMN detail TEXT")

        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_device_id_id ON events(device_id, id DESC)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type)"
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="Guardião Elétrico API",
    description=(
        "API do Guardião Elétrico. Registra o log de sensores (vibração e mão "
        "detectada) e as possíveis invasões, para consumo por um app de celular."
    ),
    version="0.2.0",
    lifespan=lifespan,
)


class EventIn(BaseModel):
    device_id: str = Field(min_length=1, max_length=80)
    event_type: str = Field(default="possible_intrusion")
    detail: str | None = Field(default=None, max_length=60)
    timestamp: datetime | None = None
    vibration_detected: bool
    hand_detected: bool
    status: str = Field(default="needs_review")

    def validar(self) -> None:
        if self.event_type not in EVENT_TYPES:
            raise ValueError(
                f"event_type invalido: {self.event_type!r}; use um de {list(EVENT_TYPES)}"
            )
        if self.status not in EVENT_STATUSES:
            raise ValueError(
                f"status invalido: {self.status!r}; use um de {list(EVENT_STATUSES)}"
            )


class EventOut(BaseModel):
    id: int
    device_id: str
    event_type: str
    detail: str | None
    timestamp: datetime
    vibration_detected: bool
    hand_detected: bool
    status: str


class EventPage(BaseModel):
    items: list[EventOut]
    count: int
    has_more: bool
    next_before_id: int | None


class StatusPatch(BaseModel):
    status: str

    def validar(self) -> None:
        if self.status not in EVENT_STATUSES:
            raise ValueError(
                f"status invalido: {self.status!r}; use um de {list(EVENT_STATUSES)}"
            )


class DeviceOut(BaseModel):
    device_id: str
    last_event_at: datetime | None
    last_event_type: str | None
    vibration_detected: bool
    hand_detected: bool


class DeviceStateOut(BaseModel):
    device_id: str
    vibration_detected: bool
    hand_detected: bool
    last_event_at: datetime | None
    last_event_type: str | None
    last_event_status: str | None
    last_intrusion_at: datetime | None
    events_24h: int
    intrusions_24h: int


class SummaryOut(BaseModel):
    window_hours: int
    devices: int
    total: int
    by_type: dict[str, int]
    by_status: dict[str, int]
    first_event_at: datetime | None
    last_event_at: datetime | None
    last_intrusion_at: datetime | None


def para_datetime(texto: str) -> datetime:
    valor = datetime.fromisoformat(texto)
    if valor.tzinfo is None:
        valor = valor.replace(tzinfo=timezone.utc)
    return valor


def normalizar(valor: datetime) -> datetime:
    if valor.tzinfo is None:
        return valor.replace(tzinfo=timezone.utc)
    return valor


def linha_para_evento(row: sqlite3.Row) -> EventOut:
    return EventOut(
        id=row["id"],
        device_id=row["device_id"],
        event_type=row["event_type"],
        detail=row["detail"],
        timestamp=para_datetime(row["timestamp"]),
        vibration_detected=bool(row["vibration_detected"]),
        hand_detected=bool(row["hand_detected"]),
        status=row["status"],
    )


def montar_filtros(
    device_id: str | None,
    event_type: Sequence[str] | None,
    status: Sequence[str] | None,
    since: datetime | None,
    until: datetime | None,
    before_id: int | None,
) -> tuple[str, list]:
    condicoes: list[str] = []
    parametros: list = []

    if device_id:
        condicoes.append("device_id = ?")
        parametros.append(device_id)
    if event_type:
        condicoes.append(f"event_type IN ({','.join('?' * len(event_type))})")
        parametros.extend(event_type)
    if status:
        condicoes.append(f"status IN ({','.join('?' * len(status))})")
        parametros.extend(status)
    if since is not None:
        condicoes.append("timestamp >= ?")
        parametros.append(normalizar(since).isoformat())
    if until is not None:
        condicoes.append("timestamp <= ?")
        parametros.append(normalizar(until).isoformat())
    if before_id is not None:
        condicoes.append("id < ?")
        parametros.append(before_id)

    where = f" WHERE {' AND '.join(condicoes)}" if condicoes else ""
    return where, parametros


@app.get("/api/v1/health")
def health():
    return {"status": "ok", "service": "guardiao-eletrico-api", "version": "0.2.0"}


@app.post("/api/v1/events", response_model=EventOut, status_code=201)
def create_event(event: EventIn):
    try:
        event.validar()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    timestamp = normalizar(event.timestamp or datetime.now(timezone.utc))

    with connect_db() as connection:
        cursor = connection.execute(
            """
            INSERT INTO events
            (device_id, event_type, detail, timestamp, vibration_detected, hand_detected, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.device_id,
                event.event_type,
                event.detail,
                timestamp.isoformat(),
                int(event.vibration_detected),
                int(event.hand_detected),
                event.status,
            ),
        )
        event_id = cursor.lastrowid

    return EventOut(
        id=event_id,
        device_id=event.device_id,
        event_type=event.event_type,
        detail=event.detail,
        timestamp=timestamp,
        vibration_detected=event.vibration_detected,
        hand_detected=event.hand_detected,
        status=event.status,
    )


@app.get("/api/v1/events", response_model=EventPage)
def list_events(
    device_id: str | None = Query(default=None, max_length=80),
    event_type: list[str] | None = Query(default=None),
    status: list[str] | None = Query(default=None),
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    before_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
):
    invalidos = [t for t in (event_type or []) if t not in EVENT_TYPES]
    if invalidos:
        raise HTTPException(
            status_code=422,
            detail=f"event_type invalido: {invalidos}; use de {list(EVENT_TYPES)}",
        )
    invalidos = [s for s in (status or []) if s not in EVENT_STATUSES]
    if invalidos:
        raise HTTPException(
            status_code=422,
            detail=f"status invalido: {invalidos}; use de {list(EVENT_STATUSES)}",
        )

    where, parametros = montar_filtros(
        device_id, event_type, status, since, until, before_id
    )

    with connect_db() as connection:
        rows = connection.execute(
            f"SELECT * FROM events{where} ORDER BY id DESC LIMIT ?",
            (*parametros, limit + 1),
        ).fetchall()

    tem_mais = len(rows) > limit
    rows = rows[:limit]
    itens = [linha_para_evento(row) for row in rows]

    return EventPage(
        items=itens,
        count=len(itens),
        has_more=tem_mais,
        next_before_id=itens[-1].id if tem_mais and itens else None,
    )


@app.get("/api/v1/events/{event_id}", response_model=EventOut)
def get_event(event_id: int):
    with connect_db() as connection:
        row = connection.execute(
            "SELECT * FROM events WHERE id = ?", (event_id,)
        ).fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="evento nao encontrado")
    return linha_para_evento(row)


@app.patch("/api/v1/events/{event_id}", response_model=EventOut)
def update_event_status(event_id: int, patch: StatusPatch):
    try:
        patch.validar()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    with connect_db() as connection:
        cursor = connection.execute(
            "UPDATE events SET status = ? WHERE id = ?", (patch.status, event_id)
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="evento nao encontrado")
        row = connection.execute(
            "SELECT * FROM events WHERE id = ?", (event_id,)
        ).fetchone()

    return linha_para_evento(row)


@app.delete("/api/v1/events")
def delete_events(
    device_id: str = Query(min_length=1, max_length=80),
    antes_de: datetime | None = Query(default=None),
):
    where, parametros = montar_filtros(device_id, None, None, None, antes_de, None)

    with connect_db() as connection:
        cursor = connection.execute(f"DELETE FROM events{where}", parametros)

    return {"deleted": cursor.rowcount}


@app.get("/api/v1/devices", response_model=list[DeviceOut])
def list_devices():
    with connect_db() as connection:
        rows = connection.execute(
            """
            SELECT e.* FROM events e
            JOIN (
                SELECT device_id, MAX(id) AS ultimo_id
                FROM events GROUP BY device_id
            ) ult ON ult.ultimo_id = e.id
            ORDER BY e.id DESC
            """
        ).fetchall()

    return [
        DeviceOut(
            device_id=row["device_id"],
            last_event_at=para_datetime(row["timestamp"]),
            last_event_type=row["event_type"],
            vibration_detected=bool(row["vibration_detected"]),
            hand_detected=bool(row["hand_detected"]),
        )
        for row in rows
    ]


@app.get("/api/v1/devices/{device_id}/state", response_model=DeviceStateOut)
def get_device_state(device_id: str):
    limite = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()

    with connect_db() as connection:
        atual = connection.execute(
            "SELECT * FROM events WHERE device_id = ? ORDER BY id DESC LIMIT 1",
            (device_id,),
        ).fetchone()

        if atual is None:
            raise HTTPException(status_code=404, detail="dispositivo sem eventos")

        ultima_invasao = connection.execute(
            """
            SELECT timestamp FROM events
            WHERE device_id = ? AND event_type = 'possible_intrusion'
            ORDER BY id DESC LIMIT 1
            """,
            (device_id,),
        ).fetchone()

        contagem = connection.execute(
            """
            SELECT
                COUNT(*) AS total,
                COALESCE(SUM(event_type = 'possible_intrusion'), 0) AS invasoes
            FROM events WHERE device_id = ? AND timestamp >= ?
            """,
            (device_id, limite),
        ).fetchone()

    return DeviceStateOut(
        device_id=device_id,
        vibration_detected=bool(atual["vibration_detected"]),
        hand_detected=bool(atual["hand_detected"]),
        last_event_at=para_datetime(atual["timestamp"]),
        last_event_type=atual["event_type"],
        last_event_status=atual["status"],
        last_intrusion_at=(
            para_datetime(ultima_invasao["timestamp"]) if ultima_invasao else None
        ),
        events_24h=contagem["total"],
        intrusions_24h=contagem["invasoes"],
    )


@app.get("/api/v1/summary", response_model=SummaryOut)
def get_summary(hours: int = Query(default=24, ge=1, le=MAX_WINDOW_HOURS)):
    desde = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()

    with connect_db() as connection:
        agregados = connection.execute(
            """
            SELECT
                COUNT(*) AS total,
                COUNT(DISTINCT device_id) AS dispositivos,
                MIN(timestamp) AS primeiro,
                MAX(timestamp) AS ultimo
            FROM events WHERE timestamp >= ?
            """,
            (desde,),
        ).fetchone()

        por_tipo = {
            row["event_type"]: row["total"]
            for row in connection.execute(
                """
                SELECT event_type, COUNT(*) AS total FROM events
                WHERE timestamp >= ? GROUP BY event_type
                """,
                (desde,),
            ).fetchall()
        }

        por_status = {
            row["status"]: row["total"]
            for row in connection.execute(
                """
                SELECT status, COUNT(*) AS total FROM events
                WHERE timestamp >= ? GROUP BY status
                """,
                (desde,),
            ).fetchall()
        }

        ultima_invasao = connection.execute(
            """
            SELECT timestamp FROM events WHERE event_type = 'possible_intrusion'
            ORDER BY id DESC LIMIT 1
            """
        ).fetchone()

    return SummaryOut(
        window_hours=hours,
        devices=agregados["dispositivos"],
        total=agregados["total"],
        by_type=por_tipo,
        by_status=por_status,
        first_event_at=para_datetime(agregados["primeiro"]) if agregados["primeiro"] else None,
        last_event_at=para_datetime(agregados["ultimo"]) if agregados["ultimo"] else None,
        last_intrusion_at=(
            para_datetime(ultima_invasao["timestamp"]) if ultima_invasao else None
        ),
    )


@app.get("/api/v1/status")
def get_status():
    with connect_db() as connection:
        row = connection.execute(
            "SELECT timestamp, status FROM events ORDER BY id DESC LIMIT 1"
        ).fetchone()

    if row is None:
        return {
            "status": "waiting",
            "last_event_at": None,
            "last_event_status": None,
        }
    return {
        "status": "event_received",
        "last_event_at": row["timestamp"],
        "last_event_status": row["status"],
    }