import datetime
import io
import os
import xml.etree.ElementTree as ET
import zipfile
import boto3
import duckdb
import joblib
import numpy as np
import pandas as pd
import requests
import yfinance as yf
from dotenv import load_dotenv

# Pipeline d'inférence quotidien (6h30)
# 1. Téléchargement des données (API gouv, yfinance)
# 2. Chargement des référentiels, du modèle et du buffer depuis S3
# 3. Feature engineering DuckDB
# 4. Inférence LightGBM + seuils métier
# 5. Export des prédictions et actualisation de l'état sur S3

load_dotenv()

BASE_URL_FUEL = "https://donnees.roulez-eco.fr/opendata/instantane"


print("Téléchargement des prix des carburants")
response_fuel = requests.get(BASE_URL_FUEL, timeout=30)
if response_fuel.status_code != 200:
    raise Exception(f"Erreur API carburants : {response_fuel.status_code}")

zfile = zipfile.ZipFile(io.BytesIO(response_fuel.content))
fuel_file = zfile.open(f"{zfile.namelist()[-1]}")
fuel_raw = fuel_file.read().decode(encoding="iso-8859-1")

root_fuel = ET.fromstring(fuel_raw)
lignes_carbu = []

for station in root_fuel:
    attribs = station.attrib
    lat = attribs.get("latitude")
    lon = attribs.get("longitude")
    latitude = float(lat) / 100000.0 if lat else None
    longitude = float(lon) / 100000.0 if lon else None

    cp = attribs.get("cp")
    pop = attribs.get("pop")
    adresse = station.findtext("adresse")
    ville = station.findtext("ville")

    for child in station:
        if child.tag == "prix":
            val = child.attrib.get("valeur")
            maj = child.attrib.get("maj")
            if not val or not maj:
                continue
            lignes_carbu.append({
                "id": attribs.get("id"),
                "latitude": latitude,
                "longitude": longitude,
                "cp": cp,
                "pop": pop,
                "adresse": adresse,
                "ville": ville,
                "carburant": child.attrib.get("nom"),
                "maj": maj,
                "valeur": float(val)
            })

df_carbu_brut = pd.DataFrame(lignes_carbu)
print(f"-> {len(df_carbu_brut):,} relevés extraits.")

print("2. Récupération du cours du Brent...")
ticker = yf.Ticker("BZ=F")
df_brent = ticker.history(period="1mo").reset_index()
df_brent = df_brent[["Date", "Close"]].rename(
    columns={"Date": "date", "Close": "brent_usd"}
)
df_brent["date"] = pd.to_datetime(df_brent["date"]).dt.date
df_brent["brent_usd"] = df_brent["brent_usd"].astype(float).round(2)
print(f"-> Dernier cours Brent : {df_brent.iloc[-1]['brent_usd']} $")


BUCKET_NAME = os.getenv("S3_BUCKET_NAME", "eco-essence-bordji")
AWS_REGION = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
s3 = boto3.client("s3", region_name=AWS_REGION)

def charger_parquet_s3(cle_s3: str) -> pd.DataFrame:
    buffer = io.BytesIO()
    s3.download_fileobj(BUCKET_NAME, cle_s3, buffer)
    buffer.seek(0)
    return pd.read_parquet(buffer)

def charger_modele_s3(cle_s3: str):
    buffer = io.BytesIO()
    s3.download_fileobj(BUCKET_NAME, cle_s3, buffer)
    buffer.seek(0)
    return joblib.load(buffer)

def sauvegarder_parquet_s3(df: pd.DataFrame, cle_s3: str):
    buffer = io.BytesIO()
    df.to_parquet(buffer, index=False, compression="zstd")
    buffer.seek(0)
    s3.upload_fileobj(buffer, BUCKET_NAME, cle_s3)

print("Chargement depuis S3")
df_feries = charger_parquet_s3("reference/jours_feriers_brut.parquet")
df_vacances = charger_parquet_s3("reference/vacances.parquet")
df_buffer = charger_parquet_s3("state/historique_recent_14j.parquet")
model = charger_modele_s3("modele/modele_lgbm_carburants.joblib")

print("Exécution du feature engineering avec DuckDB")
con = duckdb.connect()

con.register("carbu_brut_jour", df_carbu_brut)
con.register("historique_buffer", df_buffer)
con.register("brent_raw", df_brent)
con.register("jours_feriers_ref", df_feries)
con.register("vacances_ref", df_vacances)

