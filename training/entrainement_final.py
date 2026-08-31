from sklearn.metrics import mean_absolute_error, confusion_matrix, classification_report
import duckdb
import pandas as pd
import lightgbm as lgb
import numpy as np
import joblib


#BASELINE
duckdb.sql("""
    SELECT 
        AVG(ABS(prix - prix_precedent)) AS mae_euros,
        AVG(ABS(prix - prix_precedent)) * 100 AS mae_centimes
    FROM 'val_2025.parquet'
""").show()

#On charge les tables

print("Chargement des tables Parquet...")
train = pd.read_parquet("train_2023_2024_final.parquet")
valide = pd.read_parquet("val_2025_final.parquet")

features = [
    'prix_precedent',
    'brent_j0', 'brent_diff_1j', 'brent_diff_7j', 'ecart_prix_brent',
    'jours_au_meme_prix',
    'ecart_concurrence',
    'ecart_moy_7j',
    'jour_semaine',
    'est_ferie', 'precede_ferie', 'succede_ferie',
    'vacances_zone_a', 'vacances_zone_b', 'vacances_zone_c',
    'departement', 'carburant', 'pop'
]

categorielle_cols = ['carburant', 'pop', 'departement', 'jour_semaine']
for col in categorielle_cols:
    train[col] = train[col].astype('category')
    valide[col] = valide[col].astype('category')

X_train = train[features]
y_train = (train['prix'] - train['prix_precedent']).astype(np.float32)

X_val = valide[features]
y_val = valide['prix']
prix_prec_val = valide['prix_precedent'].values

# LIGHTGBM AVEC PONDÉRATION DES HAUSSES
model = lgb.LGBMRegressor(
    objective='regression',
    n_estimators=131,
    learning_rate=0.03,
    num_leaves=63,
    min_child_samples=50,
    colsample_bytree=0.8,
    random_state=42,
    n_jobs=-1
)

poids_train = np.where(y_train > 0.002, 1.4, 1.0)

print("Entraînement LightGBM en cours...")
model.fit(
    X_train, 
    y_train, 
    sample_weight=poids_train, 
    categorical_feature=categorielle_cols
)

delta_pred = model.predict(X_val)


#On applique directement le seuil optimal (-0.20 ct / +0.08 ct)

opti_baisse_euro = 0.0020   # -0.20 ct
opti_hausse_euro = 0.0008   # +0.08 ct

delta_pred_opti = np.where(
    delta_pred < -opti_baisse_euro, delta_pred,
    np.where(delta_pred > opti_hausse_euro, delta_pred, 0.0)
)
prix_pred_opti = prix_prec_val + delta_pred_opti
mae_finale = mean_absolute_error(y_val, prix_pred_opti)

print("\n" + "="*55)
print(f"   RÉSULTATS FINAUX (Baisse: -{opti_baisse_euro*100:.2f} cts | Hausse: +{opti_hausse_euro*100:.2f} cts)")
print("="*55)
print(f"MAE du modèle : {mae_finale * 100:.4f} centimes ({mae_finale:.4f} €/L)")

# PERFORMANCE

delta_reel = (y_val.values - prix_prec_val)

print("\n" + "="*55)
print("   PERFORMANCE SUR LES MOUVEMENTS SIGNIFICATIFS")
print("="*55)

for seuil_var in [0.005, 0.010, 0.020]:
    mask = np.abs(delta_reel) >= seuil_var
    nb_cas = np.sum(mask)
    pct_cas = (nb_cas / len(delta_reel)) * 100

    mae_base_segment = mean_absolute_error(y_val[mask], valide.loc[mask, 'prix_precedent'])
    mae_mod_segment = mean_absolute_error(y_val[mask], prix_pred_opti[mask])
    gain_pct = ((mae_base_segment - mae_mod_segment) / mae_base_segment) * 100

    pred_bouge = delta_pred_opti[mask] != 0
    meme_sens = np.sign(delta_pred_opti[mask][pred_bouge]) == np.sign(delta_reel[mask][pred_bouge])
    taux_bonne_direction = np.mean(meme_sens) * 100 if np.sum(pred_bouge) > 0 else 0
    taux_detection = (np.sum(pred_bouge) / nb_cas) * 100

    print(f"\nVariations réelles >= {seuil_var*100:.1f} cts ({nb_cas:,} cas, soit {pct_cas:.1f} % du jeu) :")
    print(f"  • MAE Baseline (naïve) : {mae_base_segment * 100:.4f} cts")
    print(f"  • MAE Modèle LightGBM : {mae_mod_segment * 100:.4f} cts (Gain : -{gain_pct:.1f} % d'erreur)")
    print(f"  • Taux de détection    : {taux_detection:.1f} % des mouvements détectés")
    print(f"  • Bonne direction      : {taux_bonne_direction:.1f} % de bon sens (hausse/baisse)")

# MATRICE DE CONFUSION & RAPPORT DE CLASSIFICATION

classes_reelles = np.where(delta_reel > 0.002, "Hausse", np.where(delta_reel < -0.002, "Baisse", "Stable"))
classes_predites_opti = np.where(
    delta_pred_opti > opti_hausse_euro, "Hausse",
    np.where(delta_pred_opti < -opti_baisse_euro, "Baisse", "Stable")
)
labels = ["Baisse", "Stable", "Hausse"]

cm_brute = confusion_matrix(classes_reelles, classes_predites_opti, labels=labels)
df_cm_brute = pd.DataFrame(cm_brute, index=[f"Réel {l}" for l in labels], columns=[f"Prédit {l}" for l in labels])

cm_pct = (cm_brute / cm_brute.sum(axis=1, keepdims=True)) * 100
df_cm_pct = pd.DataFrame(cm_pct, index=[f"Réel {l}" for l in labels], columns=[f"Prédit {l}" for l in labels])

print("\n" + "="*55)
print("   MATRICE DE CONFUSION (Volumes réels)")
print("="*55)
print(df_cm_brute.map(lambda x: f"{x:,}"))

print("\n" + "="*55)
print("   MATRICE DE CONFUSION (Normalisée en % par ligne)")
print("="*55)
print(df_cm_pct.map(lambda x: f"{x:6.2f} %"))

print("\n" + "="*55)
print("   RAPPORT DE CLASSIFICATION")
print("="*55)
print(classification_report(classes_reelles, classes_predites_opti, labels=labels, digits=4))

joblib.dump(model, 'modele_lgbm_carburants.joblib')