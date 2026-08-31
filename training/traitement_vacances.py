import pandas as pd
import duckdb
import xml.etree.ElementTree as ET
import json

#SOUS FORME 1990-01-01 │ false           │ false           │ false           │ NULL 
duckdb.sql("SELECT * FROM 'vacances.csv' WHERE date IS NULL OR vacances_zone_a IS NULL OR vacances_zone_b IS NULL OR vacances_zone_c IS NULL").show()
duckdb.sql("""
    COPY (
        SELECT 
            date,
            CAST(vacances_zone_a AS INT) AS vacances_zone_a,
            CAST(vacances_zone_b AS INT) AS vacances_zone_b,
            CAST(vacances_zone_c AS INT) AS vacances_zone_c
        FROM 'vacances.csv'
        WHERE date >= '2023-01-01'
    ) TO 'donnees_propres/vacances.parquet' (FORMAT PARQUET)
""")