import requests
import os


class Donnees_gouv :
    def __init__(self):
        headers = {"Content-Type": "application/json"}

        URL = "https://data.economie.gouv.fr/api/explore/v2.1/catalog/datasets/prix-des-carburants-en-france-flux-instantane-v2/records/?lang=fr&limit=10&offset=0"

        response = requests.get(URL, headers=headers).json()


