# DimCE — dimensionnement de communautés d'énergie (version Python)

DimCE permet de déterminer le **nombre optimal** et le **nombre maximal** de consommateurs
à faire entrer dans une communauté d'énergie (CE) autour d'un ou plusieurs producteurs
(solaire, éolien, cogénération/biométhanisation, avec ou sans batterie), et d'estimer les
gains de chacun.

Ce dépôt est une conversion en Python de l'application MATLAB `DimCE.m` (App Designer).
Le moteur de calcul est repris fonction par fonction ; l'interface est disponible en
version web (Streamlit) et en version bureau (PySide6 / Qt).

## Contenu du dépôt

| Fichier | Rôle |
|---|---|
| `dimce.py` | Moteur de calcul, graphiques matplotlib et ligne de commande |
| `dimce_app.py` | Interface web (Streamlit) |
| `dimce_gui_qt.py` | Interface bureau (PySide6) |
| `DataCE.mat` | Profils au quart d'heure (35 136 valeurs) de consommation et de production |
| `tableautarif.csv` | Tarifs des fournisseurs |
| `assets/` | (optionnel) images de l'interface bureau : `splash.png`, `app_icon.png`, icônes des boutons |
| `requirements.txt` | Dépendances Python |

Les fichiers `DataCE.mat` et `tableautarif.csv` proviennent de l'archive d'origine
(`DimceM.zip`) : copiez-les à côté des scripts. Conservez aussi le fichier `LICENSE` d'origine.

## Installation

Python 3.10 ou plus récent.

```bash
pip install -r requirements.txt
```

PySide6 est installé par `pip` avec le reste des dépendances (aucun paquet système
supplémentaire n'est nécessaire sous Windows et macOS). Sous Linux, si l'interface ne démarre
pas avec une erreur du plugin Qt « xcb », installez les bibliothèques manquantes, par exemple :
`sudo apt install libxcb-cursor0`. PySide6 n'est pas nécessaire pour la version web.

## Utilisation

### Interface web (Streamlit)

```bash
streamlit run dimce_app.py
```

### Interface bureau (PySide6)

```bash
python dimce_gui_qt.py
```

Les interfaces proposent ces onglets :

1. **Simulation CE** — simulation rapide (un producteur + N consommateurs) ou sur une CE
   personnalisée ; résultats au maximum d'énergie vendue et à l'optimum, 4 graphiques,
   tableau détaillé, export. Dans la version bureau, la simulation s'exécute dans un thread
   séparé : l'interface reste utilisable et le bouton **« Arrêter la simulation »** permet de
   l'interrompre (l'arrêt est effectif à la fin de l'étape en cours, c'est-à-dire après le
   consommateur en cours de calcul).
2. **Personnaliser la CE** — saisie des membres, import/export, gains de chaque membre,
   énergie échangée par mois.
3. **Dimensionnement installation** — temps de retour en fonction de la puissance installée
   (disponible en version web et en ligne de commande ; désactivé dans l'interface bureau,
   comme dans le code d'origine).
4. **Tarifs** — tarifs du fournisseur choisi (modifiables pour la session).

### Ligne de commande

```bash
python dimce.py optim --puissance 4 --type Solaire --nb-conso-max 10 --graphique 2
python dimce.py perso ma_ce.csv --optimiser
python dimce.py dim --conso 3500 --type Solaire
```

`python dimce.py <commande> --help` liste toutes les options (fournisseur, prix de vente et
d'achat, partage dans un même bâtiment, export, enregistrement du graphique…).

### Dans votre propre code

```python
import dimce as d

res = d.optimiser_rapide(puissance=4, type_prod="Solaire", nb_conso_max=10)
print(res.table)      # une ligne par nombre de consommateurs ajoutés
print(res.resume())   # maximum d'énergie vendue et optimum
```

Fonctions principales : `optimiser_rapide`, `optimiser`, `analyser_ce_perso`,
`dimensionner_installation`, `facture`, `importer_ce`, `tracer_optimisation`.

Pour interrompre `optimiser` depuis votre propre code, levez une exception dans la fonction
`progression` : elle est appelée au début de chaque étape.

## Format du fichier d'import d'une CE

Fichier `.csv`, `.xlsx` ou `.xls` avec ces colonnes (une ligne par membre) :

| Colonne | Contenu |
|---|---|
| `Nom` | Nom du membre |
| `Consommationannuelleparticulier` | kWh/an, profil « particulier » |
| `Consommationannuelleusine` | kWh/an, profil « industrie » |
| `ConsommationannuelleAdministration` | kWh/an, profil « administration » |
| `PuissanceinstalleeSol` | kW solaire |
| `PuissanceinstalleeEol` | kW éolien |
| `PuissanceinstalleeBio` | kW bio/cogénération |
| `PuissanceinstalleeBatt` | kW de la batterie |
| `Capabat` | kWh de la batterie |

Une CE doit comporter au moins un membre producteur pour être simulée.

## Principes du modèle

- Pour chaque membre, on calcule au quart d'heure la production, la consommation, le
  surplus et la consommation résiduelle. La batterie éventuelle se charge avec le surplus
  et se décharge quand il y a un déficit.
- Le partage dans la CE répartit, à chaque quart d'heure, le surplus total entre les membres
  en déficit (ou l'inverse), au prorata de leurs besoins (ou de leurs surplus).
- Rendements annuels utilisés : solaire 937,9 kWh/kW, éolien 2 076,9 kWh/kW,
  cogénération/biométhanisation 6 547,4 kWh/kW.
- L'optimisation ajoute les consommateurs un par un. Le **maximum d'énergie vendue** est le
  nombre de consommateurs à partir duquel le surplus vendu ne progresse plus ; l'**optimum**
  est atteint quand le gain marginal du producteur tombe sous 20 % de son premier gain.
- Le prix d'achat de la CE au producteur doit rester inférieur ou égal au prix de vente au
  consommateur.

## Déploiement de la version web (Streamlit Community Cloud)

1. Placez dans un dépôt GitHub : `dimce.py`, `dimce_app.py`, `DataCE.mat`,
   `tableautarif.csv` et `requirements.txt` (au besoin aussi `dimce_gui_qt.py`, `README.md`
   et `LICENSE`).
2. Sur <https://share.streamlit.io>, créez une application depuis ce dépôt et indiquez
   `dimce_app.py` comme fichier principal.

Remarque : `requirements.txt` contient PySide6, inutile (et volumineux) pour la version web.
Pour un déploiement allégé, retirez la ligne `PySide6` du fichier utilisé par Streamlit Cloud
(ou séparez-la dans un `requirements-gui.txt`).

## Créer un exécutable Windows (version PySide6)

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --add-data "DataCE.mat;." --add-data "tableautarif.csv;." --add-data "assets;assets" dimce_gui_qt.py
```

L'exécutable est créé dans `dist/`. Sous Linux et macOS, remplacez `;` par `:` dans
`--add-data`. Si vous n'avez pas de dossier `assets/`, retirez l'option correspondante.

## Limites connues

- Comportements du code MATLAB conservés tels quels :
  - en simulation rapide, toute la puissance installée est portée par un seul producteur .
- L'export Excel écrit des `.xlsx` (le `.xls` n'est pas géré en écriture).
- L'arrêt d'une simulation dans l'interface bureau n'intervient qu'entre deux étapes ; la
  simulation initiale de la CE (avant l'ajout des consommateurs) ne peut pas être interrompue.

## Contact

dimce@ikmail.com
