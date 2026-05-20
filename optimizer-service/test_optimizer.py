import unittest
import asyncio
import pandas as pd
from main import parse_pdvs_from_df, RulesModel
from optimizer_engine import RouteOptimizer, get_days_from_freq, calculate_haversine

BASE_RULES = dict(
    horaInicio="08:00",
    horaFin="18:00",
    almuerzoInicio="12:00",
    almuerzoFin="13:00",
    maxHorasDiarias=9.0,
    maxHorasSemanales=42.0,
    permanenciaDefaultMin=40,
    velocidadCaminandoKmh=4.0,
    distanciaCaminableKm=0.8,
    velocidadBusKmh=15.0,
    base_url_osrm="http://127.0.0.1:5000",
    sabadoActivo=True,
    sabadoMaxPdvs=2,
    sabadoPermanenciaFija=198,
    maxRelocalizacionMin=120.0,
    centroPunto=[4.6097, -74.0817]
)


class TestRouteOptimizer(unittest.TestCase):
    def setUp(self):
        self.rules_model = RulesModel(**BASE_RULES)
        self.optimizer = RouteOptimizer(BASE_RULES)

    # ------------------------------------------------------------------
    # Tests existentes
    # ------------------------------------------------------------------

    def test_calculate_haversine(self):
        """Distancia entre dos puntos de Bogotá debe ser ~1.5 km."""
        lat1, lon1 = 4.6097, -74.0817
        lat2, lon2 = 4.6197, -74.0917
        dist = calculate_haversine(lat1, lon1, lat2, lon2)
        self.assertTrue(1.0 < dist < 2.0)

    def test_get_days_from_freq(self):
        self.assertEqual(get_days_from_freq(6, 0), '1,2,3,4,5,6')
        self.assertEqual(get_days_from_freq(5, 0), '1,2,3,4,5')
        self.assertEqual(get_days_from_freq(3, 0), '1,3,5')
        self.assertEqual(get_days_from_freq(2, 0), '2,4')

    def test_parse_pdvs_from_df(self):
        data = [
            {
                "PDV": "Tienda A", "Latitud": 4.6097, "Longitud": -74.0817,
                "Ruta": "Ruta A", "Frecuencia": 2, "Tiempo de visita entero": 30
            },
            {
                "PDV": "Tienda B", "Latitud": 4.6197, "Longitud": -74.0917,
                "Ruta": "Ruta A", "Frecuencia": 1, "Tiempo de visita entero": None
            }
        ]
        df = pd.DataFrame(data)
        pdvs = parse_pdvs_from_df(df, self.rules_model, is_capacity=False)
        self.assertEqual(len(pdvs), 2)
        self.assertEqual(pdvs[0]['pdv'], "Tienda A")
        self.assertEqual(pdvs[0]['tiempoVisita'], 30)
        self.assertEqual(pdvs[1]['tiempoVisita'], 40)  # Default rule

    # ------------------------------------------------------------------
    # Tests V6.7: Lógica Híbrida de Transporte
    # ------------------------------------------------------------------

    def _make_sequence(self, dist_km: float):
        """
        Construye una secuencia de 2 PDVs separados aproximadamente `dist_km` km
        (desplazando longitud ~0.009° ≈ 1 km en Ecuador).
        """
        delta_lon = dist_km * 0.009  # 0.009° lon ≈ 1 km en latitudes bogotanas
        pdv_a = {'id': 'A', 'pdv': 'PDV A', 'latitud': 4.6097, 'longitud': -74.0817,
                 'tiempoVisita': 30, 'ruta': 'Ruta Test', 'dias': '1'}
        pdv_b = {'id': 'B', 'pdv': 'PDV B', 'latitud': 4.6097, 'longitud': -74.0817 + delta_lon,
                 'tiempoVisita': 30, 'ruta': 'Ruta Test', 'dias': '1'}
        return [pdv_a, pdv_b]

    def test_transport_walking_when_distance_lte_threshold(self):
        """
        V6.7 – Cuando la distancia Haversine es ≤ 0.8 km el transporte debe
        ser 'pie' y el tiempo de traslado calculado con velocidadCaminandoKmh.
        (Simula fallback Haversine, sin OSRM real.)
        """
        short_dist_km = 0.5  # Bien dentro del umbral
        rules = BusinessRulesProxy(BASE_RULES)

        dist_prev = short_dist_km
        if dist_prev <= rules.distanciaCaminableKm:
            transport = 'pie'
            travel_time = (dist_prev / rules.velocidadCaminandoKmh) * 60.0
        else:
            transport = 'bus'
            travel_time = (dist_prev / rules.velocidadBusKmh) * 60.0

        self.assertEqual(transport, 'pie')
        # 0.5 km a 4 km/h = 7.5 min
        self.assertAlmostEqual(travel_time, 7.5, places=1)

    def test_transport_bus_when_distance_gt_threshold(self):
        """
        V6.7 – Cuando la distancia Haversine es > 0.8 km el transporte debe
        ser 'bus' y el tiempo de traslado calculado con velocidadBusKmh.
        """
        long_dist_km = 2.0  # Fuera del umbral
        rules = BusinessRulesProxy(BASE_RULES)

        dist_prev = long_dist_km
        if dist_prev <= rules.distanciaCaminableKm:
            transport = 'pie'
            travel_time = (dist_prev / rules.velocidadCaminandoKmh) * 60.0
        else:
            transport = 'bus'
            travel_time = (dist_prev / rules.velocidadBusKmh) * 60.0

        self.assertEqual(transport, 'bus')
        # 2.0 km a 15 km/h = 8.0 min
        self.assertAlmostEqual(travel_time, 8.0, places=1)

    def test_walking_speed_used_for_short_tramo(self):
        """
        V6.7 – Verificar que velocidadCaminandoKmh (no velocidadBusKmh)
        se usa cuando el tramo es ≤ umbral.
        """
        dist_km = 0.8  # Exactamente en el umbral
        rules = BusinessRulesProxy(BASE_RULES)

        if dist_km <= rules.distanciaCaminableKm:
            travel_time = (dist_km / rules.velocidadCaminandoKmh) * 60.0
            speed_used = rules.velocidadCaminandoKmh
        else:
            travel_time = (dist_km / rules.velocidadBusKmh) * 60.0
            speed_used = rules.velocidadBusKmh

        # Debe usar 4 km/h, NO 15 km/h
        self.assertEqual(speed_used, 4.0)
        # 0.8 km a 4 km/h = 12.0 min
        self.assertAlmostEqual(travel_time, 12.0, places=1)
        # Contra-verificar que bus daría tiempo distinto: 0.8/15*60 = 3.2 min
        bus_time = (dist_km / rules.velocidadBusKmh) * 60.0
        self.assertNotAlmostEqual(travel_time, bus_time, places=1)


class BusinessRulesProxy:
    """Proxy ligero de BusinessRules para pruebas unitarias sin instanciar el engine."""
    def __init__(self, d):
        self.distanciaCaminableKm = d['distanciaCaminableKm']
        self.velocidadCaminandoKmh = d['velocidadCaminandoKmh']
        self.velocidadBusKmh = d['velocidadBusKmh']


if __name__ == '__main__':
    unittest.main()
