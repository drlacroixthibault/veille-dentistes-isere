#!/usr/bin/env python3
"""
Veille des chirurgiens-dentistes en Isère (38).

Source : Annuaire Santé de l'ANS (données RPPS transmises par l'Ordre des
chirurgiens-dentistes), en libre accès sur data.gouv.fr, Licence Ouverte 2.0.

À chaque passage :
  1. télécharge le fichier « PS_LibreAcces_Personne_activite » (flux, sans tout stocker) ;
  2. garde uniquement les chirurgiens-dentistes (code profession 40), France entière ;
  3. compare avec la photo précédente pour repérer arrivées, départs et
     changements de commune en Isère, et d'où viennent / où vont les confrères ;
  4. écrit les fichiers lus par la page web (docs/data/).

Usage :
  python veille.py                 # télécharge la source officielle
  python veille.py --source f.txt  # utilise un fichier local (test)
  python veille.py --date 2026-11-02
"""
import argparse
import math
import csv
import datetime as dt
import gzip
import io
import json
import os
import sys
import time
import unicodedata
import urllib.parse
import urllib.request

SOURCE_URL = "https://www.data.gouv.fr/api/1/datasets/r/fffda7e9-0ea2-4c35-bba0-4496f3af935d"
DEPARTEMENT = "38"
CODE_PROFESSION = "40"  # chirurgien-dentiste
# Zone suivie : tout l'Isère + tout cabinet à moins de RAYON_KM de Grenoble (Savoie, Drôme…)
GRENOBLE = (45.1885, 5.7245)
RAYON_KM = 50
DEPS_VOISINS = {"73", "26"}  # départements géocodés pour trouver les cabinets à moins de 50 km

ROOT = os.path.dirname(os.path.abspath(__file__))
SNAPSHOT = os.path.join(ROOT, "data", "photo_nationale.json.gz")
OUT_DIR = os.path.join(ROOT, "docs", "data")
ALERTE = os.path.join(ROOT, "nouveaux_mouvements.md")
GEOCACHE = os.path.join(ROOT, "data", "geocache.json")
# Géocodage : API de la Géoplateforme IGN (ex-API Adresse de la BAN), gratuite, sans clé
GEO_URL = "https://data.geopf.fr/geocodage/search"

csv.field_size_limit(10_000_000)


# ---------------------------------------------------------------- utilitaires
def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return " ".join(s.lower().replace("﻿", "").split())


class Colonnes:
    """Retrouve les colonnes par leur nom, même si l'ordre change."""

    def __init__(self, entete):
        self.h = [norm(c) for c in entete]

    def idx(self, *candidats, obligatoire=True):
        for cand in candidats:
            c = norm(cand)
            for i, h in enumerate(self.h):
                if h == c:
                    return i
            for i, h in enumerate(self.h):
                if h.startswith(c):
                    return i
        if obligatoire:
            raise SystemExit(f"Colonne introuvable : {candidats}\nEn-tête : {self.h}")
        return None


def ouvrir_source(source):
    if source and os.path.exists(source):
        return open(source, encoding="utf-8-sig", errors="replace", newline="")
    url = source or SOURCE_URL
    for essai in range(4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "veille-dentistes-isere/1.0"})
            resp = urllib.request.urlopen(req, timeout=120)
            return io.TextIOWrapper(resp, encoding="utf-8-sig", errors="replace", newline="")
        except Exception as e:  # réseau capricieux : on réessaie
            print(f"Téléchargement échoué ({e}), nouvel essai…", file=sys.stderr)
            time.sleep(30 * (essai + 1))
    raise SystemExit("Impossible de télécharger la source.")


PETITS_MOTS = {"en", "de", "du", "des", "la", "le", "les", "sur", "sous", "et", "aux", "au", "d", "l"}


def titre(s):
    """GRENOBLE -> Grenoble, LANS-EN-VERCORS -> Lans-en-Vercors."""
    s = (s or "").strip()
    if not s.isupper():
        return s
    out, mot, debut = [], "", True
    for ch in s.lower() + " ":
        if ch.isalpha():
            mot += ch
            continue
        if mot:
            out.append(mot if (mot in PETITS_MOTS and not debut) else mot.capitalize())
            mot, debut = "", False
        out.append(ch)
    return "".join(out).rstrip()


