import pandas as pd
import duckdb
import xml.etree.ElementTree as ET
#####################################################################################################
#On prend une même structure de dataframe et on la duplique pour chaque prix
carbu = ET.parse('PrixCarburants_annuel_2025.xml')
root_carbu = carbu.getroot()

lignes = []
#à chaque prix
#Je créer une copie de l'attribue de la root
#Je concatène adresse,ville et tout ce qu'il y a dans le prix
#j'append à lignes
for station in root_carbu :

    if station.attrib.get('latitude') != None :
        if station.attrib.get('latitude') == '' :
            station.attrib['latitude'] = None
        else:
            station.attrib['latitude'] = float(station.attrib.get('latitude'))/100000
    
    if station.attrib.get('longitude') != None :
        if station.attrib.get('longitude') == '' :
            station.attrib['longitude'] = None
        else:
            station.attrib['longitude'] = float(station.attrib.get('longitude'))/100000

    adresse = station.findtext('adresse')
    ville = station.findtext('ville')
    for child in station :
        if child.tag =="prix" :
            valeur_str = child.attrib.get('valeur')
            if not valeur_str:
                continue
            ligne_complete = station.attrib | {'ville':ville} | {'adresse':adresse} | {'carburant' :child.attrib.get('nom')} | {'maj' :child.attrib.get('maj')}| {'valeur' : float(valeur_str)}
            lignes.append(ligne_complete)

dataf = pd.DataFrame(lignes)
duckdb.sql("COPY (SELECT * FROM dataf) TO 'carburants_2025_brut.parquet' (FORMAT PARQUET)")
duckdb.sql('SELECT * FROM carburants_2025_brut.parquet').show()
    


