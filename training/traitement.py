import pandas as pd
import duckdb
import xml.etree.ElementTree as ET
import json
from datetime import datetime


df_brent_raw = pd.read_excel('RBRTEd.xls', sheet_name='Data 1', skiprows=2)

# On renomme les deux colonnes pour que ce soit plus simple à manipuler
df_brent_raw.columns = ['date', 'brent_usd']

# 2. Requête DuckDB : le CAST(... AS DATE) retire les 00:00:00
duckdb.sql("""
COPY (
    SELECT 
        CAST(date AS DATE) AS date,
        CAST(brent_usd AS DOUBLE) AS brent_usd
    FROM df_brent_raw
    WHERE date >= '2022-01-01'
      AND brent_usd IS NOT NULL
      ) TO 'donnees_propres/brent.parquet' (FORMAT PARQUET)
""")

#####################################################################################################




