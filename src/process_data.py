import duckdb

#De CSV à parquet
#duckdb.sql("SELECT * FROM '../data/20230823-communes-departement-region.csv'").write_parquet("../data/code_coordonnees.parquet")

# Nettoyage
#duckdb.sql("""
#    COPY (
#        SELECT 
#            nom_commune_postal,code_postal,latitude,longitude
#        FROM '../data/code_coordonnees.parquet'
#    ) 
#    TO '../data/code_coordonnees.parquet' (FORMAT PARQUET);
#""")

# Charger la relation
donnees = duckdb.read_parquet("../data/code_coordonnees.parquet")

# Requêter la variable Python 'donnees' comme une table SQL
duckdb.sql("""
    SELECT *
    FROM donnees 
""").show()