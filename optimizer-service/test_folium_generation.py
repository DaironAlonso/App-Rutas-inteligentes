import unittest
from fastapi.testclient import TestClient
from main import app, execution_store
from map_generator import generate_folium_map

class TestFoliumGeneration(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        # Prepare mock paradas
        self.mock_paradas = [
            {
                "pdv": {
                    "id": "1",
                    "pdv": "Tienda San Andres",
                    "latitud": 4.6097,
                    "longitud": -74.0817,
                    "direccion": "Calle 10 # 5-6"
                },
                "horaLlegada": "08:00",
                "horaSalida": "08:40",
                "distanciaPreviaKm": 0.0,
                "tiempoTrasladoMin": 0.0,
                "tipoTransporte": "pie"
            },
            {
                "pdv": {
                    "id": "2",
                    "pdv": "Supermercado Exito",
                    "latitud": 4.6197,
                    "longitud": -74.0917,
                    "direccion": "Carrera 15 # 12-4"
                },
                "horaLlegada": "09:10",
                "horaSalida": "09:50",
                "distanciaPreviaKm": 1.5,
                "tiempoTrasladoMin": 15.0,
                "tipoTransporte": "car",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [
                        [-74.0817, 4.6097],
                        [-74.0850, 4.6130],
                        [-74.0917, 4.6197]
                    ]
                }
            }
        ]

    def test_generate_folium_map_returns_valid_html(self):
        # 1. Test single-day rendering
        html_content = generate_folium_map(self.mock_paradas, day_filter=1)
        self.assertIsInstance(html_content, str)
        self.assertIn("<!DOCTYPE html>", html_content)
        self.assertIn("Tienda San Andres", html_content)
        self.assertIn("Supermercado Exito", html_content)
        self.assertIn("Tramo Vehículo", html_content)  # Legend check
        self.assertIn("Tramo A Pie", html_content)

        # 2. Test all-days combined rendering
        all_days_paradas = []
        for d in [1, 2]:
            for p in self.mock_paradas:
                p_copy = dict(p)
                p_copy["dia"] = d
                all_days_paradas.append(p_copy)
                
        html_content_all = generate_folium_map(all_days_paradas, day_filter=None)
        self.assertIsInstance(html_content_all, str)
        self.assertIn("Lunes", html_content_all)
        self.assertIn("Martes", html_content_all)

    def test_api_endpoint_delivers_map(self):
        session_id = "test-session-123"
        # Mock the session data in execution_store
        execution_store[session_id] = {
            "id": session_id,
            "rutas": [
                {
                    "rutaNombre": "Ruta Bogota Norte",
                    "dia": 1,
                    "paradas": self.mock_paradas,
                    "horasTrabajadas": 2.5,
                    "kmTotales": 1.5
                },
                {
                    "rutaNombre": "Ruta Bogota Norte",
                    "dia": 2,
                    "paradas": self.mock_paradas,
                    "horasTrabajadas": 2.5,
                    "kmTotales": 1.5
                }
            ]
        }

        try:
            # Test individual day endpoint
            response = self.client.get(f"/api/session/{session_id}/map/Ruta%20Bogota%20Norte/1")
            self.assertEqual(response.status_code, 200)
            self.assertIn("text/html", response.headers["content-type"])
            self.assertIn("Tienda San Andres", response.text)

            # Test combined all-days endpoint
            response_all = self.client.get(f"/api/session/{session_id}/map/Ruta%20Bogota%20Norte/all")
            self.assertEqual(response_all.status_code, 200)
            self.assertIn("text/html", response_all.headers["content-type"])
            self.assertIn("Tienda San Andres", response_all.text)
            self.assertIn("Lunes", response_all.text)
            self.assertIn("Martes", response_all.text)

            # Test 404 for invalid session
            response_404_session = self.client.get("/api/session/non-existent/map/Ruta%20Bogota%20Norte/1")
            self.assertEqual(response_404_session.status_code, 404)

            # Test 404 for invalid route name
            response_404_route = self.client.get(f"/api/session/{session_id}/map/InvalidRoute/1")
            self.assertEqual(response_404_route.status_code, 404)

        finally:
            # Clean up execution_store mock data
            execution_store.pop(session_id, None)

if __name__ == '__main__':
    unittest.main()
