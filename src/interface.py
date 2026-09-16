import streamlit as st
import cost_calculation as cc
import re
from st_files_connection import FilesConnection

conn = st.connection('s3', type=FilesConnection)
df = conn.read("s3://eco-essence-bordji/predictions/predictions_du_jour.parquet", input_format="parquet", ttl=600)

st.title("Eco Essence")
st.divider()
code_postal = st.text_input("Votre code postal", "69300")

rayon = st.slider("Dans quel rayon recherchez-vous ?",2,100)

st.divider()
data = cc.Calculations(code_postal,df)
pattern = r"^\d{5}$"
if(bool(re.fullmatch(pattern, code_postal))):
    st.dataframe(data.in_radius(rayon))
    
