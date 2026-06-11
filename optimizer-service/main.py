import base64
import io
import math
import uuid
import asyncio
import time
import json
import logging
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from fastapi import FastAPI, BackgroundTasks, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse, HTMLResponse
from starlette.middleware.base import BaseHTTPMiddleware
from pydantic import BaseModel, Field, field_validator

import pandas as pd
from optimizer_engine import RouteOptimizer, get_days_from_freq, get_weeks_from_monthly_freq
from config import config

# 1. Configuración de Logs Estructurados
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("smartroute")

app = FastAPI(
    title="SmartRoute AI Optimization Service",
    description="Microservicio de ruteo inteligente de alto rendimiento en Python",
    version="2.1.0"
)

# Custom Validation Exception Handler
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    logger.error(f"Fallo de validacion en la peticion a {request.url.path}: {exc.errors()}")
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors()}
    )

# 2. Restricción de CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 3. Middleware de Rate Limiting en Memoria
class SimpleRateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, limit: int = 60, window: int = 60):
        super().__init__(app)
        self.limit = limit  # Máximo de solicitudes
        self.window = window  # Ventana en segundos
        self.clients: Dict[str, List[float]] = {}

    async def dispatch(self, request: Request, call_next):
        # Omitir límites para endpoints de documentación o salud
        if request.url.path in ["/health", "/docs", "/openapi.json"]:
            return await call_next(request)
            
        client_ip = request.client.host if request.client else "unknown"
        now = time.time()
        
        # Inicializar y filtrar llamadas fuera de la ventana
        if client_ip not in self.clients:
            self.clients[client_ip] = []
        self.clients[client_ip] = [t for t in self.clients[client_ip] if now - t < self.window]
        
        if len(self.clients[client_ip]) >= self.limit:
            logger.warning(f"Límite de tasa excedido para la IP: {client_ip}")
            return JSONResponse(
                status_code=429,
                content={"detail": "Límite de peticiones excedido. Inténtalo más tarde."}
            )
            
        self.clients[client_ip].append(now)
        return await call_next(request)

app.add_middleware(SimpleRateLimitMiddleware, limit=config.RATE_LIMIT_REQUESTS, window=60)

# Almacenamiento en memoria (Base de datos efímera)
execution_store: Dict[str, Any] = {}
progress_store: Dict[str, Any] = {}
session_timestamps: Dict[str, datetime] = {}
SESSION_TTL_MINUTES = 360

def cleanup_old_sessions() -> None:
    cutoff = datetime.utcnow() - timedelta(minutes=SESSION_TTL_MINUTES)
    expired = [sid for sid, created_at in session_timestamps.items() if created_at < cutoff]
    for sid in expired:
        execution_store.pop(sid, None)
        progress_store.pop(sid, None)
        session_timestamps.pop(sid, None)

def register_session(session_id: str) -> None:
    cleanup_old_sessions()
    session_timestamps[session_id] = datetime.utcnow()

def validate_excel_payload(file_content: str) -> None:
    try:
        payload_size = len(base64.b64decode(file_content, validate=False))
    except Exception as exc:
        raise ValueError("Archivo base64 invalido") from exc
    if payload_size > config.MAX_FILE_SIZE_BYTES:
        raise ValueError(f"Archivo excede el limite de {config.MAX_FILE_SIZE_MB}MB")

def estimate_people_required(routes: List[Dict[str, Any]], rules: Dict[str, Any]) -> Dict[str, Any]:
    max_weekly_hours = max(float(rules.get("maxHorasSemanales", 42.0)), 1.0)
    total_hours = sum(float(r.get("horasTrabajadas", 0.0)) for r in routes)
    unique_route_people = len(set(r.get("rutaNombre") for r in routes if r.get("rutaNombre")))
    persons_by_hours = max(1, math.ceil(total_hours / max_weekly_hours)) if total_hours > 0 else 0
    persons_by_routes = max(1, math.ceil(unique_route_people / 6.0)) if unique_route_people > 0 else 0
    required = max(persons_by_hours, persons_by_routes)
    return {
        "personasRequeridas": required,
        "personasPorHoras": persons_by_hours,
        "personasPorRutas": persons_by_routes,
        "horasPorPersonaPromedio": (total_hours / required) if required else 0.0,
    }

