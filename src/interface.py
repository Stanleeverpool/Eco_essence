import streamlit as st
import cost_calculation as cc
import re
from st_files_connection import FilesConnection

st.set_page_config(layout="wide")

conn = st.connection('s3', type=FilesConnection)

df = conn.read("s3://eco-essence-bordji/predictions/predictions_du_jour.parquet", input_format="parquet", ttl=600)
cpo = conn.read("s3://eco-essence-bordji/reference/code_coordonnees.parquet", input_format="parquet", ttl=600)

st.title("Eco Essence")
st.divider()
code_postal = st.text_input("Votre code postal", "69300")

rayon = st.slider("Dans quel rayon recherchez-vous ?",2,100)

carburant_selec = st.radio(
    "Votre carburant 🛢️:",
    ["E10","E85","SP98", "Gazole", "GPLc"])

st.divider()
data = cc.Calculations(code_postal,df,carburant_selec,cpo)
print(f"Carburant sélectionné : {carburant_selec}")
pattern = r"^\d{5}$"
if(bool(re.fullmatch(pattern, code_postal))):
    resultats =data.in_radius(rayon)

    st.dataframe(
    resultats,
    column_config={
        "maps": st.column_config.LinkColumn(
            "Itinéraire",
            display_text="Ouvrir dans Maps",
            pinned=True
        )
    },
    hide_index=True
)
    
