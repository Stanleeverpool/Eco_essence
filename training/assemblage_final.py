import duckdb

print("Déduplication des relevés")
duckdb.sql("""
    CREATE OR REPLACE TABLE carburants_unifies AS
    SELECT 
        id,
        carburant,
        CAST(maj AS DATE) AS date,
        valeur AS prix,
        latitude,
        longitude,
        cp,
        pop,
        ville,
        adresse
    FROM 'carburants_*_brut.parquet'
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY id, carburant, CAST(maj AS DATE) 
        ORDER BY maj DESC
    ) = 1;
""")

print("Construction de la série continue du brent")
duckdb.sql("""
    CREATE OR REPLACE TABLE brent_journalier AS
    WITH calendrier AS (
        SELECT CAST(range AS DATE) AS date
        FROM range(DATE '2022-01-01', DATE '2026-01-05', INTERVAL 1 DAY)
    ),
    brent_ffill AS (
        SELECT 
            c.date,
            LAST_VALUE(b.brent_usd IGNORE NULLS) OVER (
                ORDER BY c.date
                ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
            ) AS brent_j0
        FROM calendrier c
        LEFT JOIN 'brent.parquet' b ON c.date = CAST(b.date AS DATE)
    ),
    brent_full AS (
        SELECT 
            date,
            COALESCE(brent_j0, FIRST_VALUE(brent_j0 IGNORE NULLS) OVER (ORDER BY date)) AS brent_j0,
            LAG(brent_j0, 1) OVER (ORDER BY date) AS brent_j1,
            LAG(brent_j0, 3) OVER (ORDER BY date) AS brent_j3,
            LAG(brent_j0, 7) OVER (ORDER BY date) AS brent_j7
        FROM brent_ffill
    )
    SELECT * FROM brent_full WHERE date >= '2023-01-01';
""")

print(" jours fériés et vacances")
duckdb.sql("""
    CREATE OR REPLACE TABLE jours_feriers AS
    WITH calendrier AS (
        SELECT CAST(range AS DATE) AS date
        FROM range(DATE '2022-01-01', DATE '2026-01-05', INTERVAL 1 DAY)
    ),
    jours_ffill AS (
        SELECT 
            c.date,
            CASE WHEN b.Jour IS NOT NULL THEN TRUE ELSE FALSE END AS est_ferie
        FROM calendrier c
        LEFT JOIN 'jours_feriers_brut.parquet' b ON c.date = CAST(b.Jour AS DATE)
    ),
    jours_full AS (
        SELECT 
            date,
            est_ferie,
            LEAD(est_ferie, 1) OVER (ORDER BY date) AS precede_ferie,
            LAG(est_ferie, 1) OVER (ORDER BY date) AS succede_ferie
        FROM jours_ffill
    )
    SELECT * FROM jours_full WHERE date BETWEEN '2023-01-01' AND '2025-12-31';
""")