con.execute("""
    CREATE OR REPLACE TABLE carbu_jour_unifie AS
    SELECT 
        id, carburant, CAST(maj AS DATE) AS date, valeur AS prix,
        latitude, longitude, cp, pop, ville, adresse
    FROM carbu_brut_jour
    WHERE valeur > 0.5 AND valeur < 3.5
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY id, carburant, CAST(maj AS DATE) 
        ORDER BY maj DESC
    ) = 1;

    CREATE OR REPLACE TABLE carbu_fusion AS
    SELECT * FROM historique_buffer
    UNION ALL
    SELECT * FROM carbu_jour_unifie;

    CREATE OR REPLACE TABLE brent_journalier AS
    WITH calendrier AS (
        SELECT CAST(range AS DATE) AS date
        FROM range(CURRENT_DATE - INTERVAL 20 DAY, CURRENT_DATE + INTERVAL 2 DAY, INTERVAL 1 DAY)
    ),
    brent_ffill AS (
        SELECT 
            c.date,
            LAST_VALUE(b.brent_usd IGNORE NULLS) OVER (
                ORDER BY c.date
                ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
            ) AS brent_j0
        FROM calendrier c
        LEFT JOIN brent_raw b ON c.date = CAST(b.date AS DATE)
    )
    SELECT 
        date,
        COALESCE(brent_j0, FIRST_VALUE(brent_j0 IGNORE NULLS) OVER (ORDER BY date)) AS brent_j0,
        LAG(brent_j0, 1) OVER (ORDER BY date) AS brent_j1,
        LAG(brent_j0, 3) OVER (ORDER BY date) AS brent_j3,
        LAG(brent_j0, 7) OVER (ORDER BY date) AS brent_j7
    FROM brent_ffill;

    CREATE OR REPLACE TABLE stations AS
    SELECT 
        id, carburant, latitude, longitude, cp, pop, ville, adresse,
        MIN(date) AS d_min, MAX(date) AS d_max
    FROM carbu_fusion
    GROUP BY id, carburant, latitude, longitude, cp, pop, ville, adresse;

    CREATE OR REPLACE TABLE calendrier_fenetre AS
    SELECT CAST(range AS DATE) AS date
    FROM range(CURRENT_DATE - INTERVAL 14 DAY, CURRENT_DATE + INTERVAL 1 DAY, INTERVAL 1 DAY);

    -- On force la grille à aller de d_min jusqu'au dernier jour du calendrier pour TOUTES les stations
    CREATE OR REPLACE TABLE grille_complete AS
    SELECT s.id, s.carburant, s.latitude, s.longitude, s.cp, s.pop, s.ville, s.adresse, c.date
    FROM stations s
    CROSS JOIN calendrier_fenetre c
    WHERE c.date >= s.d_min;

    CREATE OR REPLACE TABLE grille_ffill AS
    SELECT 
        g.id, g.carburant, g.date, g.latitude, g.longitude, g.cp, g.pop, g.ville, g.adresse,
        LAST_VALUE(u.prix IGNORE NULLS) OVER (
            PARTITION BY g.id, g.carburant 
            ORDER BY g.date 
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ) AS prix
    FROM grille_complete g
    LEFT JOIN carbu_fusion u 
        ON g.id = u.id AND g.carburant = u.carburant AND g.date = u.date;

    CREATE OR REPLACE TABLE dataset_inference AS
    WITH base_temporelle AS (
        SELECT 
            g.id, g.carburant, g.date, g.prix,
            LAG(g.prix, 1) OVER (PARTITION BY g.id, g.carburant ORDER BY g.date) AS prix_precedent,
            g.latitude, g.longitude, g.cp, g.pop, g.ville, g.adresse,
            b.brent_j0, b.brent_j1, b.brent_j3, b.brent_j7,
            CASE WHEN f.Jour IS NOT NULL THEN TRUE ELSE FALSE END AS est_ferie,
            LEAD(CASE WHEN f.Jour IS NOT NULL THEN TRUE ELSE FALSE END, 1) OVER (ORDER BY g.date) AS precede_ferie,
            LAG(CASE WHEN f.Jour IS NOT NULL THEN TRUE ELSE FALSE END, 1) OVER (ORDER BY g.date) AS succede_ferie,
            COALESCE(v.vacances_zone_a, FALSE) AS vacances_zone_a,
            COALESCE(v.vacances_zone_b, FALSE) AS vacances_zone_b,
            COALESCE(v.vacances_zone_c, FALSE) AS vacances_zone_c,
            SUBSTRING(LPAD(CAST(g.cp AS VARCHAR), 5, '0'), 1, 2) AS departement,
            (EXTRACT(ISODOW FROM g.date) - 1)::TINYINT AS jour_semaine,
            (b.brent_j0 - b.brent_j1)::FLOAT AS brent_diff_1j,
            (b.brent_j0 - b.brent_j7)::FLOAT AS brent_diff_7j,
            CASE WHEN g.prix != LAG(g.prix, 1) OVER (PARTITION BY g.id, g.carburant ORDER BY g.date) THEN 1 ELSE 0 END AS a_change
        FROM grille_ffill g
        LEFT JOIN brent_journalier b ON g.date = b.date
        LEFT JOIN jours_feriers_ref f ON g.date = CAST(f.Jour AS DATE)
        LEFT JOIN vacances_ref v ON g.date = CAST(v.date AS DATE)
        WHERE g.prix IS NOT NULL
    ),
    avec_groupes AS (
        SELECT 
            *,
            (prix_precedent - (brent_j0 * 0.01))::FLOAT AS ecart_prix_brent,
            SUM(a_change) OVER (
                PARTITION BY id, carburant 
                ORDER BY date 
                ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
            ) AS groupe_stab
        FROM base_temporelle
        WHERE prix_precedent IS NOT NULL
    )
    SELECT 
        id, carburant, date, prix AS prix_actuel, prix_precedent,
        latitude, longitude, cp, pop, ville, adresse,
        departement, jour_semaine,
        brent_j0, brent_j1, brent_j3, brent_j7,
        brent_diff_1j, brent_diff_7j, ecart_prix_brent,
        est_ferie, precede_ferie, succede_ferie,
        vacances_zone_a, vacances_zone_b, vacances_zone_c,
        (ROW_NUMBER() OVER (
            PARTITION BY id, carburant, groupe_stab 
            ORDER BY date
        ) - 1)::SMALLINT AS jours_au_meme_prix,
        (prix_precedent - AVG(prix_precedent) OVER (
            PARTITION BY date, departement, carburant
        ))::FLOAT AS ecart_concurrence,
        (prix_precedent - AVG(prix_precedent) OVER (
            PARTITION BY id, carburant 
            ORDER BY date 
            ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
        ))::FLOAT AS ecart_moy_7j
    FROM avec_groupes;
""")

