# DimCE — dimensionnement de communautés d'énergie (version Python)

DimCE permet de déterminer le **nombre optimal** et le **nombre maximal** de consommateurs
à faire entrer dans une communauté d'énergie (CE) autour d'un ou plusieurs producteurs
(solaire, éolien, cogénération/biométhanisation, avec ou sans batterie), et d'estimer les
gains de chacun.

Ce dépôt est une conversion en Python de l'application MATLAB `DimCE.m` (App Designer).
Le moteur de calcul est repris fonction par fonction ; l'interface est disponible en
version web (Streamlit) et en version bureau (Tkinter).

## Contenu du dépôt

| Fichier | Rôle |
|---|---|
| `dimce.py` | Moteur de calcul, graphiques matplotlib et ligne de commande |
| `dimce_app.py` | Interface web (Streamlit) |
| `dimce_gui.py` | Interface bureau (Tkinter) |
| `DataCE.mat` | Profils au quart d'heure (35 136 valeurs) de consommation et de production |
| `tableautarif.csv` | Tarifs des fournisseurs |
| `requirements.txt` | Dépendances Python |

Les fichiers `DataCE.mat` et `tableautarif.csv` proviennent de l'archive d'origine
(`DimceM.zip`) : copiez-les à côté des scripts. Conservez aussi le fichier `LICENSE` d'origine.

## Installation

Python 3.10 ou plus récent.

```bash
pip install -r requirements.txt
```

Tkinter est inclus avec Python sous Windows et macOS. Sous Linux :
`sudo apt install python3-tk`. Il n'est pas nécessaire pour la version web.

## Utilisation

### Interface web (Streamlit)

```bash
streamlit run dimce_app.py
```

### Interface bureau (Tkinter)

```bash
python dimce_gui.py
```

Les deux interfaces proposent les mêmes onglets :

1. **Simulation CE** — simulation rapide (un producteur + N consommateurs) ou sur une CE
   personnalisée ; résultats au maximum d'énergie vendue et à l'optimum, 4 graphiques,
   tableau détaillé, export.
2. **Personnaliser la CE** — saisie des membres, import/export, gains de chaque membre,
   énergie échangée par mois.
3. **Dimensionnement installation** — temps de retour en fonction de la puissance installée.
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
   `tableautarif.csv` et `requirements.txt` (au besoin aussi `dimce_gui.py`, `README.md`
   et `LICENSE`).
2. Sur <https://share.streamlit.io>, créez une application depuis ce dépôt et indiquez
   `dimce_app.py` comme fichier principal.

## Créer un exécutable Windows (version Tkinter)

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --add-data "DataCE.mat;." --add-data "tableautarif.csv;." dimce_gui.py
```

L'exécutable est créé dans `dist/`. Sous Linux et macOS, remplacez `;` par `:` dans
`--add-data`.

## Limites connues

- Comportements du code MATLAB conservés tels quels :
  - en simulation rapide, toute la puissance installée est portée par un seul producteur ;
  - la facture « avec CE » du consommateur ne tient pas compte de l'option
    « partage dans un même bâtiment », contrairement au calcul du gain.
- L'export Excel écrit des `.xlsx` (le `.xls` n'est pas géré en écriture).

## Contact

dimce@ikmail.com
