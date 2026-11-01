# Veille des confrères — Isère

Petit outil gratuit qui repère chaque semaine les chirurgiens-dentistes qui arrivent en Isère, qui en partent ou qui changent de commune, avec leur provenance ou leur destination.

**Source** : Annuaire Santé de l'Agence du Numérique en Santé (données RPPS transmises par l'Ordre des chirurgiens-dentistes), publié en open data sur data.gouv.fr sous Licence Ouverte 2.0. Fichier mis à jour quotidiennement par l'ANS.

**Fonctionnement** : chaque lundi matin, GitHub lance `veille.py`, qui lit l'annuaire national, compare avec la semaine précédente, met à jour la page web et, s'il y a du nouveau, vous envoie un e-mail. Coût : 0 €.

---

## Mise en place (15 minutes, une seule fois)

1. **Créer un compte** sur [github.com](https://github.com) (gratuit).
2. **Créer un dépôt** : bouton « New repository », nom `veille-dentistes-isere`, cocher **Public** (nécessaire pour l'hébergement gratuit de la page), puis « Create repository ».
3. **Envoyer les fichiers** : sur la page du dépôt, « uploading an existing file », puis glisser tout le contenu du dossier dézippé.
   - Sur Mac, le dossier `.github` est masqué : dans le Finder, appuyez sur `Cmd + Maj + .` pour l'afficher avant de glisser.
   - Si le dossier `.github` refuse de partir : « Add file › Create new file », tapez `.github/workflows/veille.yml` comme nom, collez le contenu du fichier, validez.
4. **Autoriser l'écriture** : Settings › Actions › General › Workflow permissions › cocher « Read and write permissions » › Save.
5. **Activer la page** : Settings › Pages › Source › choisir **GitHub Actions**.
6. **Premier lancement** : onglet Actions › « Mise à jour hebdomadaire » › « Run workflow ». Comptez 5 à 10 minutes.

La page est alors en ligne à l'adresse : `https://VOTRE-PSEUDO.github.io/veille-dentistes-isere/`

## À savoir

- **Le premier passage sert de référence** : il affiche l'annuaire complet de l'Isère, mais aucun mouvement. Les arrivées et départs apparaissent à partir du lundi suivant.
- **Alertes e-mail** : quand il y a du nouveau, l'outil crée une « issue » dans le dépôt et GitHub vous l'envoie par e-mail (adresse du compte GitHub).
- **Provenance** : « Exerçait à Colmar » si le confrère figurait ailleurs dans l'annuaire la semaine précédente ; « Nouvelle inscription » s'il n'existait pas encore (jeune diplômé ou arrivée de l'étranger).
- **Annuaire Isère** : le tri « inscription la plus récente » utilise le numéro RPPS, attribué dans l'ordre chronologique. Utile dès le premier jour, mais approximatif.
- **Carte « température »** : chaque cabinet est placé à son adresse (géocodage gratuit de l'IGN, fait une seule fois par adresse puis mémorisé). Un nouvel arrivant apparaît en rouge vif, puis vire au violet et au bleu au fil de l'année qui suit son arrivée ; les confrères installés avant le début du suivi sont de petits points bleu pâle (masquables) ; un départ reste affiché en noir pendant trois mois, puis disparaît de la carte. Quand l'adresse est introuvable, le point est placé au centre de la commune et la fiche le signale. Le premier passage prend quelques minutes de plus, le temps de géocoder tous les cabinets de l'Isère.
- **Garde-fous** : si le fichier source change de format ou paraît vide, le script s'arrête sans rien écraser (GitHub vous prévient d'un échec par e-mail).
- **Autre département** : modifier `DEPARTEMENT = "38"` en haut de `veille.py`.
- Les données sont publiques (open data), la page n'est pas indexée par les moteurs de recherche.
