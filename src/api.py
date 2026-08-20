import requests

class Donnees_gouv:
    BASE_URL = "https://data.economie.gouv.fr/api/explore/v2.1/catalog/datasets/prix-des-carburants-en-france-flux-instantane-v2/records"

    def __init__(self):
        self.headers = {"Content-Type": "application/json"}

    def get(self, lon: float, lat: float, radius_km: float = 15, limit: int = 100):
        """
        Récupère les stations dans un rayon donné (en km) autour d'un point GPS.
        """
        params = {
            "where": f"within_distance(geom, geom'POINT({lon} {lat})', {radius_km}km)",
            "limit": limit,
            "lang": "fr"
        }
        
        response = requests.get(self.BASE_URL, headers=self.headers, params=params, timeout=10)
        response.raise_for_status()
        return response.json()

   