# 4. Esquemas de Validación Pydantic
class RulesModel(BaseModel):
    horaInicio: str = Field(default="08:00")
    horaFin: str = Field(default="18:00")
    almuerzoInicio: str = Field(default="12:00")
    almuerzoFin: str = Field(default="13:00")
    maxHorasDiarias: float = Field(default=9.0)
    maxHorasSemanales: float = Field(default=42.0)
    permanenciaDefaultMin: int = Field(default=40)
    velocidadCaminandoKmh: float = Field(default=4.0)
    distanciaCaminableKm: float = Field(default=0.8)
    velocidadBusKmh: float = Field(default=15.0)
    base_url_osrm: str = Field(default="http://127.0.0.1:5000")
    sabadoActivo: bool = Field(default=True)
    sabadoMaxPdvs: int = Field(default=2)
    sabadoPermanenciaFija: int = Field(default=198)
    maxRelocalizacionMin: float = Field(default=120.0)
    centroPunto: List[float] = Field(default=[4.6097, -74.0817])

    @field_validator("horaInicio", "horaFin", "almuerzoInicio", "almuerzoFin")
    @classmethod
    def validate_time(cls, value: str) -> str:
        try:
            hour, minute = [int(part) for part in value.split(":")]
        except Exception as exc:
            raise ValueError("La hora debe tener formato HH:MM") from exc
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError("La hora debe estar entre 00:00 y 23:59")
        return value

    @field_validator(
        "maxHorasDiarias",
        "maxHorasSemanales",
        "permanenciaDefaultMin",
        "velocidadCaminandoKmh",
        "distanciaCaminableKm",
        "velocidadBusKmh",
        "maxRelocalizacionMin",
    )
    @classmethod
    def validate_positive(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("El valor debe ser mayor que cero")
        return value

    @field_validator("centroPunto")
    @classmethod
    def validate_center(cls, value: List[float]) -> List[float]:
        if len(value) != 2 or not (-90 <= value[0] <= 90) or not (-180 <= value[1] <= 180):
            raise ValueError("centroPunto debe ser [latitud, longitud] valido")
        return value

class ProcessRequest(BaseModel):
    fileContent: str  # Base64 del Excel
    rules: RulesModel

    @field_validator("fileContent")
    @classmethod
    def validate_file_content(cls, value: str) -> str:
        validate_excel_payload(value)
        return value

class EstimateCapacityRequest(BaseModel):
    data: List[Dict[str, Any]]
    rules: RulesModel
    groupBy: str
    frequencyPeriod: str = Field(default="week")

    @field_validator("data")
    @classmethod
    def validate_capacity_rows(cls, value: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not value:
            raise ValueError("Debes enviar al menos un PDV")
        return value

    @field_validator("groupBy")
    @classmethod
    def validate_group_by(cls, value: str) -> str:
        if value not in {"Ciudad", "Departamento"}:
            raise ValueError("groupBy debe ser Ciudad o Departamento")
        return value

    @field_validator("frequencyPeriod")
    @classmethod
    def validate_frequency_period(cls, value: str) -> str:
        if value not in {"week", "month"}:
            raise ValueError("frequencyPeriod debe ser week o month")
        return value

# 5. Función de Parsing Compartida y Refactorizada
def parse_pdvs_from_df(
    df: pd.DataFrame,
    rules: RulesModel,
    is_capacity: bool = False,
    frequency_period: str = "week",
) -> List[Dict[str, Any]]:
    # Reemplazar valores NaN con None para que sean compatibles con JSON
    df = df.where(pd.notnull(df), None)
    raw_data = df.to_dict(orient='records')
    
    pdvs = []
    for index, row in enumerate(raw_data):
        # Frecuencia de visita
        freq_raw = row.get('Frecuencia') or row.get('frecuencia')
        try:
            freq = int(freq_raw) if freq_raw is not None else 1
        except Exception:
            freq = 1
        if is_capacity and frequency_period == "month":
            freq = min(max(freq, 1), 4)
        else:
            freq = min(max(freq, 1), 6)
            
        # Coordenadas geográficas
        lat_raw = row.get('Latitud') or row.get('latitud')
        lon_raw = row.get('Longitud') or row.get('longitud')
        try:
            lat = float(lat_raw)
            lon = float(lon_raw)
            if math.isnan(lat) or math.isnan(lon) or not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
                continue
        except Exception:
            continue
            
        # Días de visita
        dias = row.get('Dias') or row.get('dias') or row.get('Días') or row.get('días')
        if not dias:
            dias = get_days_from_freq(1 if is_capacity and frequency_period == "month" else freq, index)
            
        # Tiempo de permanencia
        t_visita_raw = row.get('Tiempo de visita entero') or row.get('tiempoVisita') or row.get('Tiempo de visita')
        try:
            t_visita = int(t_visita_raw) if t_visita_raw is not None else int(rules.permanenciaDefaultMin)
        except Exception:
            t_visita = int(rules.permanenciaDefaultMin)

        pdv_obj = {
            'id': str(row.get('Llave PDV') or row.get('ID') or (f"cap-{index}" if is_capacity else f"pdv-{index}")),
            'pdv': str(row.get('PDV') or row.get('pdv') or 'Desconocido'),
            'latitud': lat,
            'longitud': lon,
            'direccion': str(row.get('direccion') or row.get('Direccion') or ''),
            'frecuencia': freq,
            'tiempoVisita': t_visita,
            'ruta': str(row.get('Ruta') or row.get('ruta') or ('Estimación' if is_capacity else 'Sin Ruta')),
            'dias': str(dias)
        }
        
        if is_capacity:
            pdv_obj['ciudad'] = str(row.get('Ciudad') or row.get('ciudad') or '')
            pdv_obj['departamento'] = str(row.get('Departamento') or row.get('departamento') or '')
            if frequency_period == "month":
                semanas = row.get('Semanas') or row.get('semanas') or row.get('Semana Mes') or row.get('semanaMes')
                pdv_obj['semanasMes'] = str(semanas or get_weeks_from_monthly_freq(freq, index))
            
        pdvs.append(pdv_obj)
        
    return pdvs

# 6. Procesamiento Asíncrono en Paralelo (Hilos)
async def run_process_task(session_id: str, file_content_base64: str, rules_model: RulesModel):
    try:
        progress_store[session_id] = {"progress": 0, "status": "Iniciando lectura de datos..."}
        logger.info(f"Sesión {session_id}: Decodificando Excel base64")
        
        excel_bytes = base64.b64decode(file_content_base64)
        df = pd.read_excel(io.BytesIO(excel_bytes))
        
        rules = rules_model.model_dump()
        pdvs = parse_pdvs_from_df(df, rules_model, is_capacity=False)
        logger.info(f"Sesión {session_id}: Parseados {len(pdvs)} PDVs correctamente")

        if len(pdvs) == 0:
            progress_store[session_id] = {"progress": 0, "status": "Error: No se encontraron PDVs válidos."}
            return

        optimizer = RouteOptimizer(rules)
        rutas_unicas = list(set([p['ruta'] for p in pdvs]))
        
        progress_store[session_id] = {
            "progress": 5,
            "status": f"Optimizando {len(rutas_unicas)} rutas de forma paralela..."
        }
        
        # Procesar cada ruta en paralelo usando asyncio.gather
        async def process_single_route(ruta_nombre):
            logger.info(f"Sesión {session_id}: Optimizando ruta de forma concurrente: {ruta_nombre}")
            pdvs_de_ruta = [p for p in pdvs if p['ruta'] == ruta_nombre]
            
            res = await optimizer.process_route(ruta_nombre, pdvs_de_ruta)
            
            # Incrementar progreso parcial
            current = progress_store[session_id]["progress"]
            progress_store[session_id]["progress"] = min(95, current + max(1, int(90 / len(rutas_unicas))))
            progress_store[session_id]["status"] = f"Ruta optimizada: {ruta_nombre}"
            return res

        tasks = [process_single_route(name) for name in rutas_unicas]
        engine_results = await asyncio.gather(*tasks)
        
        all_daily_routes = []
        all_omitted = []
        
        for engine_result in engine_results:
            all_daily_routes.extend(engine_result['dailyRoutes'])
            all_omitted.extend(engine_result['omitted'])

        total_km = sum([r['kmTotales'] for r in all_daily_routes])
        total_horas = sum([r['horasTrabajadas'] for r in all_daily_routes])
        cobertura = ((len(pdvs) - len(all_omitted)) / len(pdvs)) * 100.0 if len(pdvs) > 0 else 0.0

        summary = {
            'totalPdvs': len(pdvs),
            'totalRutas': len(rutas_unicas),
            'totalKm': total_km,
            'totalHoras': total_horas,
            'cobertura': cobertura
        }
        summary.update(estimate_people_required(all_daily_routes, rules))

        result = {
            'id': session_id,
            'timestamp': datetime.utcnow().isoformat() + "Z",
            'rutas': all_daily_routes,
            'omitidos': all_omitted,
            'summary': summary
        }

        execution_store[session_id] = result
        progress_store[session_id] = {"progress": 100, "status": "Completado"}
        logger.info(f"Sesión {session_id}: Optimización global completada con éxito.")
        
    except Exception as e:
        logger.error(f"Sesión {session_id}: Error en run_process_task: {str(e)}", exc_info=True)
        progress_store[session_id] = {"progress": 0, "status": f"Error: {str(e)}"}

async def run_estimate_capacity_task(
    session_id: str,
    data: List[Dict[str, Any]],
    rules_model: RulesModel,
    group_by: str,
    frequency_period: str = "week",
):
    try:
        progress_store[session_id] = {"progress": 0, "status": "Preparando datos para dimensionamiento..."}
        
        df = pd.DataFrame(data)
        rules = rules_model.model_dump()
        pdvs = parse_pdvs_from_df(df, rules_model, is_capacity=True, frequency_period=frequency_period)
        logger.info(f"Sesión {session_id}: Iniciando dimensionamiento para {len(pdvs)} PDVs")

        if len(pdvs) == 0:
            progress_store[session_id] = {"progress": 0, "status": "Error: No se encontraron PDVs válidos."}
            return

        optimizer = RouteOptimizer(rules)
        group_by_lower = group_by.lower()
        groups = list(set([p.get(group_by_lower) or 'Sin Definir' for p in pdvs]))
        
        progress_store[session_id] = {
            "progress": 5,
            "status": f"Dimensionando {len(groups)} grupos en paralelo..."
        }

        # Procesar los grupos en paralelo usando asyncio.gather
        async def process_single_group(group_name):
            remaining_pdvs = [p for p in pdvs if (p.get(group_by_lower) or 'Sin Definir') == group_name]
            person_index = 1
            group_routes = []
            group_omitted = []
            
            while len(remaining_pdvs) > 0:
                virtual_route_name = f"{group_name} - Persona {person_index}"
                for p in remaining_pdvs:
                    p['ruta'] = virtual_route_name
                    
                engine_result = await optimizer.process_route_monthly_aware(virtual_route_name, remaining_pdvs)
                
                if len(engine_result['dailyRoutes']) == 0 and len(engine_result['omitted']) > 0:
                    group_omitted.extend(engine_result['omitted'])
                    break
                    
                for dr in engine_result['dailyRoutes']:
                    dr['personId'] = person_index
                    group_routes.append(dr)
                    
                assigned_ids = set([p['pdv']['id'] for dr in engine_result['dailyRoutes'] for p in dr['paradas']])
                remaining_pdvs = [p for p in remaining_pdvs if p['id'] not in assigned_ids]
                
                if len(assigned_ids) == 0:
                    group_omitted.extend(engine_result['omitted'])
                    break
                    
                person_index += 1
                
            # Incrementar progreso parcial
            current = progress_store[session_id]["progress"]
            progress_store[session_id]["progress"] = min(95, current + max(1, int(90 / len(groups))))
            progress_store[session_id]["status"] = f"Dimensionado grupo: {group_name}"
            
            return group_routes, group_omitted

        tasks = [process_single_group(name) for name in groups]
        group_results = await asyncio.gather(*tasks)
        
        all_daily_routes = []
        all_omitted = []
        
        for g_routes, g_omitted in group_results:
            all_daily_routes.extend(g_routes)
            all_omitted.extend(g_omitted)

        total_km = sum([r['kmTotales'] for r in all_daily_routes])
        total_horas = sum([r['horasTrabajadas'] for r in all_daily_routes])
        cobertura = ((len(pdvs) - len(all_omitted)) / len(pdvs)) * 100.0 if len(pdvs) > 0 else 0.0
        people_metrics = estimate_people_required(all_daily_routes, rules)

        summary = {
            'totalPdvs': len(pdvs),
            'totalRutas': len(set([r['rutaNombre'] for r in all_daily_routes])),
            'totalKm': total_km,
            'totalHoras': total_horas,
            'cobertura': cobertura,
            'frecuenciaPeriodo': frequency_period,
            **people_metrics
        }

        result = {
            'id': session_id,
            'timestamp': datetime.utcnow().isoformat() + "Z",
            'rutas': all_daily_routes,
            'omitidos': all_omitted,
            'summary': summary
        }

        execution_store[session_id] = result
        progress_store[session_id] = {"progress": 100, "status": "Completado"}
        logger.info(f"Sesión {session_id}: Dimensionamiento completado con éxito.")

    except Exception as e:
        logger.error(f"Sesión {session_id}: Error en run_estimate_capacity_task: {str(e)}", exc_info=True)
        progress_store[session_id] = {"progress": 0, "status": f"Error: {str(e)}"}

# 7. Endpoints HTTP / SSE de la API
@app.post("/api/process")
def process_data(req: ProcessRequest, background_tasks: BackgroundTasks):
    session_id = str(uuid.uuid4())
    register_session(session_id)
    progress_store[session_id] = {"progress": 0, "status": "En cola..."}
    logger.info(f"Nueva solicitud de optimización. Asignando sessionId: {session_id}")
    background_tasks.add_task(run_process_task, session_id, req.fileContent, req.rules)
    return {"sessionId": session_id}

@app.get("/api/progress/{session_id}")
def get_progress(session_id: str):
    if session_id not in progress_store:
        raise HTTPException(status_code=404, detail="Sesión no encontrada")
    return progress_store[session_id]

# Endpoint Server-Sent Events (SSE) para progreso asíncrono en tiempo real
@app.get("/api/progress/stream/{session_id}")
async def progress_stream(session_id: str):
    async def event_generator():
        logger.info(f"Conexión flujo SSE abierta para sesión: {session_id}")
        last_progress = -1
        last_status = ""
        
        while True:
            if session_id in progress_store:
                data = progress_store[session_id]
                # Enviar sólo ante cambios reales de estado o progreso
                if data["progress"] != last_progress or data["status"] != last_status:
                    last_progress = data["progress"]
                    last_status = data["status"]
                    yield f"data: {json.dumps(data)}\n\n"
                    
                if data["progress"] >= 100 or data["status"].startswith("Error"):
                    logger.info(f"Conexión flujo SSE cerrada para sesión: {session_id}")
                    break
            else:
                yield f"data: {json.dumps({'progress': 0, 'status': 'En cola...'})}\n\n"
                
            await asyncio.sleep(0.5)
            
    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.get("/api/results/{session_id}")
def get_results(session_id: str):
    if session_id not in execution_store:
        raise HTTPException(status_code=404, detail="Resultados no listos o sesión no encontrada")
    return execution_store[session_id]

@app.post("/api/estimate-capacity")
def estimate_capacity(req: EstimateCapacityRequest, background_tasks: BackgroundTasks):
    session_id = str(uuid.uuid4())
    register_session(session_id)
    progress_store[session_id] = {"progress": 0, "status": "En cola..."}
    logger.info(f"Nueva solicitud de dimensionamiento. Asignando sessionId: {session_id}")
    background_tasks.add_task(run_estimate_capacity_task, session_id, req.data, req.rules, req.groupBy, req.frequencyPeriod)
    return {"sessionId": session_id}

@app.get("/api/session/{session_id}/map/{ruta_nombre}/{dia}", response_class=HTMLResponse)
def get_session_map(session_id: str, ruta_nombre: str, dia: str):
    """
    Exposes a premium dynamically generated Folium HTML map for an optimized route.
    If dia is 'all', merges all days of the specified route, color-coding each day.
    If dia is 1-6, renders just that single day's stops.
    """
    if session_id not in execution_store:
        raise HTTPException(status_code=404, detail="Sesión no encontrada o ha expirado")
        
    session_data = execution_store[session_id]
    all_routes = session_data.get("rutas", [])
    
    # Filter matching routes by name
    matching_routes = [r for r in all_routes if r.get("rutaNombre") == ruta_nombre]
    if not matching_routes:
        raise HTTPException(
            status_code=404, 
            detail=f"Ruta '{ruta_nombre}' no encontrada en la sesión {session_id}"
        )
        
    from map_generator import generate_folium_map
    
    if dia == "all":
        # Sort routes by day (Monday to Saturday)
        matching_routes = sorted(matching_routes, key=lambda r: r.get("dia", 1))
        flat_paradas = []
        for r in matching_routes:
            day_val = r.get("dia", 1)
            for p in r.get("paradas", []):
                p_copy = dict(p)
                p_copy["dia"] = day_val
                flat_paradas.append(p_copy)
        
        html_content = generate_folium_map(flat_paradas, day_filter=None)
    else:
        try:
            day_int = int(dia)
        except ValueError:
            raise HTTPException(status_code=400, detail="El día debe ser 'all' o un entero del 1 al 6")
            
        single_day_route = next((r for r in matching_routes if r.get("dia") == day_int), None)
        if not single_day_route:
            raise HTTPException(
                status_code=404, 
                detail=f"Ruta '{ruta_nombre}' no tiene programación para el día {dia}"
            )
            
        html_content = generate_folium_map(single_day_route.get("paradas", []), day_filter=day_int)
        
    return html_content

@app.get("/health")
def health():
    return {"status": "ok"}
