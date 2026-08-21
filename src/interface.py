import streamlit as st
import cost_calculation as cc
import re

st.title("Eco Essence")
st.divider()
code_postal = st.text_input("Votre code postal", "69300")

rayon = st.slider("Dans quel rayon recherchez-vous ?",1,100)
st.divider()
data = cc.Calculations(code_postal)
pattern = r"^\d{5}$"
if(bool(re.fullmatch(pattern, code_postal))):
    st.dataframe(data.in_radius(rayon))
