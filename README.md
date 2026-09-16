# ⛽ Eco Essence — Prédiction & comparateur des prix des carburants

## Concept 

Ce projet est un outil d'aide à la décision pour les automobilistes,\
sa particularité est de proposer en même temps une **prédiction à J+1** des prix pour chaque station ainsi qu'une **tendance**.

### ⚡ En quelques chiffres

* **11,95 millions** d'observations évaluées en conditions réelles sur l'année de test 2025
* **-10,1 % d'erreur absolue** par rapport à la baseline naïve (MAE réduite de 0,3273 à 0,2944 ct/L)
* **96,3 % de stabilité préservée** : filtrage quasi total du bruit quotidien (< 3,8 % de fausses alertes sur jours stables)
* **> 55 % des variations détectées** à $J+1$ (rappel de 56,7 % sur les baisses et 54,8 % sur les hausses)
* **Règle de décision asymétrique** calibrée sur le comportement des distributeurs (-0,20 ct / +0,08 ct)

## 🛠️ Architecture & Environnement technique

* **Stockage Cloud :** Stockage au format parquet sur **AWS S3** avec archivage
* **Analyse & Géospatial :** Requêtage **SQL** via **DuckDB** et son extension **Spatial** 
* **Pipeline automatisé :** Workflow **GitHub Actions** planifié chaque matin à 6h30 (appels aux API, enrichissement, LightGBM et synchronisation vers AWS S3).
* **Interface utilisateur :** Application web avec **Streamlit** (recherche par code postal/rayon, filtres carburants et itinéraires Google Maps).


## 🧠 Modélisation et Machine Learning

### Préambule
Plutôt que de prédire un prix absolu (fortement corrélé au prix de la veille et sujet à des dérives de tendance), le modèle prédit la **variation journalière** 

---

### Validation
Après nettoyage : 
* **Entraînement :** Historique complet 2023 - 2024 (`train_2023_2024_final.parquet`)
* **Test / Validation :** Année 2025 (`val_2025_final.parquet`)

---

### 3. Feature engineering
Le modèle s'appuie sur 18 variables :

* **Marché mondial du pétrole :** Cours du Brent à $J$, variations à $J-1$ et $J-7$, et spread station/Brent (`ecart_prix_brent`).
* **Concurrence & Micro-marché :** Écart de prix moyen avec les stations concurrentes du secteur (`ecart_concurrence`) et écart à la moyenne glissante sur 7 jours.
* **Historique de la station :** Nombre de jours consécutifs au même prix (`jours_au_meme_prix`).
* **Saisonnalité & Calendrier :** Jour de la semaine, statut des jours fériés (le jour même, veille, lendemain) et vacances scolaires 
* **Catégories :** Implantation (`autoroute vs réseau secondaire), département et type de carburant.

---

### 4. Algorithme & Optimisation métier

* **Moteur :** `LightGBM` (`n_estimators=131`, `learning_rate=0.03`, `num_leaves=63`) avec le n_estimators trouvé pour minimiser le MAE.
* **Fonction de coût orientée usage :** Du point de vue utilisateur, rater une hausse est plus pénalisant que manquer une légère baisse. Une **surpondération des hausses** (`sample_weight = 1.4` pour toute variation $> +0,002$ €) a été intégrée à l'entraînement pour pousser le modèle à détecter en priorité les renchérissements de prix.

---

### 5. Post-traitement : Seuillage asymétrique
Le marché des carburants étant caractérisé par une forte inertie (prix inchangés la plupart des jours), un filtre asymétrique neutralise le bruit :

$$
\Delta_{\text{retenu}} = 
\begin{cases} 
\Delta_{\text{prédit}} & \text{si } \Delta_{\text{prédit}} < -0,20\text{ ct} \quad (\text{signal de baisse}) \\
\Delta_{\text{prédit}} & \text{si } \Delta_{\text{prédit}} > +0,08\text{ ct} \quad (\text{signal de hausse}) \\
0,0 & \text{sinon } (\text{station considérée stable})
\end{cases}
$$

---

### 6. Évaluation des performances
Le modèle est évalué par rapport à une **baseline naïve** (Prix(t) = Prix(t-1)) sur plusieurs axes et par rapport à un autre moteur :

| Approche | MAE (centimes €/L) | Gain vs baseline | Rappel hausse | Rappel baisse | Faux signaux |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Baseline naïve** | 0,3273 | — | 0,0 % | 0,0 % | 0,0 % |
| **Hurdle model** | 0,3813 | -16,5 %  | 49,8 % | 82,9 % | 2,1 % |
| **LightGBM optimisé** | **0,2944** | **+10,1 %** | **54,8 %** | **56,7 %** | **3,7 %** |

#### Matrice de confusion normalisée (test 2025 en % par ligne)

| Réel \ Prédit | Prédit Baisse | Prédit Stable | Prédit Hausse |
| :--- | :---: | :---: | :---: |
| **Réel Baisse** | **56,72 %** | 19,18 % | 24,11 % |
| **Réel Stable** | 1,04 % | **96,28 %** | 2,68 % |
| **Réel Hausse** | 27,12 % | 18,05 % | **54,83 %** |

Sachant que la grande majorité du temps les prix sont stables ces résultats sont tout à fait satisfaisants.
Une tentative d'introduire d'autres variables comme le cours de l'euro/dollar a été testé mais au final écarté\
car elle apportait plus de bruit et donc des résultats moins intéressants.

Une autre donnée intéressante à inférer serait le nom du revendeur (non données via l'API gouvernementale pour \
des raisons évidentes) afin de réentrainer le modèle avec cette feature ainsi que d'ajuster les prédictions au \
cas par cas (exemple : Total et le blocage des prix à 1.99).


## Jeux de données 

https://www.prix-carburants.gouv.fr/rubrique/opendata/

https://www.eia.gov/dnav/pet/hist/rbrted.htm 

https://pypi.org/project/yfinance/

https://www.data.gouv.fr/datasets/vacances-scolaires-par-zones

https://calendrier.api.gouv.fr/jours-feries/metropole.json

## Pragmatisme