print("Grille spatio-temporelle continue et FE")
duckdb.sql("""
    CREATE OR REPLACE TABLE dataset_ml_enrichi AS
    WITH stations AS (
        SELECT 
            id, carburant, latitude, longitude, cp, pop, ville, adresse,
            MIN(date) AS d_min, 
            MAX(date) AS d_max
        FROM carburants_unifies
        GROUP BY id, carburant, latitude, longitude, cp, pop, ville, adresse
    ),
    calendrier AS (
        SELECT CAST(range AS DATE) AS date
        FROM range(DATE '2023-01-01', DATE '2026-01-01', INTERVAL 1 DAY)
    ),
    grille AS (
        SELECT s.*, c.date
        FROM stations s
        CROSS JOIN calendrier c
        WHERE c.date BETWEEN s.d_min AND s.d_max
    ),
    grille_avec_prix AS (
        SELECT 
            g.id, g.carburant, g.date, g.latitude, g.longitude, g.cp, g.pop, g.ville, g.adresse,
            u.prix AS prix_observe
        FROM grille g
        LEFT JOIN carburants_unifies u 
            ON g.id = u.id AND g.carburant = u.carburant AND g.date = u.date
    ),
    grille_ffill AS (
        SELECT 
            id, carburant, date, latitude, longitude, cp, pop, ville, adresse,
            LAST_VALUE(prix_observe IGNORE NULLS) OVER (
                PARTITION BY id, carburant 
                ORDER BY date 
                ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
            ) AS prix
        FROM grille_avec_prix
    ),
    base_temporelle AS (
        SELECT 
            g.id,
            g.carburant,
            g.date,
            g.prix,
            LAG(g.prix, 1) OVER (PARTITION BY g.id, g.carburant ORDER BY g.date) AS prix_precedent,
            g.latitude,
            g.longitude,
            g.cp,
            g.pop,
            g.ville,
            g.adresse,
            b.brent_j0, b.brent_j1, b.brent_j3, b.brent_j7,
            f.est_ferie, f.precede_ferie, f.succede_ferie,
            v.vacances_zone_a, v.vacances_zone_b, v.vacances_zone_c,
            -- Département et jour de la semaine (0 = Lundi, 6 = Dimanche)
            SUBSTRING(LPAD(CAST(g.cp AS VARCHAR), 5, '0'), 1, 2) AS departement,
            (EXTRACT(ISODOW FROM g.date) - 1)::TINYINT AS jour_semaine,
            -- Dynamique Brent
            (b.brent_j0 - b.brent_j1)::FLOAT AS brent_diff_1j,
            (b.brent_j0 - b.brent_j7)::FLOAT AS brent_diff_7j,
            -- Détection du changement d'état
            CASE WHEN g.prix != LAG(g.prix, 1) OVER (PARTITION BY g.id, g.carburant ORDER BY g.date) THEN 1 ELSE 0 END AS a_change
        FROM grille_ffill g
        LEFT JOIN brent_journalier b ON g.date = b.date
        LEFT JOIN jours_feriers f ON g.date = f.date
        LEFT JOIN (SELECT * FROM 'vacances.parquet' WHERE date BETWEEN '2023-01-01' AND '2025-12-31') v ON g.date = v.date
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
    ),
    features_finales AS (
        SELECT 
            id, carburant, date, prix, prix_precedent,
            latitude, longitude, cp, pop, ville, adresse,
            departement, jour_semaine,
            brent_j0, brent_j1, brent_j3, brent_j7,
            brent_diff_1j, brent_diff_7j, ecart_prix_brent,
            est_ferie, precede_ferie, succede_ferie,
            vacances_zone_a, vacances_zone_b, vacances_zone_c,
            
            -- Inertie locale (jours au même prix)
            (ROW_NUMBER() OVER (
                PARTITION BY id, carburant, groupe_stab 
                ORDER BY date
            ) - 1)::SMALLINT AS jours_au_meme_prix,
            
            -- Écart à la moyenne départementale
            (prix_precedent - AVG(prix_precedent) OVER (
                PARTITION BY date, departement, carburant
            ))::FLOAT AS ecart_concurrence,
            
            -- Écart à la moyenne mobile glissante 7j
            (prix_precedent - AVG(prix_precedent) OVER (
                PARTITION BY id, carburant 
                ORDER BY date 
                ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
            ))::FLOAT AS ecart_moy_7j
        FROM avec_groupes
    )
    SELECT * FROM features_finales;
""")

print("Exportation des fichiers parquet")
duckdb.sql("""
    COPY (
        SELECT * FROM dataset_ml_enrichi 
        WHERE date BETWEEN '2023-01-01' AND '2024-12-31'
    ) TO 'train_2023_2024_final.parquet' (FORMAT PARQUET, COMPRESSION ZSTD);
""")

duckdb.sql("""
    COPY (
        SELECT * FROM dataset_ml_enrichi
        WHERE date >= '2025-01-01'
    ) TO 'val_2025_final.parquet' (FORMAT PARQUET, COMPRESSION ZSTD);
""")

print("Assemblage et calculs terminés avec succès !")