df_inference = con.execute("""
    SELECT * FROM dataset_inference 
    WHERE date = (SELECT MAX(date) FROM dataset_inference)
""").df()


print(f"Calcul des prédictions sur {len(df_inference):,} lignes")
features_lgbm = [
    "prix_precedent",
    "brent_j0", "brent_diff_1j", "brent_diff_7j", "ecart_prix_brent",
    "jours_au_meme_prix",
    "ecart_concurrence",
    "ecart_moy_7j",
    "jour_semaine",
    "est_ferie", "precede_ferie", "succede_ferie",
    "vacances_zone_a", "vacances_zone_b", "vacances_zone_c",
    "departement", "carburant", "pop"
]

for col in ["carburant", "pop", "departement", "jour_semaine"]:
    df_inference[col] = df_inference[col].astype("category")

deltas_bruts = model.predict(df_inference[features_lgbm])

SEUIL_BAISSE = 0.0020
SEUIL_HAUSSE = 0.0008

deltas_finaux = np.where(
    deltas_bruts < -SEUIL_BAISSE, deltas_bruts,
    np.where(deltas_bruts > SEUIL_HAUSSE, deltas_bruts, 0.0)
)

df_inference["variation_predite_euros"] = deltas_finaux.round(4)
df_inference["prix_predit_demain"] = (df_inference["prix_actuel"] + deltas_finaux).round(3)
df_inference["tendance"] = np.where(
    deltas_finaux > SEUIL_HAUSSE, "Hausse",
    np.where(deltas_finaux < -SEUIL_BAISSE, "Baisse", "Stable")
)

colonnes_finales = [
    "id", "carburant", "date", "prix_actuel", "prix_predit_demain",
    "variation_predite_euros", "tendance", "latitude", "longitude",
    "cp", "ville", "adresse", "departement"
]
df_predictions = df_inference[colonnes_finales]

print("Upload des prédictions et actualisation du buffer sur S3")
date_str = datetime.date.today().isoformat()

sauvegarder_parquet_s3(df_predictions, "predictions/predictions_du_jour.parquet")
date_str = str(df_predictions["date"].max())
sauvegarder_parquet_s3(df_predictions, f"predictions/archive/predictions_{date_str}.parquet")

df_nouveau_buffer = con.execute("""
    SELECT 
        id, carburant, date, prix,
        latitude, longitude, cp, pop, ville, adresse
    FROM carbu_fusion
    WHERE date >= CURRENT_DATE - INTERVAL 14 DAY
""").df()

sauvegarder_parquet_s3(df_nouveau_buffer, "state/historique_recent_14j.parquet")

print("Pipeline exécutée avec succès")