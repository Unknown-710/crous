# -*- coding: utf-8 -*-
"""
Surveillance de plusieurs recherches de logement Crous (Illkirch-Graffenstaden,
Strasbourg, etc.) et envoi d'un email dès qu'un logement apparaît sur l'une
des villes surveillées.

A lancer dans Spyder (ou en ligne de commande : python surveillance_crous.py)
"""

import re
import time
import smtplib
from email.mime.text import MIMEText
from datetime import datetime

import requests

# ============================================================
# CONFIGURATION - À MODIFIER AVANT DE LANCER LE SCRIPT
# ============================================================

# Liste des recherches à surveiller. Pour ajouter une ville :
# 1. Va sur https://trouverunlogement.lescrous.fr/, fais une recherche
# 2. Copie l'URL complète qui apparaît dans la barre d'adresse
# 3. Ajoute une entrée {"nom": "...", "url": "..."} ci-dessous
VILLES_SURVEILLEES = [
    {
        "nom": "Illkirch-Graffenstaden (67400)",
        "url": (
            "https://trouverunlogement.lescrous.fr/tools/47/search"
            "?bounds=7.6936786_48.5513899_7.7668133_48.4931752"
            "&locationName=Illkirch-Graffenstaden+%2867400%29"
        ),
    },
    {
        "nom": "Strasbourg",
        "url": (
            "https://trouverunlogement.lescrous.fr/tools/47/search"
            "?bounds=7.6881371_48.6461896_7.8360646_48.491861"
            "&locationName=Strasbourg"
        ),
    },
]

# Le site affiche toujours une phrase du type :
#   "Aucun logement trouvé pour ..."           -> 0 logement
#   "1 logement trouvé pour ..."                -> 1 logement
#   "2 logements trouvés pour ..."              -> 2 logements ou plus
#
# On utilise donc une regex qui capture le nombre devant "logement(s) trouvé(s)"
# pour ne pas confondre "Aucun logement trouvé" (0 résultat) avec un vrai résultat.
MOTIF_NB_LOGEMENTS = re.compile(r"(\d+)\s+logements?\s+trouvés?", re.IGNORECASE)

# Intervalle entre deux tours de vérification complets (en secondes).
# NB : sur Crous les logements partent parfois en quelques minutes.
# Plus l'intervalle est court, plus vite tu seras alerté, mais reste
# raisonnable (>= 30s) pour ne pas te faire bloquer par le site.
INTERVALLE_VERIFICATION = 60

# --- Paramètres d'envoi d'email (compte Gmail expéditeur) ---
EMAIL_EXPEDITEUR = "TON_ADRESSE_GMAIL@gmail.com"      # à remplir
MOT_DE_PASSE_APPLICATION = "xxxx xxxx xxxx xxxx"      # mot de passe d'application Gmail (voir explication plus bas)
EMAIL_DESTINATAIRE = "abuhassansami1@gmail.com"

SMTP_SERVEUR = "smtp.gmail.com"
SMTP_PORT = 587

# ============================================================
# FONCTIONS
# ============================================================

def obtenir_nombre_logements(session, url, nom_ville):
    """
    Récupère la page pour une ville donnée et retourne le nombre de
    logements trouvés (int). Retourne 0 si aucun logement, ou si la
    phrase n'est pas trouvée (dans ce cas on sauvegarde le HTML reçu
    pour debug).
    """
    reponse = session.get(url, timeout=20)
    reponse.raise_for_status()
    # Le serveur ne précise pas toujours correctement son charset dans les
    # en-têtes HTTP, ce qui fait que 'requests' décode parfois le texte en
    # Latin-1 au lieu d'UTF-8 (les accents deviennent "Ã©" au lieu de "é").
    # On force donc l'encodage UTF-8 pour être sûr.
    reponse.encoding = "utf-8"
    contenu = reponse.text

    correspondance = MOTIF_NB_LOGEMENTS.search(contenu)

    if correspondance:
        return int(correspondance.group(1))

    # Si on ne trouve ni "Aucun logement trouvé" ni "X logement(s) trouvé(s)",
    # soit le site a changé de structure, soit on a été bloqué / redirigé
    # (anti-bot, page "Vous êtes trop nombreux", session manquante, etc.)
    if "Aucun logement trouvé" not in contenu:
        print(f"[{datetime.now()}] ATTENTION [{nom_ville}] : impossible de déterminer le nombre de logements.")
        print(f"  -> Code HTTP reçu : {reponse.status_code}")
        print(f"  -> URL finale (après redirections éventuelles) : {reponse.url}")
        print(f"  -> Longueur du HTML reçu : {len(contenu)} caractères")

        correspondance_titre = re.search(r"<title[^>]*>(.*?)</title>", contenu, re.IGNORECASE | re.DOTALL)
        if correspondance_titre:
            print(f"  -> Titre de la page reçue : {correspondance_titre.group(1).strip()}")

        indices_blocage = [
            "trop nombreux", "captcha", "cloudflare", "just a moment",
            "access denied", "attention required", "vérification",
        ]
        contenu_minuscule = contenu.lower()
        trouves = [mot for mot in indices_blocage if mot in contenu_minuscule]
        if trouves:
            print(f"  -> Indices de blocage détectés dans la page : {trouves}")

        nom_fichier_debug = f"debug_page_{nom_ville}.html".replace(" ", "_").replace("/", "-")
        with open(nom_fichier_debug, "w", encoding="utf-8") as fichier:
            fichier.write(contenu)
        print(f"  -> HTML complet sauvegardé dans {nom_fichier_debug}\n")
    return 0


