import pandas as pd
import duckdb
import api

class Calculations:
    def __init__(self, code_postal):
        # On attache les variables à l'instance courante avec self
        self.code_p = str(code_postal)
        self.api_ = api.Donnees_gouv()

    def in_radius(self, radius):
        # 1. On trouve les coordonnées à partir du code postal
        donnees = duckdb.read_parquet("../data/code_coordonnees.parquet")

        coordonnees = duckdb.execute("""
            SELECT longitude, latitude
            FROM donnees 
            WHERE code_postal = ?
            LIMIT 1
        """, [self.code_p]).fetchone()

        if not coordonnees:
            raise ValueError(f"Code postal {self.code_p} introuvable dans la base.")

        lon, lat = coordonnees

        # 2. Appel à l'API gouvernementale
        liste_stations = self.api_.get(lon,lat,radius)["results"]
        liste_stations = pd.DataFrame(data=liste_stations)
        resultats = duckdb.sql("""
        SELECT 
            adresse,
            cp,
            ville,
            gazole_prix,
            e10_prix,
            sp98_prix
        FROM liste_stations
        WHERE latitude IS NOT NULL AND longitude IS NOT NULL
        ORDER BY e10_prix
        """)

        return resultats