# ------------------------------------------------------------------- lecture
def lire_dentistes(source):
    f = ouvrir_source(source)
    lecteur = csv.reader(f, delimiter="|", quoting=csv.QUOTE_NONE)
    col = Colonnes(next(lecteur))
    I = dict(
        rpps=col.idx("Identifiant PP"),
        prof=col.idx("Code profession"),
        civ=col.idx("Libellé civilité d'exercice", obligatoire=False),
        nom=col.idx("Nom d'exercice"),
        prenom=col.idx("Prénom d'exercice"),
        sf=col.idx("Libellé savoir-faire", obligatoire=False),
        mode=col.idx("Libellé mode exercice", obligatoire=False),
        rs=col.idx("Raison sociale site", obligatoire=False),
        enseigne=col.idx("Enseigne commerciale site", obligatoire=False),
        num=col.idx("Numéro Voie (coord. structure)", obligatoire=False),
        ind=col.idx("Indice répétition voie (coord. structure)", obligatoire=False),
        tvoie=col.idx("Libellé type de voie (coord. structure)", obligatoire=False),
        voie=col.idx("Libellé Voie (coord. structure)", obligatoire=False),
        cp=col.idx("Code postal (coord. structure)"),
        ville=col.idx("Libellé commune (coord. structure)"),
        tel=col.idx("Téléphone (coord. structure)", obligatoire=False),
        mail=col.idx("Adresse e-mail (coord. structure)", obligatoire=False),
        dep=col.idx("Code Département (structure)", obligatoire=False),
    )
    n = max(v for v in I.values() if v is not None) + 1

    def g(r, k):
        i = I[k]
        return r[i].strip() if i is not None and i < len(r) else ""

    pros = {}
    for r in lecteur:
        if len(r) < n or r[I["prof"]].strip() != CODE_PROFESSION:
            continue
        rpps = g(r, "rpps")
        if not rpps:
            continue
        p = pros.setdefault(rpps, {
            "civ": g(r, "civ"), "nom": titre(g(r, "nom")), "prenom": titre(g(r, "prenom")),
            "sf": [], "sites": [],
        })
        sf = g(r, "sf")
        if sf and sf not in p["sf"]:
            p["sf"].append(sf)
        cp, ville = g(r, "cp"), titre(g(r, "ville"))
        if not (cp or ville):
            continue
        adr = titre(" ".join(x for x in (g(r, "num"), g(r, "ind"), g(r, "tvoie").upper(), g(r, "voie").upper()) if x))
        dep = g(r, "dep") or (cp[:2] if cp[:2] not in ("97", "98") else cp[:3])
        site = {
            "cp": cp, "ville": ville, "dep": dep, "adr": adr,
            "cabinet": titre(g(r, "enseigne") or g(r, "rs")),
            "mode": g(r, "mode"), "tel": g(r, "tel"), "mail": g(r, "mail"),
        }
        cle = (cp, ville.lower(), adr.lower())
        if all((s["cp"], s["ville"].lower(), s["adr"].lower()) != cle for s in p["sites"]):
            p["sites"].append(site)
    f.close()
    return pros


# ---------------------------------------------------------------- géocodage
class Geocodeur:
    """Adresse -> (lat, lon), avec cache pour ne géocoder chaque adresse qu'une fois."""

    def __init__(self, actif=True):
        self.actif = actif
        self.cache = lire_json(GEOCACHE, {})
        self.appels = 0

    def _requete(self, params):
        url = GEO_URL + "?" + urllib.parse.urlencode({**params, "limit": 1})
        for essai in range(3):
            try:
                with urllib.request.urlopen(url, timeout=20) as r:
                    feats = json.load(r).get("features") or []
                self.appels += 1
                time.sleep(0.03)  # rester sous la limite de 50 requêtes / seconde
                if feats:
                    lon, lat = feats[0]["geometry"]["coordinates"]
                    return round(lat, 5), round(lon, 5), feats[0]["properties"].get("score", 0)
                return None
            except Exception:
                time.sleep(2 * (essai + 1))
        return None

    def placer(self, site):
        cle = f'{site["adr"]}|{site["cp"]}|{site["ville"]}'.lower()
        if cle not in self.cache and self.actif:
            res = None
            if site["adr"]:
                r = self._requete({"q": f'{site["adr"]} {site["ville"]}', "postcode": site["cp"], "index": "address"})
                if r and r[2] >= 0.5:
                    res = [r[0], r[1], "adresse"]
            if res is None:  # adresse absente ou introuvable : centre de la commune
                r = self._requete({"q": site["ville"], "postcode": site["cp"], "index": "address", "type": "municipality"})
                if r:
                    res = [r[0], r[1], "commune"]
            if res:  # on ne met en cache que les réussites, les échecs seront retentés
                self.cache[cle] = res
        if cle in self.cache:
            site["lat"], site["lon"], site["precision"] = self.cache[cle]
            site["km"] = round(km_grenoble(site["lat"], site["lon"]), 1)

    def depuis_cache(self, site):
        """Positionne un site sans appel réseau (pour l'ancienne photo)."""
        actif, self.actif = self.actif, False
        self.placer(site)
        self.actif = actif

    def enregistrer(self):
        ecrire_json(GEOCACHE, self.cache)


