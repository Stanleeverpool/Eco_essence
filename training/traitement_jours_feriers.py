import pandas as pd
import duckdb
import xml.etree.ElementTree as ET
import json

#Liste avec : {2031-01-01=1er janvier, ...}
#A transformer en une liste de jours 
with open("jours_feriers.json", "r") as f:
    data = json.load(f)
    liste = []
    for jour in data :
        liste.append(jour)
    pliste = pd.DataFrame(liste, columns=['Jour'])
    duckdb.sql("COPY (SELECT * FROM pliste) TO 'jours_feriers_brut.parquet' (FORMAT PARQUET)")
duckdb.sql('SELECT * FROM jours_feriers_brut.parquet').show()
