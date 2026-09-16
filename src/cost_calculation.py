import pandas as pd
import duckdb
import api

class Calculations:
    def __init__(self, code_postal, predi, carburant, code_po):
        # On attache les variables à l'instance courante avec self
        self.code_p = str(code_postal)
        #self.api_ = api.Donnees_gouv()
        self.api = predi
        self.con = duckdb.connect()
        self.con.execute("INSTALL spatial; LOAD spatial;")
        self.carbu = carburant
        self.cpo = code_po

    def in_radius(self, radius):
        # On trouve les coordonnées à partir du code postal
        donnees = pd.DataFrame(data=self.cpo)

        coordonnees = duckdb.execute("""
            SELECT longitude, latitude
            FROM donnees 
            WHERE code_postal = ?
            LIMIT 1
        """, [self.code_p]).fetchone()

        if not coordonnees:
            raise ValueError(f"Code postal {self.code_p} introuvable dans la base.")

        lon, lat = coordonnees

        #Il faut trier avec les stations qui sont dans le rayon
        rayon_metres = radius * 1000

        liste_stations = pd.DataFrame(data=self.api)

        resultats = self.con.execute(f"""
        SELECT 
            'https://www.google.com/maps/search/?api=1&query=' || 
        url_encode(concat_ws(' ', adresse, ville)) AS maps,
            carburant,
            date,
            prix_actuel,
            prix_predit_demain AS Prix_predit_demain,
            tendance,
            variation_predite_euros AS Variation,
            cp AS Code_postal,
            ville,
            adresse
        FROM liste_stations
        WHERE latitude IS NOT NULL AND longitude IS NOT NULL 
        AND ST_Distance_Sphere(
                    ST_Point(longitude, latitude), 
                    ST_Point({lon}, {lat})
      ) <= {rayon_metres} 
        AND carburant = '{self.carbu}'
        ORDER BY prix_actuel
        """)

        #
        return resultats