# --------------------------------------------------------------- comparaison
def km_grenoble(lat, lon):
    la1, lo1, la2, lo2 = map(math.radians, (GRENOBLE[0], GRENOBLE[1], lat, lon))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(h))


def dans_zone(s):
    if s["dep"] == DEPARTEMENT:
        return True
    return s.get("km") is not None and s["km"] <= RAYON_KM


def en_isere(p):  # « dans la zone suivie »
    return [s for s in p.get("sites", []) if dans_zone(s)]


def ailleurs(p):
    return [s for s in p.get("sites", []) if not dans_zone(s)]


def proche(sites):
    km = [s["km"] for s in sites if s.get("km") is not None]
    return round(min(km)) if km else None


def lieux(sites):
    return sorted({f'{s["ville"]} ({s["cp"]})' for s in sites})


def comparer(avant, apres, date):
    ev = []
    for rpps in set(avant) | set(apres):
        a, b = avant.get(rpps), apres.get(rpps)
        a38 = en_isere(a) if a else []
        b38 = en_isere(b) if b else []
        p = b or a
        base = {"date": date, "rpps": rpps, "civ": p["civ"], "nom": p["nom"],
                "prenom": p["prenom"], "sf": p["sf"], "km": proche(b38 or a38)}

        if b38 and not a38:
            if a is None:
                prov = "Nouvelle inscription à l'Ordre (jeune diplômé·e ou arrivée de l'étranger)"
            elif ailleurs(a):
                prov = "Exerçait à " + ", ".join(lieux(ailleurs(a)))
            else:
                prov = "Aucun lieu d'exercice déclaré auparavant"
            ev.append({**base, "type": "arrivee", "sites": b38,
                       "autres": ailleurs(b), "detail": prov})
        elif a38 and not b38:
            if b is None:
                dest = "Retiré·e de l'annuaire (retraite, radiation, décès…)"
            elif ailleurs(b):
                dest = "Exerce désormais à " + ", ".join(lieux(ailleurs(b)))
            else:
                dest = "Plus de lieu d'exercice déclaré"
            ev.append({**base, "type": "depart", "sites": a38,
                       "autres": ailleurs(b) if b else [], "detail": dest})
        elif a38 and b38:
            avant_l, apres_l = set(lieux(a38)), set(lieux(b38))
            nouveaux = apres_l - avant_l
            if nouveaux:
                quittes = avant_l - apres_l
                txt = "Nouveau lieu : " + ", ".join(sorted(nouveaux))
                if quittes:
                    txt += " — auparavant : " + ", ".join(sorted(quittes))
                ev.append({**base, "type": "mouvement",
                           "sites": [s for s in b38 if f'{s["ville"]} ({s["cp"]})' in nouveaux],
                           "autres": [], "detail": txt})
    ordre = {"arrivee": 0, "mouvement": 1, "depart": 2}
    ev.sort(key=lambda e: (ordre[e["type"]], e["nom"], e["prenom"]))
    return ev


# --------------------------------------------------------------------- écriture
def ecrire_json(chemin, obj):
    os.makedirs(os.path.dirname(chemin), exist_ok=True)
    with open(chemin, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))


