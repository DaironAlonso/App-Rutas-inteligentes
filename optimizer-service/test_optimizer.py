import unittest
import pandas as pd
from main import parse_pdvs_from_df, RulesModel, estimate_people_required
from optimizer_engine import RouteOptimizer, get_days_from_freq, get_weeks_from_monthly_freq, calculate_haversine

class TestRouteOptimizer(unittest.TestCase):
    def setUp(self):
        self.rules = RulesModel(
            horaInicio="08:00",
            horaFin="18:00",
            almuerzoInicio="12:00",
            almuerzoFin="13:00",
            maxHorasDiarias=9.0,
            maxHorasSemanales=42.0,
            permanenciaDefaultMin=40,
            velocidadCaminandoKmh=4.0,
            sabadoActivo=True,
            sabadoMaxPdvs=2,
            sabadoPermanenciaFija=198,
            maxRelocalizacionMin=120.0,
            centroPunto=[4.6097, -74.0817]
        )

    def test_calculate_haversine(self):
        # Distancia aproximada entre dos puntos de Bogotá
        lat1, lon1 = 4.6097, -74.0817
        lat2, lon2 = 4.6197, -74.0917
        dist = calculate_haversine(lat1, lon1, lat2, lon2)
        # Debe ser aproximadamente ~1.5 km
        self.assertTrue(1.0 < dist < 2.0)

    def test_get_days_from_freq(self):
        self.assertEqual(get_days_from_freq(6, 0), '1,2,3,4,5,6')
        self.assertEqual(get_days_from_freq(5, 0), '1,2,3,4,5')
        self.assertEqual(get_days_from_freq(3, 0), '1,3,5')
        self.assertEqual(get_days_from_freq(2, 0), '2,4')

    def test_get_weeks_from_monthly_freq(self):
        self.assertEqual(get_weeks_from_monthly_freq(1, 0), '1')
        self.assertEqual(get_weeks_from_monthly_freq(2, 0), '1,2')
        self.assertEqual(get_weeks_from_monthly_freq(3, 1), '2,3,4')
        self.assertEqual(get_weeks_from_monthly_freq(4, 3), '1,2,3,4')

    def test_parse_pdvs_from_df(self):
        data = [
            {
                "PDV": "Tienda A",
                "Latitud": 4.6097,
                "Longitud": -74.0817,
                "Ruta": "Ruta A",
                "Frecuencia": 2,
                "Tiempo de visita entero": 30
            },
            {
                "PDV": "Tienda B",
                "Latitud": 4.6197,
                "Longitud": -74.0917,
                "Ruta": "Ruta A",
                "Frecuencia": 1,
                "Tiempo de visita entero": None  # Debería usar el default
            }
        ]
        df = pd.DataFrame(data)
        pdvs = parse_pdvs_from_df(df, self.rules, is_capacity=False)
        self.assertEqual(len(pdvs), 2)
        self.assertEqual(pdvs[0]['pdv'], "Tienda A")
        self.assertEqual(pdvs[0]['frecuencia'], 2)
        self.assertEqual(pdvs[0]['tiempoVisita'], 30)
        self.assertEqual(pdvs[1]['pdv'], "Tienda B")
        self.assertEqual(pdvs[1]['tiempoVisita'], 40)  # Default rule

    def test_parse_pdvs_filters_invalid_coordinates_and_caps_frequency(self):
        df = pd.DataFrame([
            {"PDV": "Valido", "Latitud": 4.6097, "Longitud": -74.0817, "Frecuencia": 9},
            {"PDV": "Lat invalida", "Latitud": 120, "Longitud": -74.0817, "Frecuencia": 1},
        ])
        pdvs = parse_pdvs_from_df(df, self.rules, is_capacity=False)
        self.assertEqual(len(pdvs), 1)
        self.assertEqual(pdvs[0]["frecuencia"], 6)

    def test_parse_capacity_monthly_frequency_assigns_unique_weeks(self):
        df = pd.DataFrame([
            {"PDV": "Mensual 1", "Latitud": 4.6097, "Longitud": -74.0817, "Frecuencia": 1},
            {"PDV": "Mensual 2", "Latitud": 4.6197, "Longitud": -74.0917, "Frecuencia": 2},
            {"PDV": "Mensual 3", "Latitud": 4.6297, "Longitud": -74.1017, "Frecuencia": 3},
        ])
        pdvs = parse_pdvs_from_df(df, self.rules, is_capacity=True, frequency_period="month")
        self.assertEqual(len(pdvs), 3)
        self.assertEqual(pdvs[0]["frecuencia"], 1)
        self.assertEqual(pdvs[0]["semanasMes"], "1")
        self.assertEqual(pdvs[1]["frecuencia"], 2)
        self.assertEqual(pdvs[1]["semanasMes"], "2,3")
        self.assertEqual(pdvs[2]["frecuencia"], 3)
        self.assertEqual(pdvs[2]["semanasMes"], "1,3,4")
        self.assertEqual(pdvs[0]["dias"], "1")

    def test_estimate_people_required_uses_hours_and_route_load(self):
        metrics = estimate_people_required(
            [
                {"rutaNombre": "Bogota - Persona 1", "horasTrabajadas": 42},
                {"rutaNombre": "Bogota - Persona 2", "horasTrabajadas": 18},
            ],
            {"maxHorasSemanales": 42},
        )
        self.assertEqual(metrics["personasPorHoras"], 2)
        self.assertEqual(metrics["personasRequeridas"], 2)


