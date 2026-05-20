import unittest
import pandas as pd
from main import parse_pdvs_from_df, RulesModel
from optimizer_engine import RouteOptimizer, get_days_from_freq, calculate_haversine

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

if __name__ == '__main__':
    unittest.main()