def lire_json(chemin, defaut):
    try:
        with open(chemin, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return defaut


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", help="fichier local ou URL (défaut : data.gouv.fr)")
    ap.add_argument("--date", default=dt.date.today().isoformat())
    ap.add_argument("--sans-geo", action="store_true", help="ne pas géocoder (test hors ligne)")
    args = ap.parse_args()

    print("Lecture de l'annuaire…")
    apres = lire_dentistes(args.source)
    if len(apres) < 100 and not args.source:
        raise SystemExit(f"Seulement {len(apres)} dentistes lus : fichier source suspect, arrêt.")
    print(f"{len(apres)} chirurgiens-dentistes en France.")

    avant = None
    if os.path.exists(SNAPSHOT):
        with gzip.open(SNAPSHOT, "rt", encoding="utf-8") as f:
            avant = json.load(f)["pros"]

    # positions (Isère + départements voisins) avant la comparaison, pour le rayon de 50 km
    print("Géocodage des cabinets…")
    geo = Geocodeur(actif=not args.sans_geo)
    for p in apres.values():
        for s in p["sites"]:
            if s["dep"] == DEPARTEMENT or s["dep"] in DEPS_VOISINS:
                geo.placer(s)
    for p in (avant or {}).values():
        for s in p["sites"]:
            if s["dep"] == DEPARTEMENT or s["dep"] in DEPS_VOISINS:
                geo.depuis_cache(s)
    geo.enregistrer()
    print(f"{geo.appels} appel(s) de géocodage.")

    mouvements = lire_json(os.path.join(OUT_DIR, "mouvements.json"), [])
    nouveaux = comparer(avant, apres, args.date) if avant is not None else []
    if avant is not None and len(nouveaux) > 300:
        # garde-fou : un changement massif signale un problème de format, pas 300 installations
        raise SystemExit(f"{len(nouveaux)} mouvements détectés d'un coup : anomalie probable, arrêt.")
    mouvements = nouveaux + mouvements

    isere = []
    for rpps, p in apres.items():
        s38 = en_isere(p)
        if s38:
            isere.append({"rpps": rpps, "civ": p["civ"], "nom": p["nom"], "prenom": p["prenom"],
                          "sf": p["sf"], "sites": s38, "autres": ailleurs(p), "km": proche(s38)})
    isere.sort(key=lambda x: (x["nom"], x["prenom"]))

    # date d'arrivée en Isère (pour la carte « température ») : dernière arrivée constatée
    arrivees = {}
    for e in mouvements:  # du plus récent au plus ancien
        if e["type"] == "arrivee" and e["rpps"] not in arrivees:
            arrivees[e["rpps"]] = e["date"]
    for p in isere:
        p["arrivee"] = arrivees.get(p["rpps"])


    meta = lire_json(os.path.join(OUT_DIR, "meta.json"), {})
    meta.setdefault("debut_suivi", args.date)
    meta.update({"maj": args.date, "nb_isere": len(isere), "nb_france": len(apres),
                 "rayon_km": RAYON_KM, "centre": GRENOBLE})
    meta.setdefault("historique", []).append(
        {"date": args.date, "isere": len(isere),
         "arrivees": sum(e["type"] == "arrivee" for e in nouveaux),
         "departs": sum(e["type"] == "depart" for e in nouveaux),
         "mouvements": sum(e["type"] == "mouvement" for e in nouveaux)})

    # les mouvements sont écrits après géocodage pour que les départs aient leur position
    ecrire_json(os.path.join(OUT_DIR, "isere.json"), isere)
    ecrire_json(os.path.join(OUT_DIR, "mouvements.json"), mouvements)
    ecrire_json(os.path.join(OUT_DIR, "meta.json"), meta)
    os.makedirs(os.path.dirname(SNAPSHOT), exist_ok=True)
    with gzip.open(SNAPSHOT, "wt", encoding="utf-8") as f:
        json.dump({"date": args.date, "pros": apres}, f, ensure_ascii=False, separators=(",", ":"))

    for fic in (ALERTE, ALERTE + ".titre"):
        if os.path.exists(fic):
            os.remove(fic)
    if nouveaux:
        etiquette = {"arrivee": "🟢 Arrivée", "depart": "🔴 Départ", "mouvement": "🔵 Changement de lieu"}
        pres = [e for e in nouveaux if e["km"] is not None and e["km"] <= RAYON_KM]
        loin = [e for e in nouveaux if e not in pres]

        def ligne(e):
            sf = f" — {', '.join(e['sf'])}" if e["sf"] else ""
            ou = ", ".join(lieux(e["sites"]))
            km = f" (à {e['km']} km de Grenoble)" if e["km"] is not None else ""
            return f"- **{etiquette[e['type']]}** : {e['civ']} {e['prenom']} {e['nom']}{sf} — {ou}{km}. {e['detail']}"

        lignes = []
        if pres:
            lignes += [f"## ⭐ À moins de {RAYON_KM} km de Grenoble ({len(pres)})", ""] + [ligne(e) for e in pres] + [""]
        if loin:
            lignes += [f"## Reste de l'Isère ({len(loin)})", ""] + [ligne(e) for e in loin] + [""]
        lignes += ["Voir la carte et le détail : https://drlacroixthibault.github.io/veille-dentistes-isere/"]
        with open(ALERTE, "w", encoding="utf-8") as f:
            f.write("\n".join(lignes) + "\n")
        titre_alerte = (f"⭐ {len(pres)} près de Grenoble · " if pres else "") + f"{len(nouveaux)} mouvement(s) confrères"
        with open(ALERTE + ".titre", "w", encoding="utf-8") as f:
            f.write(titre_alerte)

    if avant is None:
        print(f"Premier passage : photo de référence enregistrée ({len(isere)} dentistes en Isère).")
    else:
        print(f"{len(nouveaux)} mouvement(s) détecté(s). {len(isere)} dentistes en Isère.")


if __name__ == "__main__":
    main()
