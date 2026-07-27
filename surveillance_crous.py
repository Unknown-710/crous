# -*- coding: utf-8 -*-
"""
Surveillance de la page de recherche de logement Crous.

Version "one-shot" : ce script fait UNE seule vérification puis s'arrête.
Il est conçu pour être exécuté périodiquement par un planificateur externe
(GitHub Actions), et non plus dans une boucle infinie locale.

Les identifiants ne sont plus écrits en dur dans le code : ils sont lus
depuis des variables d'environnement (voir le workflow GitHub Actions
associé, qui les injecte à partir des "Secrets" du dépôt).
"""

import os
import re
import smtplib
import sys
from email.mime.text import MIMEText
from datetime import datetime

import requests

# ============================================================
# CONFIGURATION
# ============================================================

URL = (
    "https://trouverunlogement.lescrous.fr/tools/47/search"
    "?bounds=7.6936786_48.5513899_7.7668133_48.4931752"
    "&locationName=Illkirch-Graffenstaden+%2867400%29"
)

MOTIF_NB_LOGEMENTS = re.compile(r"(\d+)\s+logements?\s+trouvés?", re.IGNORECASE)

# --- Identifiants lus depuis les variables d'environnement ---
# (définies comme "Secrets" dans les paramètres du dépôt GitHub)
EMAIL_EXPEDITEUR = os.environ.get("GMAIL_EXPEDITEUR")
MOT_DE_PASSE_APPLICATION = os.environ.get("GMAIL_MOT_DE_PASSE_APPLICATION")
EMAIL_DESTINATAIRE = os.environ.get("GMAIL_DESTINATAIRE")

SMTP_SERVEUR = "smtp.gmail.com"
SMTP_PORT = 587

# ============================================================
# FONCTIONS
# ============================================================


def obtenir_nombre_logements(session):
    """
    Récupère la page et retourne le nombre de logements trouvés (int).
    Retourne 0 si aucun logement, ou si la phrase n'est pas trouvée
    (dans ce cas on sauvegarde le HTML reçu pour debug).
    """
    reponse = session.get(URL, timeout=20)
    reponse.raise_for_status()
    reponse.encoding = "utf-8"
    contenu = reponse.text

    correspondance = MOTIF_NB_LOGEMENTS.search(contenu)

    if correspondance:
        return int(correspondance.group(1))

    if "Aucun logement trouvé" not in contenu:
        print(f"[{datetime.now()}] ATTENTION : impossible de déterminer le nombre de logements.")
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

        with open("debug_page.html", "w", encoding="utf-8") as fichier:
            fichier.write(contenu)
        print("  -> HTML complet sauvegardé dans debug_page.html\n")
    return 0


def creer_session():
    """Crée une session requests qui se comporte comme un vrai navigateur."""
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

    try:
        session.get("https://trouverunlogement.lescrous.fr/", timeout=20)
    except requests.RequestException as erreur:
        print(f"[{datetime.now()}] Avertissement préchauffage cookies : {erreur}")

    return session


def envoyer_email(nombre_logements):
    """Envoie un email d'alerte à EMAIL_DESTINATAIRE."""
    if not all([EMAIL_EXPEDITEUR, MOT_DE_PASSE_APPLICATION, EMAIL_DESTINATAIRE]):
        print(f"[{datetime.now()}] ERREUR : identifiants email manquants "
              "(variables d'environnement GMAIL_* non définies).")
        sys.exit(1)

    sujet = f"🏠 {nombre_logements} logement(s) Crous trouvé(s) à Illkirch-Graffenstaden !"
    corps = (
        "Bonjour,\n\n"
        f"{nombre_logements} logement(s) semble(nt) maintenant disponible(s) "
        "sur le site Crous pour Illkirch-Graffenstaden (67400).\n\n"
        f"Lien : {URL}\n\n"
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

    print(f"[{datetime.now()}] Email envoyé avec succès.")


def verification_unique():
    """Effectue UNE vérification puis se termine (pas de boucle)."""
    print(f"[{datetime.now()}] Vérification en cours...")
    print(f"URL surveillée : {URL}")

    session = creer_session()

    try:
        nombre_logements = obtenir_nombre_logements(session)

        if nombre_logements > 0:
            print(f"[{datetime.now()}] {nombre_logements} logement(s) détecté(s) !")
            envoyer_email(nombre_logements)
        else:
            print(f"[{datetime.now()}] Toujours aucun logement disponible.")

    except requests.RequestException as erreur:
        print(f"[{datetime.now()}] Erreur réseau : {erreur}")
        sys.exit(1)


# ============================================================
# POINT D'ENTRÉE
# ============================================================

if __name__ == "__main__":
    verification_unique()