def creer_session():
    """
    Crée une session requests qui se comporte comme un vrai navigateur :
    - en-têtes complets (Accept, Accept-Language, Referer...)
    - visite préalable de la page d'accueil pour récupérer les cookies
      de session nécessaires (le site peut bloquer les requêtes sans
      cookies valides).
    """
    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0 Safari/537.36"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/webp,*/*;q=0.8"
        ),
        "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
        "Referer": "https://trouverunlogement.lescrous.fr/",
    })

    # Préchauffage : on visite la page d'accueil pour obtenir les cookies
    # de session avant de faire la vraie requête de recherche.
    try:
        session.get("https://trouverunlogement.lescrous.fr/", timeout=20)
    except requests.RequestException as erreur:
        print(f"[{datetime.now()}] Avertissement préchauffage cookies : {erreur}")

    return session


def envoyer_email(nom_ville, url, nombre_logements):
    """Envoie un email d'alerte à EMAIL_DESTINATAIRE pour une ville donnée."""
    sujet = f"🏠 {nombre_logements} logement(s) Crous trouvé(s) à {nom_ville} !"
    corps = (
        "Bonjour,\n\n"
        f"{nombre_logements} logement(s) semble(nt) maintenant disponible(s) "
        f"sur le site Crous pour {nom_ville}.\n\n"
        f"Lien : {url}\n\n"
        "Va vérifier rapidement, les places partent vite !\n"
    )

    message = MIMEText(corps, "plain", "utf-8")
    message["Subject"] = sujet
    message["From"] = EMAIL_EXPEDITEUR
    message["To"] = EMAIL_DESTINATAIRE

    with smtplib.SMTP(SMTP_SERVEUR, SMTP_PORT) as serveur:
        serveur.starttls()
        serveur.login(EMAIL_EXPEDITEUR, MOT_DE_PASSE_APPLICATION)
        serveur.send_message(message)

    print(f"[{datetime.now()}] Email envoyé avec succès pour {nom_ville}.")


def boucle_surveillance():
    """
    Boucle infinie de surveillance de toutes les villes de VILLES_SURVEILLEES.
    Envoie un email à chaque fois qu'un NOUVEAU logement apparaît sur une
    ville (le nombre de logements augmente par rapport à la vérification
    précédente pour cette ville), sans jamais s'arrêter, et sans renvoyer
    de mail en boucle si le même nombre reste affiché.
    """
    print(f"[{datetime.now()}] Démarrage de la surveillance...")
    for ville in VILLES_SURVEILLEES:
        print(f"  - {ville['nom']} : {ville['url']}")
    print(f"Vérification toutes les {INTERVALLE_VERIFICATION} secondes.\n")

    session = creer_session()
    # On garde en mémoire le dernier nombre connu de logements, par ville.
    derniers_nombres_connus = {ville["nom"]: 0 for ville in VILLES_SURVEILLEES}

    while True:
        for ville in VILLES_SURVEILLEES:
            nom_ville = ville["nom"]
            url = ville["url"]

            if url == "COLLE_ICI_URL_STRASBOURG":
                print(f"[{datetime.now()}] {nom_ville} ignorée : URL non configurée.")
                continue

            try:
                nombre_logements = obtenir_nombre_logements(session, url, nom_ville)

                if nombre_logements > derniers_nombres_connus[nom_ville]:
                    print(f"[{datetime.now()}] [{nom_ville}] {nombre_logements} logement(s) détecté(s) !")
                    envoyer_email(nom_ville, url, nombre_logements)
                elif nombre_logements > 0:
                    print(f"[{datetime.now()}] [{nom_ville}] {nombre_logements} logement(s) toujours affiché(s) (déjà signalé).")
                else:
                    print(f"[{datetime.now()}] [{nom_ville}] Toujours aucun logement disponible.")

                derniers_nombres_connus[nom_ville] = nombre_logements

            except requests.RequestException as erreur:
                print(f"[{datetime.now()}] [{nom_ville}] Erreur réseau : {erreur}")

        time.sleep(INTERVALLE_VERIFICATION)


# ============================================================
# POINT D'ENTRÉE
# ============================================================

if __name__ == "__main__":
    boucle_surveillance()
