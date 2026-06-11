import math
import httpx
import asyncio
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from ortools.constraint_solver import routing_enums_pb2
from ortools.constraint_solver import pywrapcp
from config import config


def calculate_haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calcula la distancia Haversine en kilómetros entre dos puntos."""
    R = 6371.0  # Radio de la Tierra en km
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (math.sin(d_lat / 2.0) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(d_lon / 2.0) ** 2)
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return R * c

def haversine_m(p1: Dict[str, Any], p2: Dict[str, Any]) -> int:
    """Calcula la distancia Haversine en metros (entero)."""
    dist_km = calculate_haversine(p1['latitud'], p1['longitud'], p2['latitud'], p2['longitud'])
    return int(dist_km * 1000.0)

def parse_time_to_minutes(time_str: str) -> int:
    """Convierte una cadena de hora "HH:MM" a minutos transcurridos desde la medianoche."""
    try:
        h, m = map(int, time_str.split(':'))
        return h * 60 + m
    except Exception:
        return 0

def format_minutes_to_time(minutes: int) -> str:
    """Convierte minutos transcurridos desde la medianoche a formato "HH:MM"."""
    h = (minutes // 60) % 24
    m = minutes % 60
    return f"{h:02d}:{m:02d}"

def get_days_from_freq(freq: int, index: int) -> str:
    """Retorna los días de visita asignados según la frecuencia."""
    if freq >= 6:
        return '1,2,3,4,5,6'
    if freq == 5:
        return '1,2,3,4,5'
    if freq == 4:
        return '1,2,4,5'
    if freq == 3:
        return '1,3,5'
    if freq == 2:
        return '2,4'
    start_day = (index % 6) + 1
    return str(start_day)

def get_weeks_from_monthly_freq(freq: int, index: int) -> str:
    """Retorna semanas únicas del mes para una frecuencia mensual de 1 a 4."""
    visits = min(max(int(freq), 1), 4)
    start_week = index % 4
    weeks = sorted({((start_week + offset) % 4) + 1 for offset in range(visits)})
    return ",".join(str(week) for week in weeks)

class BusinessRules:
    def __init__(self, rules_dict: Dict[str, Any]):
        self.horaInicio = rules_dict.get('horaInicio', '08:00')
        self.horaFin = rules_dict.get('horaFin', '18:00')
        self.almuerzoInicio = rules_dict.get('almuerzoInicio', '12:00')
        self.almuerzoFin = rules_dict.get('almuerzoFin', '13:00')
        self.maxHorasDiarias = rules_dict.get('maxHorasDiarias', 9.0)
        self.maxHorasSemanales = rules_dict.get('maxHorasSemanales', 42.0)
        self.permanenciaDefaultMin = rules_dict.get('permanenciaDefaultMin', 40)
        self.velocidadCaminandoKmh = rules_dict.get('velocidadCaminandoKmh', 4.0)
        self.distanciaCaminableKm = rules_dict.get('distanciaCaminableKm', 0.8)
        self.velocidadBusKmh = rules_dict.get('velocidadBusKmh', 15.0)
        self.base_url_osrm = rules_dict.get('base_url_osrm', 'http://127.0.0.1:5000')
        self.sabadoActivo = rules_dict.get('sabadoActivo', True)
        self.sabadoMaxPdvs = rules_dict.get('sabadoMaxPdvs', 2)
        self.sabadoPermanenciaFija = rules_dict.get('sabadoPermanenciaFija', 198)
        self.maxRelocalizacionMin = rules_dict.get('maxRelocalizacionMin', 120.0)
        self.centroPunto = rules_dict.get('centroPunto', [4.6097, -74.0817])

class RouteOptimizer:
    def __init__(self, rules_dict: Dict[str, Any]):
        self.rules = BusinessRules(rules_dict)
        self.osrm_cache = {}
        self.osrm_failures = {}  # Track failed requests with timestamp

    async def fetch_osrm(self, start: List[float], end: List[float], mode: str = 'car') -> Optional[Dict[str, Any]]:
        """
        Llama a OSRM para obtener la geometría y distancia real.
        Intenta primero el contenedor local y luego el servidor público.
        Implements circuit breaker with exponential backoff and failure caching.
        """
        profile = mode
        key = f"{start[0]:.5f},{start[1]:.5f}-{end[0]:.5f},{end[1]:.5f}-{profile}"
        
        # Check if we have cached result
        if key in self.osrm_cache:
            return self.osrm_cache[key]
        
        # Check if we're in failure cache period
        if key in self.osrm_failures:
            failure_time, retry_count = self.osrm_failures[key]
            cache_expiry = failure_time + timedelta(minutes=config.OSRM_FAILURE_CACHE_MINUTES)
            if datetime.now() < cache_expiry:
                print(f"[OSRM] Circuit breaker active for {key}, skipping (failed {retry_count} times)")
                return None
            else:
                # Cache expired, remove from failures and retry
                del self.osrm_failures[key]

        # URLs a intentar: 1. Contenedor local, 2. Servidor público
        urls = [
            f"{self.rules.base_url_osrm.rstrip('/')}/route/v1/{profile}/{start[1]},{start[0]};{end[1]},{end[0]}?overview=full&geometries=geojson",
            f"http://router.project-osrm.org/route/v1/{profile}/{start[1]},{start[0]};{end[1]},{end[0]}?overview=full&geometries=geojson"
        ]
        
        max_retries = config.OSRM_MAX_RETRIES
        backoff_base = config.OSRM_RETRY_BACKOFF_BASE
        
        for url in urls:
            for attempt in range(max_retries):
                try:
                    print(f"[OSRM] Attempt {attempt + 1}/{max_retries} using URL: {url}")
                    async with httpx.AsyncClient() as client:
                        resp = await client.get(url, timeout=5.0)
                        if resp.status_code == 200:
                            data = resp.json()
                            if data.get('code') == 'Ok' and data.get('routes'):
                                route = data['routes'][0]
                                result = {
                                    'distance': route['distance'] / 1000.0,  # Convertir a km
                                    'duration': route['duration'] / 60.0,    # Convertir a minutos
                                    'geometry': route['geometry']
                                }
                                self.osrm_cache[key] = result
                                print(f"[OSRM] Success for {key} using {url}")
                                return result
                except Exception as e:
                    print(f"[OSRM] Attempt {attempt + 1}/{max_retries} failed for {url}: {e}")
                    if attempt < max_retries - 1:
                        wait_time = backoff_base * (2 ** attempt)
                        await asyncio.sleep(wait_time)
            
            print(f"[OSRM] URL {url} exhausted.")

        # All URLs and retries exhausted, cache the failure
        print(f"[OSRM] All attempts exhausted for {key}")
        self.osrm_failures[key] = (datetime.now(), max_retries)
        return None

    def should_visit_today(self, pdv: Dict[str, Any], day: int) -> bool:
        """Determina si un PDV debe ser visitado en el día especificado."""
        dias_raw = pdv.get('dias')
        if not dias_raw:
            return False
        
        try:
            dias_str = str(dias_raw).replace(',', ' ').split()
            dias_permitidos = [int(d) for d in dias_str if d.isdigit()]
            return day in dias_permitidos
        except Exception:
            return False

    def should_visit_in_week(self, pdv: Dict[str, Any], week: int) -> bool:
        """Determina si un PDV mensual debe visitarse en la semana indicada."""
        semanas_raw = pdv.get('semanasMes')
        if not semanas_raw:
            return True

        try:
            weeks_str = str(semanas_raw).replace(',', ' ').split()
            semanas_permitidas = [int(w) for w in weeks_str if w.isdigit()]
            return week in semanas_permitidas
        except Exception:
            return False

    def optimize_with_or_tools(self, pdvs: List[Dict[str, Any]]) -> List[int]:
        """Aplica Google OR-Tools para calcular el orden óptimo considerando restricciones de tiempo e itinerarios híbridos."""
        n = len(pdvs)
        if n <= 2:
            return list(range(n))

        # 1. Matriz de distancias Haversine en metros
        dist_matrix = [[haversine_m(pdvs[i], pdvs[j]) for j in range(n)] for i in range(n)]

        # 2. Matriz de tiempos de tránsito híbrida
        service_time = []
        for i in range(n):
            if i == 0:
                service_time.append(0)  # Depósito inicial no suma tiempo de permanencia al iniciar
            else:
                service_time.append(pdvs[i].get('tiempoVisita') or self.rules.permanenciaDefaultMin)

        travel_time = [[0] * n for _ in range(n)]
        for i in range(n):
            for j in range(n):
                if i == j:
                    travel_time[i][j] = 0
                    continue
                dist_km = dist_matrix[i][j] / 1000.0
                if dist_km <= self.rules.distanciaCaminableKm:
                    t_min = (dist_km / self.rules.velocidadCaminandoKmh) * 60.0
                else:
                    t_min = (dist_km / self.rules.velocidadBusKmh) * 60.0
                
                # Penalizar arcos que excedan el límite de traslado máximo
                if t_min > self.rules.maxRelocalizacionMin:
                    travel_time[i][j] = 999999
                else:
                    travel_time[i][j] = int(t_min)

        manager = pywrapcp.RoutingIndexManager(n, 1, 0)
        routing = pywrapcp.RoutingModel(manager)

        # Tránsito del arco i -> j = tiempo de viaje + tiempo de permanencia en i
        def time_callback(from_idx, to_idx):
            from_node = manager.IndexToNode(from_idx)
            to_node = manager.IndexToNode(to_idx)
            return travel_time[from_node][to_node] + service_time[from_node]

        time_cb = routing.RegisterTransitCallback(time_callback)

        # El objetivo principal sigue siendo minimizar la distancia caminada total
        def distance_callback(from_idx, to_idx):
            return dist_matrix[manager.IndexToNode(from_idx)][manager.IndexToNode(to_idx)]

        dist_cb = routing.RegisterTransitCallback(distance_callback)
        routing.SetArcCostEvaluatorOfAllVehicles(dist_cb)

        # Restricción de jornada diaria (neto de almuerzo)
        h_start = parse_time_to_minutes(self.rules.horaInicio)
        h_end = parse_time_to_minutes(self.rules.horaFin)
        l_start = parse_time_to_minutes(self.rules.almuerzoInicio)
        l_end = parse_time_to_minutes(self.rules.almuerzoFin)
        lunch_dur = max(0, l_end - l_start)
        max_minutes = max(60, (h_end - h_start) - lunch_dur)

        routing.AddDimension(
            time_cb,
            0,  # Sin tolerancia (slack)
            int(max_minutes),
            True,  # Iniciar acumulador de tiempo en 0
            "Time"
        )

        # Habilitar omisión opcional (Disjunctions) con penalización alta
        penalty = 1000000
        for i in range(1, n):
            routing.AddDisjunction([manager.NodeToIndex(i)], penalty)

        params = pywrapcp.DefaultRoutingSearchParameters()
        params.first_solution_strategy = (
            routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
        )
        params.local_search_metaheuristic = (
            routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
        )
        params.time_limit.seconds = 3

        solution = routing.SolveWithParameters(params)

        if solution:
            order = []
            idx = routing.Start(0)
            while not routing.IsEnd(idx):
                order.append(manager.IndexToNode(idx))
                idx = solution.Value(routing.NextVar(idx))
            return order

        return list(range(n))

    def optimize_sequence_fallback(self, pdvs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Fallback: Algoritmo Nearest Neighbor si OR-Tools o el servidor fallan."""
        if len(pdvs) <= 1:
            return pdvs
        
        remaining = list(pdvs)
        result = [remaining.pop(0)]
        
        while len(remaining) > 0:
            current = result[-1]
            nearest_idx = 0
            min_dist = float('inf')
            
            for idx, item in enumerate(remaining):
                d = calculate_haversine(current['latitud'], current['longitud'], item['latitud'], item['longitud'])
                if d < min_dist:
                    min_dist = d
                    nearest_idx = idx
            
            result.append(remaining.pop(nearest_idx))
        return result

    async def build_itinerary(self, day: int, ruta_nombre: str, sequence: List[Dict[str, Any]], current_weekly_hours: float) -> Dict[str, Any]:
        """Calcula el itinerario detallado minuto a minuto respetando almuerzos y jornadas mixtas (a pie y en carro)."""
        paradas = []
        omitted = []
        
        current_time_min = parse_time_to_minutes(self.rules.horaInicio)
        end_time_min = parse_time_to_minutes(self.rules.horaFin)
        lunch_start_min = parse_time_to_minutes(self.rules.almuerzoInicio)
        lunch_end_min = parse_time_to_minutes(self.rules.almuerzoFin)
        lunch_duration_min = max(0, lunch_end_min - lunch_start_min)
        
        km_totales = 0.0
        labor_time_minutes = 0.0

        for i, p in enumerate(sequence):
            # Regla de Sábado activa
            if day == 6 and self.rules.sabadoActivo and len(paradas) >= self.rules.sabadoMaxPdvs:
                omitted.append({
                    'pdv': p,
                    'motivo': 'Límite PDVs Sábado',
                    'dia': day
                })
                continue

            dist_prev = 0.0
            travel_time = 0.0
            transport = 'pie'
            geometry = None

            if i > 0:
                prev = sequence[i - 1]
                haversine_dist = calculate_haversine(prev['latitud'], prev['longitud'], p['latitud'], p['longitud'])
                
                es_pie = haversine_dist <= self.rules.distanciaCaminableKm
                profile = "foot" if es_pie else "car"
                
                osrm_data = await self.fetch_osrm([prev['latitud'], prev['longitud']], [p['latitud'], p['longitud']], profile)
                
                # Fallback to 'car' profile if 'foot' profile is unsupported on public/local OSRM servers
                if not osrm_data and profile == 'foot':
                    print("[OSRM] 'foot' profile failed or not loaded. Falling back to 'car' profile...")
                    osrm_data = await self.fetch_osrm([prev['latitud'], prev['longitud']], [p['latitud'], p['longitud']], 'car')
                
                if osrm_data:
                    dist_prev = osrm_data['distance']
                    geometry = osrm_data['geometry']
                    
                    # Decidir tipo de transporte basado en el umbral
                    if dist_prev <= self.rules.distanciaCaminableKm:
                        transport = 'pie'
                        travel_time = (dist_prev / self.rules.velocidadCaminandoKmh) * 60.0
                    else:
                        transport = 'carro'
                        travel_time = osrm_data['duration']  # Duración de OSRM en minutos
                else:
                    dist_prev = haversine_dist
                    if dist_prev <= self.rules.distanciaCaminableKm:
                        transport = 'pie'
                        travel_time = (dist_prev / self.rules.velocidadCaminandoKmh) * 60.0
                    else:
                        transport = 'carro'
                        travel_time = (dist_prev / self.rules.velocidadBusKmh) * 60.0

            if travel_time > self.rules.maxRelocalizacionMin:
                omitted.append({
                    'pdv': p,
                    'motivo': f"Traslado > {self.rules.maxRelocalizacionMin}m",
                    'dia': day
                })
                continue

            arrival_time_min = current_time_min + travel_time
            
            # Almuerzo durante traslado
            if arrival_time_min > lunch_start_min and current_time_min < lunch_end_min:
                arrival_time_min += lunch_duration_min

            is_special_saturday = (day == 6 and self.rules.sabadoActivo)
            permanencia = self.rules.sabadoPermanenciaFija if is_special_saturday else (p.get('tiempoVisita') or self.rules.permanenciaDefaultMin)
            finish_time_min = arrival_time_min + permanencia

            # Almuerzo durante permanencia
            if finish_time_min > lunch_start_min and arrival_time_min < lunch_end_min:
                finish_time_min += lunch_duration_min

            # Exceder el horario fin del día o tope semanal
            if finish_time_min > end_time_min or (current_weekly_hours + (labor_time_minutes + permanencia) / 60.0) > self.rules.maxHorasSemanales:
                omitted.append({
                    'pdv': p,
                    'motivo': 'Sin tiempo en jornada',
                    'dia': day
                })
                continue

            paradas.append({
                'pdv': p,
                'horaLlegada': format_minutes_to_time(int(arrival_time_min)),
                'horaSalida': format_minutes_to_time(int(finish_time_min)),
                'distanciaPreviaKm': dist_prev,
                'tiempoTrasladoMin': travel_time,
                'tipoTransporte': transport,
                'geometry': geometry
            })

            km_totales += dist_prev
            labor_time_minutes += (travel_time + permanencia)
            current_time_min = finish_time_min

        geometries = [p['geometry'] for p in paradas if p.get('geometry') and p['geometry'].get('coordinates')]
        combined_geo = None
        if len(geometries) > 0:
            combined_geo = {
                'type': 'MultiLineString',
                'coordinates': [g['coordinates'] for g in geometries]
            }

        return {
            'route': {
                'dia': day,
                'rutaNombre': ruta_nombre,
                'paradas': paradas,
                'horasTrabajadas': labor_time_minutes / 60.0,
                'kmTotales': km_totales,
                'geometriaRaw': combined_geo
            },
            'omitted': omitted
        }

    async def process_route_monthly_aware(self, ruta_nombre: str, pdvs: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Procesa una ruta semanal o un calendario mensual de 4 semanas."""
        daily_routes = []
        omitted = []
        has_monthly_plan = any(p.get('semanasMes') for p in pdvs)
        weeks_to_process = range(1, 5) if has_monthly_plan else range(1, 2)

        for week in weeks_to_process:
            weekly_hours = 0.0

            for day in range(1, 7):
                active_pdvs = [
                    p for p in pdvs
                    if self.should_visit_in_week(p, week) and self.should_visit_today(p, day)
                ]
                if len(active_pdvs) == 0:
                    continue

                try:
                    order_indices = await asyncio.to_thread(self.optimize_with_or_tools, active_pdvs)
                    optimized_order = [active_pdvs[i] for i in order_indices]
                except Exception as e:
                    print(f"Error en optimizacion OR-Tools, activando fallback local: {e}")
                    optimized_order = self.optimize_sequence_fallback(active_pdvs)

                result = await self.build_itinerary(day, ruta_nombre, optimized_order, weekly_hours)
                
                if len(result['route']['paradas']) > 0:
                    result['route']['semanaMes'] = week if has_monthly_plan else None
                    daily_routes.append(result['route'])
                    weekly_hours += result['route']['horasTrabajadas']
                for item in result['omitted']:
                    item['semanaMes'] = week if has_monthly_plan else None
                omitted.extend(result['omitted'])

        return {
            'dailyRoutes': daily_routes,
            'omitted': omitted
        }

    async def process_route(self, ruta_nombre: str, pdvs: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Procesa y optimiza la ruta para cada uno de los días de la semana laboral."""
        daily_routes = []
        omitted = []
        weekly_hours = 0.0

        for day in range(1, 7):
            active_pdvs = [p for p in pdvs if self.should_visit_today(p, day)]
            if len(active_pdvs) == 0:
                continue

            try:
                order_indices = await asyncio.to_thread(self.optimize_with_or_tools, active_pdvs)
                optimized_order = [active_pdvs[i] for i in order_indices]
            except Exception as e:
                print(f"Error en optimización OR-Tools, activando fallback local: {e}")
                optimized_order = self.optimize_sequence_fallback(active_pdvs)

            result = await self.build_itinerary(day, ruta_nombre, optimized_order, weekly_hours)
            
            if len(result['route']['paradas']) > 0:
                daily_routes.append(result['route'])
                weekly_hours += result['route']['horasTrabajadas']
            omitted.extend(result['omitted'])

        return {
            'dailyRoutes': daily_routes,
            'omitted': omitted
        }