class TestRouteOptimizerAsync(unittest.IsolatedAsyncioTestCase):
    async def test_transport_switches_to_carro_after_walk_threshold(self):
        rules = {
            "horaInicio": "08:00",
            "horaFin": "18:00",
            "almuerzoInicio": "12:00",
            "almuerzoFin": "13:00",
            "distanciaCaminableKm": 0.8,
            "velocidadCaminandoKmh": 4.0,
            "velocidadBusKmh": 15.0,
            "maxRelocalizacionMin": 120.0,
            "permanenciaDefaultMin": 10,
            "maxHorasSemanales": 42,
            "sabadoActivo": False,
        }
        optimizer = RouteOptimizer(rules)
        async def no_osrm(*args, **kwargs):
            return None
        optimizer.fetch_osrm = no_osrm
        sequence = [
            {"id": "1", "pdv": "A", "latitud": 4.6097, "longitud": -74.0817, "tiempoVisita": 10},
            {"id": "2", "pdv": "B", "latitud": 4.6297, "longitud": -74.1017, "tiempoVisita": 10},
        ]
        result = await optimizer.build_itinerary(1, "Ruta A", sequence, 0)
        self.assertEqual(result["route"]["paradas"][1]["tipoTransporte"], "carro")

    async def test_transport_is_pie_when_within_walk_threshold(self):
        rules = {
            "horaInicio": "08:00",
            "horaFin": "18:00",
            "almuerzoInicio": "12:00",
            "almuerzoFin": "13:00",
            "distanciaCaminableKm": 0.8,
            "velocidadCaminandoKmh": 4.0,
            "velocidadBusKmh": 15.0,
            "maxRelocalizacionMin": 120.0,
            "permanenciaDefaultMin": 10,
            "maxHorasSemanales": 42,
            "sabadoActivo": False,
        }
        optimizer = RouteOptimizer(rules)
        async def no_osrm(*args, **kwargs):
            return None
        optimizer.fetch_osrm = no_osrm
        sequence = [
            {"id": "1", "pdv": "A", "latitud": 4.6097, "longitud": -74.0817, "tiempoVisita": 10},
            {"id": "2", "pdv": "B", "latitud": 4.6117, "longitud": -74.0817, "tiempoVisita": 10},
        ]
        result = await optimizer.build_itinerary(1, "Ruta A", sequence, 0)
        self.assertEqual(result["route"]["paradas"][1]["tipoTransporte"], "pie")

    async def test_uses_walking_speed_for_walking_legs(self):
        rules = {
            "horaInicio": "08:00",
            "horaFin": "18:00",
            "almuerzoInicio": "12:00",
            "almuerzoFin": "13:00",
            "distanciaCaminableKm": 0.8,
            "velocidadCaminandoKmh": 4.0,
            "velocidadBusKmh": 15.0,
            "maxRelocalizacionMin": 120.0,
            "permanenciaDefaultMin": 10,
            "maxHorasSemanales": 42,
            "sabadoActivo": False,
        }
        optimizer = RouteOptimizer(rules)
        async def no_osrm(*args, **kwargs):
            return None
        optimizer.fetch_osrm = no_osrm
        sequence = [
            {"id": "1", "pdv": "A", "latitud": 4.6097, "longitud": -74.0817, "tiempoVisita": 10},
            {"id": "2", "pdv": "B", "latitud": 4.6117, "longitud": -74.0817, "tiempoVisita": 10},
        ]
        result = await optimizer.build_itinerary(1, "Ruta A", sequence, 0)
        dist = calculate_haversine(4.6097, -74.0817, 4.6117, -74.0817)
        expected_time = (dist / 4.0) * 60.0
        self.assertAlmostEqual(result["route"]["paradas"][1]["tiempoTrasladoMin"], expected_time, places=2)

    async def test_monthly_route_uses_unique_weeks_without_repeating_same_week(self):
        rules = {
            "horaInicio": "08:00",
            "horaFin": "18:00",
            "almuerzoInicio": "12:00",
            "almuerzoFin": "13:00",
            "distanciaCaminableKm": 0.8,
            "velocidadCaminandoKmh": 4.0,
            "velocidadBusKmh": 15.0,
            "maxRelocalizacionMin": 120.0,
            "permanenciaDefaultMin": 10,
            "maxHorasSemanales": 42,
            "sabadoActivo": False,
        }
        optimizer = RouteOptimizer(rules)
        async def no_osrm(*args, **kwargs):
            return None
        optimizer.fetch_osrm = no_osrm
        pdvs = [
            {
                "id": "mensual-1",
                "pdv": "Mensual",
                "latitud": 4.6097,
                "longitud": -74.0817,
                "tiempoVisita": 10,
                "dias": "1",
                "semanasMes": "1,3,4",
            }
        ]
        result = await optimizer.process_route_monthly_aware("Ruta mensual", pdvs)
        weeks = [route["semanaMes"] for route in result["dailyRoutes"]]
        self.assertEqual(weeks, [1, 3, 4])
        self.assertEqual(len(weeks), len(set(weeks)))

if __name__ == '__main__':
    unittest.main()
