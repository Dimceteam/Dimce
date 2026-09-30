#!/usr/bin/env python3
"""
DimCE - dimensionnement de communautés d'énergie (CE).

Port Python de la logique de calcul de ``DimCE.m`` (application MATLAB App Designer).
L'interface graphique n'est pas portée : on retrouve ici le moteur de calcul, les
graphiques (matplotlib) et une ligne de commande.

Fichiers de données attendus dans le même dossier que ce script (ceux de DimceM/) :
    - DataCE.mat        profils 1/4 h (35136 valeurs) de consommation et de production
    - tableautarif.csv  tarifs des fournisseurs

Dépendances : numpy, pandas, scipy, matplotlib   (+ openpyxl pour lire/écrire du .xlsx)

Exemples en ligne de commande :
    python dimce.py optim --puissance 4 --type Solaire --nb-conso-max 10 --graphique 1
    python dimce.py perso ma_ce.csv --optimiser --graphique 2
    python dimce.py dim --conso 3500 --type Solaire
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
import scipy.io

# --------------------------------------------------------------------------- #
# Constantes
# --------------------------------------------------------------------------- #
DOSSIER = Path(__file__).resolve().parent
N_QUARTS = 35136                       # nombre de quarts d'heure de la série
QUARTS_PAR_MOIS = N_QUARTS // 12       # 2928, comme dans le code MATLAB

# Rendement annuel (kWh produits par kW installé)
RENDEMENT = {"Solaire": 937.9, "Eolien": 2076.9, "Cogen/Biometh.": 6547.4}

FOURNISSEURS = ["Mega", "Luminus", "Engie", "Total Energie", "Bolt",
                "Luminus BXL", "Total BXL", "Eneco"]

# Lignes du tableau de tarif (ordre du CSV / de app.tabPrix)
LIGNES_TARIF = [
    "Prix injection €/kWh",
    "Prix énergie €/kWh",
    "Frais de distribution Resa €/kWh",
    "Frais de transport Resa €/kWh",
    "Frais de distribution terme fixe Resa (€/an)",
    "Redevance de raccordement €/kWh",
    "Accise spéciale €/kWh",
    "Cotisation sur l'énergie €/kWh",
    "Cotisation Verte (€/kWh)",
    "Tarif Prosumer Resa (€/an/kVA)",
    "Redevance fixe (€/an)",
    "Forfait panneaux solaires (€/kVA par mois)",
    "Forfait partage d'énergie (€/an)",
]
# Indices (0-based) des lignes utilisées directement dans les formules
T_INJECTION, T_ENERGIE, T_DISTRIB, T_TRANSPORT, T_PARTAGE = 0, 1, 2, 3, 12

# Postes de la facture (tarif sans la ligne "injection")
POSTES_FACTURE = [
    "Prix énergie", "Frais de distribution Resa", "Frais de transport Resa",
    "Frais de distribution terme fixe Resa", "Redevance de raccordement",
    "Accise spéciale", "Cotisation sur l'énergie", "Cotisation Verte",
    "Tarif Prosumer Resa", "Redevance fixe", "Forfait panneaux solaires",
    "Forfait partage d'énergie",
]

COLONNES_CE = [
    "Nom", "Consommationannuelleparticulier", "Consommationannuelleusine",
    "ConsommationannuelleAdministration", "PuissanceinstalleeSol",
    "PuissanceinstalleeEol", "PuissanceinstalleeBio", "PuissanceinstalleeBatt",
    "Capabat",
]

# Prix (€ HTVA) d'une installation selon sa puissance (kW) - courbe de dimensionnement
PRIX_PUISSANCE_HTVA = np.array([[0, 0], [3, 5800], [5, 7500],
                                [11, 12500], [20, 21000], [50, 48000]], dtype=float)


# --------------------------------------------------------------------------- #
# Chargement des données
# --------------------------------------------------------------------------- #
@lru_cache(maxsize=None)
def _profils(dossier: str = str(DOSSIER)) -> dict[str, np.ndarray]:
    """Charge DataCE.mat (équivalent du ``load('DataCE.mat', ...)`` de Dimdata)."""
    mat = scipy.io.loadmat(Path(dossier) / "DataCE.mat")
    noms = ["ConsoAdmin", "ConsoPart", "ConsoUsine",
            "LoadFactorCo", "LoadFactorEol", "LoadFactorSol"]
    return {n: np.asarray(mat[n], dtype=float).ravel() for n in noms}


@dataclass
class Tarifs:
    """Contenu de tableautarif.csv."""
    table: pd.DataFrame          # index = LIGNES_TARIF, colonnes = fournisseurs
    date: str

    def pour(self, fournisseur: str) -> np.ndarray:
        """Vecteur de 13 tarifs (copie modifiable) pour un fournisseur."""
        if fournisseur not in self.table.columns:
            raise KeyError(f"Fournisseur inconnu : {fournisseur!r} "
                           f"(choix : {', '.join(self.table.columns)})")
        return self.table[fournisseur].to_numpy(dtype=float).copy()


def charger_tarifs(chemin: str | Path | None = None) -> Tarifs:
    """Équivalent de ``importtarif`` : CSV séparé par ';' avec virgule décimale."""
    chemin = Path(chemin) if chemin else DOSSIER / "tableautarif.csv"
    brut = pd.read_csv(chemin, sep=";", decimal=",", header=None, skiprows=1,
                       dtype=str, keep_default_na=False)
    valeurs = brut.iloc[:, 2:2 + len(FOURNISSEURS)].apply(
        lambda c: pd.to_numeric(c.str.replace(",", ".", regex=False), errors="coerce"))
    valeurs.columns = FOURNISSEURS
    valeurs.index = LIGNES_TARIF
    date = str(brut.iloc[0, 2 + len(FOURNISSEURS)]).strip()
    return Tarifs(valeurs, date)


# --------------------------------------------------------------------------- #
# Simulation d'un membre (Dimdata)
# --------------------------------------------------------------------------- #
def _simuler_batterie(surplus: np.ndarray, conso_resid: np.ndarray,
                      pi_bat: float, capa_bat: float) -> np.ndarray:
    """Charge/décharge quart d'heure par quart d'heure. Modifie surplus et
    conso_resid en place, renvoie l'état de charge (kWh)."""
    soc = np.zeros(N_QUARTS)
    cmax = pi_bat / 4            # énergie max échangée par quart d'heure
    charge = 0.0
    for i in range(N_QUARTS):
        s = surplus[i]
        if s > 0:                                  # il y a du surplus -> charge
            if s <= cmax:
                if charge + s < capa_bat:
                    charge += s
                    soc[i] = charge
                    surplus[i] = 0.0
                else:
                    surplus[i] = s - (capa_bat - charge)
                    charge = capa_bat
                    soc[i] = charge
            else:
                if charge + cmax < capa_bat:
                    charge += cmax
                    soc[i] = charge
                    surplus[i] = s - cmax
                else:
                    surplus[i] = s - (capa_bat - charge)
                    charge = capa_bat
                    soc[i] = charge
        else:                                      # pas de surplus -> décharge éventuelle
            c = conso_resid[i]
            if c > 0 and charge > 0:
                if c <= cmax:
                    if charge - c >= 0:
                        charge -= c
                        soc[i] = charge
                        conso_resid[i] = 0.0
                    else:
                        conso_resid[i] = c - charge
                        charge = 0.0
                        soc[i] = 0.0
                else:
                    if charge - cmax >= 0:
                        charge -= cmax
                        soc[i] = charge
                        conso_resid[i] = c - cmax
                    else:
                        conso_resid[i] = c - charge
                        charge = 0.0
                        soc[i] = 0.0
            else:
                soc[i] = charge
    return soc


@lru_cache(maxsize=None)
def _dimdata_cache(pi_eol, pi_sol, pi_bio, ca_ind, ca_part, ca_admin, pi_bat, capa_bat):
    p = _profils()
    conso_part = ca_part * p["ConsoPart"]
    conso_usine = ca_ind * p["ConsoUsine"]
    conso_admin = ca_admin * p["ConsoAdmin"]
    prod_quart = ((pi_sol / 4) * p["LoadFactorSol"]
                  + (pi_eol / 4) * p["LoadFactorEol"]
                  + (pi_bio / 4) * p["LoadFactorCo"])
    prod_total = prod_quart.sum()
    conso_quart = conso_part + conso_usine + conso_admin
    conso_total = conso_quart.sum()

    surplus = np.maximum(prod_quart - conso_quart, 0.0)
    conso_resid = np.maximum(conso_quart - prod_quart, 0.0)

    if pi_bat == 0 or capa_bat == 0:
        soc = np.zeros(N_QUARTS)
    else:
        soc = _simuler_batterie(surplus, conso_resid, pi_bat, capa_bat)

    with np.errstate(divide="ignore", invalid="ignore"):
        autosuffi = (conso_total - conso_resid.sum()) / conso_total
        autoconsom = (prod_total - surplus.sum()) / prod_total
    for a in (conso_resid, surplus, soc):
        a.setflags(write=False)       # résultats mis en cache : lecture seule
    return autosuffi, autoconsom, conso_resid, surplus, prod_total, soc


def dimdata(pi_eol, pi_sol, pi_bio, ca_ind, ca_part, ca_admin, pi_bat, capa_bat):
    """Simule un membre sur l'année.

    Renvoie ``(autosuffisance, autoconsommation, conso_résiduelle_1/4h,
    surplus_1/4h, production_totale, état_de_charge_1/4h)``.
    (Résultats mis en cache : les tableaux renvoyés sont en lecture seule.)
    """
    return _dimdata_cache(*(float(x) for x in (pi_eol, pi_sol, pi_bio, ca_ind,
                                               ca_part, ca_admin, pi_bat, capa_bat)))


# --------------------------------------------------------------------------- #
# Membres et simulation de la CE (CEini)
# --------------------------------------------------------------------------- #
@dataclass
class Membres:
    """Vecteurs décrivant les membres de la CE (un élément par membre)."""
    ca_part: np.ndarray            # consommation annuelle particulier (kWh)
    ca_ind: np.ndarray             # consommation annuelle industrie (kWh)
    ca_admin: np.ndarray           # consommation annuelle administration (kWh)
    pi_sol: np.ndarray             # puissance solaire installée (kW)
    pi_eol: np.ndarray             # puissance éolienne installée (kW)
    pi_bio: np.ndarray             # puissance bio/cogénération installée (kW)
    pi_bat: np.ndarray             # puissance batterie (kW)
    capa_bat: np.ndarray           # capacité batterie (kWh)
    noms: list[str] | None = None

    def __post_init__(self):
        for nom in ("ca_part", "ca_ind", "ca_admin", "pi_sol", "pi_eol",
                    "pi_bio", "pi_bat", "capa_bat"):
            setattr(self, nom, np.atleast_1d(np.asarray(getattr(self, nom), dtype=float)))

    def __len__(self):
        return len(self.ca_part)

    def avec_consommateurs(self, n: int, conso_annuelle: float) -> "Membres":
        """Copie avec ``n`` consommateurs purs supplémentaires."""
        z = np.zeros(n)
        cat = np.concatenate
        return Membres(cat([self.ca_part, np.full(n, conso_annuelle)]),
                       cat([self.ca_ind, z]), cat([self.ca_admin, z]),
                       cat([self.pi_sol, z]), cat([self.pi_eol, z]),
                       cat([self.pi_bio, z]), cat([self.pi_bat, z]),
                       cat([self.capa_bat, z]))

    @classmethod
    def depuis_table(cls, ce: pd.DataFrame) -> "Membres":
        """Construit les membres à partir du tableau de la CE personnalisée."""
        g = lambda c: ce[c].to_numpy(dtype=float)
        return cls(g("Consommationannuelleparticulier"), g("Consommationannuelleusine"),
                   g("ConsommationannuelleAdministration"), g("PuissanceinstalleeSol"),
                   g("PuissanceinstalleeEol"), g("PuissanceinstalleeBio"),
                   g("PuissanceinstalleeBatt"), g("Capabat"),
                   noms=[str(n) for n in ce["Nom"]])

    @classmethod
    def simulation_rapide(cls, puissance_totale: float, type_prod: str = "Solaire",
                          conso_producteur: float = 3500.0) -> "Membres":
        """Mode « Simulation rapide » : un seul producteur (comme dans DimCE.m,
        toute la puissance installée est portée par ce membre)."""
        if type_prod not in RENDEMENT:
            raise ValueError(f"Type de production inconnu : {type_prod!r} "
                             f"(choix : {', '.join(RENDEMENT)})")
        pi = {"Solaire": 0.0, "Eolien": 0.0, "Cogen/Biometh.": 0.0}
        pi[type_prod] = float(puissance_totale)
        return cls([conso_producteur], [0.0], [0.0], [pi["Solaire"]], [pi["Eolien"]],
                   [pi["Cogen/Biometh."]], [0.0], [0.0])


def _fill0(x: np.ndarray) -> np.ndarray:
    """Équivalent de ``fillmissing(x, 'constant', 0)`` (NaN uniquement)."""
    return np.where(np.isnan(x), 0.0, x)


@dataclass
class EtatCE:
    autosuf: np.ndarray            # autosuffisance initiale par membre
    autocons: np.ndarray           # autoconsommation initiale par membre
    autosuf_f: np.ndarray          # autosuffisance dans la CE
    autoconsom_f: np.ndarray       # autoconsommation dans la CE
    autosuf_acquise: np.ndarray    # part de conso couverte grâce à la CE
    surplus_vendu: np.ndarray      # part de la production vendue à la CE
    prod: np.ndarray               # production annuelle par membre (kWh)
    resid: np.ndarray              # (35136, n) conso résiduelle avant partage
    su: np.ndarray                 # (35136, n) surplus avant partage
    residf: np.ndarray             # (35136, n) conso résiduelle après partage
    suf: np.ndarray                # (35136, n) surplus après partage
    soc: np.ndarray                # (35136, n) état de charge des batteries


def _partager(resid: np.ndarray, su: np.ndarray):
    """Répartition proportionnelle, quart d'heure par quart d'heure, du surplus
    total entre les membres en déficit (ou inversement)."""
    sutot = su.sum(axis=1)
    restot = resid.sum(axis=1)
    residf = np.zeros_like(resid)
    suf = np.zeros_like(su)
    with np.errstate(divide="ignore", invalid="ignore"):
        m = (restot >= sutot) & (restot > 0)          # demande >= offre
        a = sutot[m] / restot[m]
        residf[m] = resid[m] - a[:, None] * resid[m]
        m2 = restot < sutot                           # offre > demande
        b = (sutot[m2] - restot[m2]) / sutot[m2]
        suf[m2] = b[:, None] * su[m2]
    return residf, suf


def simuler_ce(m: Membres) -> EtatCE:
    """Équivalent de ``CEini`` : simule tous les membres puis le partage dans la CE."""
    n = len(m)
    resid = np.zeros((N_QUARTS, n))
    su = np.zeros((N_QUARTS, n))
    soc = np.zeros((N_QUARTS, n))
    autosuf = np.zeros(n)
    autocons = np.zeros(n)
    prod = np.zeros(n)
    for i in range(n):
        (autosuf[i], autocons[i], resid[:, i], su[:, i],
         prod[i], soc[:, i]) = dimdata(m.pi_eol[i], m.pi_sol[i], m.pi_bio[i],
                                       m.ca_ind[i], m.ca_part[i], m.ca_admin[i],
                                       m.pi_bat[i], m.capa_bat[i])
    residf, suf = _partager(resid, su)

    conso_tot = m.ca_part + m.ca_ind + m.ca_admin
    with np.errstate(divide="ignore", invalid="ignore"):
        autosuf_f = (conso_tot - residf.sum(axis=0)) / conso_tot
        autoconsom_f = (prod - suf.sum(axis=0)) / prod
        autosuf_acq = (resid.sum(axis=0) - residf.sum(axis=0)) / conso_tot
    surplus_vendu = _fill0(autoconsom_f - autocons)
    return EtatCE(_fill0(autosuf), _fill0(autocons), _fill0(autosuf_f), autoconsom_f,
                  _fill0(autosuf_acq), surplus_vendu, prod, resid, su, residf, suf, soc)


# --------------------------------------------------------------------------- #
# Optimisation (optiCe)
# --------------------------------------------------------------------------- #
def _verifier_prix(prix_vente: float, prix_achat: float) -> None:
    if prix_achat > prix_vente:
        raise ValueError("Le prix d'achat de l'électricité de la CE au producteur doit "
                         "être plus petit que le prix de vente au consommateur.")


COLONNES_OPTI = ["Nbr de Conso.", "Autosuffisance conso.", "Surplus Vendu CE",
                 "Gain conso.", "Gain prod."]


@dataclass
class ResultatOptimisation:
    table: pd.DataFrame                 # une ligne par nombre de consommateurs ajoutés
    nb_conso_surplus_max: int
    surplus_max: float
    autosuf_max: float
    nb_conso_opti: int
    # contexte nécessaire aux factures / graphiques
    tarif: np.ndarray
    prix_vente: float
    prix_achat: float
    partage_batiment: bool
    annuel_conso_conso: float
    annuel_conso_prod: float
    autosuf_prod: float
    autosuf_inter_prod: float
    autoconso_prod: float
    prod_annuel: float
    nb_prod: int
    indice_producteur: int

    @property
    def ligne_surplus_max(self) -> pd.Series:
        return self.table.iloc[self.nb_conso_surplus_max - 1]

    @property
    def ligne_opti(self) -> pd.Series:
        return self.table.iloc[self.nb_conso_opti - 1]

    def resume(self) -> str:
        s, o = self.ligne_surplus_max, self.ligne_opti
        return (
            f"Au maximum d'énergie vendue ({self.nb_conso_surplus_max} conso.) : "
            f"surplus vendu {s['Surplus Vendu CE']:.2%}, "
            f"gain producteur {s['Gain prod.']:.2f} €/an, gain conso. {s['Gain conso.']:.2f} €/an\n"
            f"À l'optimum ({self.nb_conso_opti} conso.) : "
            f"gain producteur {o['Gain prod.']:.2f} €/an, gain conso. {o['Gain conso.']:.2f} €/an"
        )


def optimiser(membres: Membres, tarif: np.ndarray, *, conso_consommateur: float = 3500.0,
              nb_conso_max: int = 10, prix_vente: float = 0.09, prix_achat: float = 0.08,
              partage_batiment: bool = False, nb_prod: int = 1,
              prod_annuel: float | None = None, progression=None) -> ResultatOptimisation:
    """Ajoute des consommateurs un par un et cherche le nombre maximal / optimal.

    ``progression``  : fonction optionnelle ``f(fraction)`` appelée à chaque étape.
    ``prod_annuel``  : production annuelle d'un producteur (kWh) utilisée pour les
                       factures ; par défaut la production simulée du producteur principal.
    """
    _verifier_prix(prix_vente, prix_achat)
    t = np.asarray(tarif, dtype=float)
    n0 = len(membres)

    # producteur principal = celui qui a le plus de surplus à vendre
    etat0 = simuler_ce(membres)
    I = int(np.argmax((1 - etat0.autocons) * etat0.prod))
    annuel_conso_prod = membres.ca_part[I] + membres.ca_ind[I] + membres.ca_admin[I]

    tab = np.zeros((nb_conso_max, 5))
    nb_surplus_max, surplus_max, autosuf_max = 1, 0.0, 0.0
    nb_opti, opti_trouve = 1, False
    autosuf_prod = autoconso_prod = autosuf_inter_prod = 0.0
    prod_I = etat0.prod[I]

    for ic in range(1, nb_conso_max + 1):
        if progression:
            progression(ic / nb_conso_max)
        etat = simuler_ce(membres.avec_consommateurs(ic, conso_consommateur))
        prod_I = etat.prod[I]

        autosuf_inter_prod = etat.autosuf_acquise[I]
        if annuel_conso_prod > 0:
            autosuf_prod, autoconso_prod = etat.autosuf[I], etat.autocons[I]
        else:
            autosuf_prod = autoconso_prod = 0.0

        k = ic - 1
        tab[k, 0] = ic                                            # nb de consommateurs

        a = etat.autosuf_acquise[n0]                              # 1er consommateur ajouté
        tab[k, 1] = a
        surplus_prod = etat.surplus_vendu[I]
        tab[k, 2] = surplus_prod

        C = conso_consommateur
        prix_conso = t[T_ENERGIE] * C
        prix_conso_ce = t[T_ENERGIE] * ((1 - a) * C) + prix_vente * a * C
        if partage_batiment:
            prix_conso_ce -= 0.8 * (t[T_DISTRIB] + t[T_TRANSPORT]) * a * C
        tab[k, 3] = prix_conso - prix_conso_ce - t[T_PARTAGE]

        Cp = annuel_conso_prod
        prix_prod = (t[T_ENERGIE] * (1 - autosuf_prod) * Cp
                     - t[T_INJECTION] * (prod_I * (1 - autoconso_prod)))
        prix_prod_ce = (t[T_ENERGIE] * (1 - autosuf_prod - autosuf_inter_prod) * Cp
                        + prix_vente * autosuf_inter_prod * Cp
                        - prix_achat * (surplus_prod * prod_I)
                        - t[T_INJECTION] * (prod_I * (1 - etat.autoconsom_f[I])))
        tab[k, 4] = prix_prod - prix_prod_ce - t[T_PARTAGE]

        if ic > 1:
            if tab[k - 1, 2] < tab[k, 2] and tab[k, 2] - tab[k - 1, 2] > 0.0001:
                nb_surplus_max, surplus_max, autosuf_max = ic, tab[k, 2], tab[k, 2]
            v_opti = tab[k, 4] - tab[k - 1, 4]
            if v_opti < 0.2 * (tab[1, 4] - tab[0, 4]) and not opti_trouve:
                nb_opti, opti_trouve = ic - 1, True
            if ic == nb_conso_max and not opti_trouve:
                nb_opti, opti_trouve = ic, True
        if nb_conso_max == 1:
            nb_opti, opti_trouve = 1, True

    return ResultatOptimisation(
        table=pd.DataFrame(tab, columns=COLONNES_OPTI),
        nb_conso_surplus_max=nb_surplus_max, surplus_max=surplus_max,
        autosuf_max=autosuf_max, nb_conso_opti=max(nb_opti, 1),
        tarif=t, prix_vente=prix_vente, prix_achat=prix_achat,
        partage_batiment=partage_batiment, annuel_conso_conso=conso_consommateur,
        annuel_conso_prod=float(annuel_conso_prod), autosuf_prod=float(autosuf_prod),
        autosuf_inter_prod=float(autosuf_inter_prod), autoconso_prod=float(autoconso_prod),
        prod_annuel=float(prod_I if prod_annuel is None else prod_annuel),
        nb_prod=nb_prod, indice_producteur=I)


def optimiser_rapide(*, puissance: float = 4.0, type_prod: str = "Solaire",
                     nb_producteurs: int = 1, conso_producteur: float = 3500.0,
                     fournisseur: str = "Total Energie", tarifs: Tarifs | None = None,
                     **kw) -> ResultatOptimisation:
    """Raccourci « Simulation rapide » (mêmes valeurs par défaut que l'application)."""
    tarifs = tarifs or charger_tarifs()
    prod_annuel = (puissance / nb_producteurs) * RENDEMENT[type_prod]
    return optimiser(Membres.simulation_rapide(puissance, type_prod, conso_producteur),
                     tarifs.pour(fournisseur), nb_prod=nb_producteurs,
                     prod_annuel=prod_annuel, **kw)


# --------------------------------------------------------------------------- #
# Factures (caluclePrix)
# --------------------------------------------------------------------------- #
def facture(res: ResultatOptimisation, avec_ce: bool, consommateur: bool) -> pd.Series:
    """Postes de facture annuelle (€) d'un consommateur ou du producteur principal,
    sans ou avec la CE, à l'optimum."""
    t = res.tarif
    C, Cp = res.annuel_conso_conso, res.annuel_conso_prod
    a_opti = res.table.iloc[res.nb_conso_opti - 1]["Autosuffisance conso."]
    ce = 1.0 if avec_ce else 0.0

    if consommateur:
        q = C
        mult = [0, 1, q, q, 1, q, q, q, q, 0, 1, 0, ce]
        if avec_ce:
            energie = (t[T_ENERGIE] * ((1 - a_opti) * C) + res.prix_vente * a_opti * C)
        else:
            energie = t[T_ENERGIE] * C
    else:
        q = Cp * (1 - res.autosuf_prod)
        mult = [0, 1, q, q, 1, q, q, q, q, 0, 1, 0, ce]
        if avec_ce:
            vendu = C * a_opti * res.nb_conso_opti / res.nb_prod
            energie = (t[T_ENERGIE] * (1 - res.autosuf_prod - res.autosuf_inter_prod) * Cp
                       + res.prix_vente * res.autosuf_inter_prod * Cp
                       - res.prix_achat * vendu
                       - t[T_INJECTION] * (res.prod_annuel * (1 - res.autoconso_prod) - vendu))
        else:
            energie = (t[T_ENERGIE] * (1 - res.autosuf_prod) * Cp
                       - t[T_INJECTION] * (res.prod_annuel * (1 - res.autoconso_prod)))

    postes = (np.array(mult) * t)[1:]        # on retire la ligne « injection »
    postes[0] = energie
    return pd.Series(postes, index=POSTES_FACTURE, name="€/an")


# --------------------------------------------------------------------------- #
# Dimensionnement de l'installation (TypedeproductionDropDown_2ValueChanged)
# --------------------------------------------------------------------------- #
def dimensionner_installation(conso_annuelle: float, type_prod: str,
                              tarif: np.ndarray) -> pd.DataFrame:
    """Temps de retour (années) en fonction de la puissance installée, pour une
    production allant de 1 % à 200 % de la consommation annuelle."""
    if type_prod not in RENDEMENT:
        raise ValueError(f"Type de production inconnu : {type_prod!r}")
    t = np.asarray(tarif, dtype=float)
    C = float(conso_annuelle)
    rend = RENDEMENT[type_prod]
    prod_inst = 0.01 * C * np.arange(1, 201)
    puissance = prod_inst / rend

    def somme_facture(volume: float) -> float:
        mult = np.array([0, 1, volume, volume, 1, volume, volume, volume, volume, 0, 1, 0, 0])
        p = (mult * t)[1:]
        p[0] = t[T_ENERGIE] * volume
        return float(p.sum())

    sans = somme_facture(C)
    retour = np.zeros(200)
    for i, pw in enumerate(puissance):
        args = {"Solaire": (0, pw, 0), "Eolien": (pw, 0, 0),
                "Cogen/Biometh.": (0, 0, pw)}[type_prod]     # (eol, sol, bio)
        autosuffi = dimdata(args[0], args[1], args[2], 0, C, 0, 0, 0)[0]
        avec = somme_facture(C * (1 - autosuffi))
        cout = np.interp(pw, PRIX_PUISSANCE_HTVA[:, 0], PRIX_PUISSANCE_HTVA[:, 1],
                         left=np.nan, right=np.nan)          # interp1 'linear' -> NaN hors plage
        with np.errstate(divide="ignore", invalid="ignore"):
            retour[i] = cout / (sans - avec)
    return pd.DataFrame({"Puissance (kW)": puissance, "Production (kWh)": prod_inst,
                         "Temps de retour (ans)": retour})


# --------------------------------------------------------------------------- #
# CE personnalisée (updateInfoCE, import / export)
# --------------------------------------------------------------------------- #
def ce_vide() -> pd.DataFrame:
    return pd.DataFrame({c: pd.Series(dtype="string" if c == "Nom" else "float64")
                         for c in COLONNES_CE})


def ajouter_membre(ce: pd.DataFrame, nom: str, conso_part: float = 3500.0,
                   conso_usine: float = 0.0, conso_admin: float = 0.0, sol: float = 0.0,
                   eol: float = 0.0, bio: float = 0.0, puissance_bat: float = 0.0,
                   capa_bat: float = 0.0) -> pd.DataFrame:
    ligne = pd.DataFrame([[nom, conso_part, conso_usine, conso_admin, sol, eol, bio,
                           puissance_bat, capa_bat]], columns=COLONNES_CE)
    return pd.concat([ce, ligne], ignore_index=True)


def importer_ce(chemin: str | Path) -> pd.DataFrame:
    """Lit une CE personnalisée (.csv, .xls, .xlsx) avec les colonnes COLONNES_CE."""
    chemin = Path(chemin)
    df = pd.read_csv(chemin, sep=None, engine="python") if chemin.suffix.lower() == ".csv" \
        else pd.read_excel(chemin)
    manquantes = [c for c in COLONNES_CE if c not in df.columns]
    if manquantes:
        raise ValueError(f"Colonnes manquantes dans {chemin.name} : {manquantes}")
    df = df[COLONNES_CE].copy()
    df["Nom"] = df["Nom"].astype("string")
    for c in COLONNES_CE[1:]:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
    return df


def exporter(df: pd.DataFrame, chemin: str | Path) -> None:
    """Écrit un DataFrame en .csv ou .xlsx (selon l'extension)."""
    chemin = Path(chemin)
    if chemin.suffix.lower() == ".csv":
        df.to_csv(chemin, index=False)
    else:
        df.to_excel(chemin, index=False)


@dataclass
class AnalyseCE:
    tableau: pd.DataFrame            # une ligne par membre
    conso_mensuelle: pd.DataFrame    # (12 mois x membres) énergie achetée dans la CE (kWh)
    nb_membres: int
    conso_totale: float
    production_estimee: float        # estimation par rendements moyens (comme l'affichage MATLAB)
    volume_echange: float            # kWh échangés dans la CE sur l'année


def verifier_producteur(ce: pd.DataFrame) -> None:
    if len(ce) == 0 or (ce["PuissanceinstalleeBio"].max() + ce["PuissanceinstalleeSol"].max()
                        + ce["PuissanceinstalleeEol"].max()) == 0:
        raise ValueError("CE personnalisée vide ou sans producteur : ajoutez au moins "
                         "un membre producteur.")


def analyser_ce_perso(ce: pd.DataFrame, tarif: np.ndarray, *, prix_vente: float = 0.09,
                      prix_achat: float = 0.08, partage_batiment: bool = False) -> AnalyseCE:
    """Équivalent de ``updateInfoCE`` : gains de chaque membre d'une CE personnalisée."""
    _verifier_prix(prix_vente, prix_achat)
    t = np.asarray(tarif, dtype=float)
    m = Membres.depuis_table(ce)
    n = len(m)
    conso_tot = m.ca_part + m.ca_ind + m.ca_admin
    production_estimee = float(m.pi_bio.sum() * RENDEMENT["Cogen/Biometh."]
                               + m.pi_sol.sum() * RENDEMENT["Solaire"]
                               + m.pi_eol.sum() * RENDEMENT["Eolien"])
    if n == 0:
        return AnalyseCE(pd.DataFrame(), pd.DataFrame(np.zeros((12, 0))), 0, 0.0, 0.0, 0.0)

    e = simuler_ce(m)
    if partage_batiment:
        gain_achat = e.autosuf_acquise * conso_tot * (
            t[T_ENERGIE] - prix_vente + 0.8 * t[T_DISTRIB] + 0.8 * t[T_TRANSPORT])
    else:
        gain_achat = e.autosuf_acquise * conso_tot * (t[T_ENERGIE] - prix_vente)
    gain_vente = e.surplus_vendu * ((prix_achat - t[T_INJECTION]) * e.prod)

    tableau = pd.DataFrame({
        "Nom": m.noms,
        "Autosuffisance (%)": e.autosuf * 100,
        "Autoconsommation (%)": e.autocons * 100,
        "Achat CE (kWh)": e.autosuf_acquise * conso_tot,
        "Achat CE (%)": e.autosuf_acquise * 100,
        "Achat CE (€)": gain_achat,
        "Surplus vendu CE (kWh)": e.surplus_vendu * e.prod,
        "Surplus vendu CE (%)": e.surplus_vendu * 100,
        "Surplus vendu CE (€)": gain_vente,
        "Gain grâce à la CE (€)": gain_achat + gain_vente - t[T_PARTAGE],
    })
    echange = e.resid - e.residf                                # (35136, n)
    mensuel = echange[:12 * QUARTS_PAR_MOIS].reshape(12, QUARTS_PAR_MOIS, n).sum(axis=1)
    conso_mensuelle = pd.DataFrame(
        mensuel, columns=m.noms,
        index=["jan", "fev", "mars", "avril", "mai", "juin",
               "juil", "aout", "sept", "oct", "nov", "dec"])
    return AnalyseCE(tableau, conso_mensuelle, n, float(conso_tot.sum()),
                     production_estimee, float(echange.sum()))


# --------------------------------------------------------------------------- #
# Graphiques (matplotlib)
# --------------------------------------------------------------------------- #
GRAPHIQUES = {
    1: "Graphique du surplus et de autosuffisance",
    2: "Graphique du Gain des Producteurs et des Consommateurs",
    3: "Graphique comparer Facture Consommateur à l'optimum",
    4: "Graphique comparer Facture Producteur à l'optimum",
}


def _barres_empilees(ax, categories, colonnes, legendes):
    """Barres empilées gérant les valeurs négatives (comme ``bar(...,'stacked')``)."""
    import matplotlib.pyplot as plt
    couleurs = plt.get_cmap("tab20").colors
    pos = np.zeros(len(categories))
    neg = np.zeros(len(categories))
    for k, (col, leg) in enumerate(zip(colonnes, legendes)):
        col = np.asarray(col, dtype=float)
        bas = np.where(col >= 0, pos, neg)
        ax.bar(categories, col, 0.4, bottom=bas, label=leg, color=couleurs[k % 20])
        pos += np.where(col >= 0, col, 0)
        neg += np.where(col < 0, col, 0)


def tracer_optimisation(res: ResultatOptimisation, graphique: int = 1, ax=None):
    """Trace l'un des 4 graphiques de l'onglet « Simulation CE »."""
    import matplotlib.pyplot as plt
    if ax is None:
        _, ax = plt.subplots(figsize=(9, 5))
    tb = res.table
    x = tb["Nbr de Conso."]
    if graphique == 1:
        ax.plot(x, tb["Autosuffisance conso."] * 100, label="Autosuffisance conso.")
        ax.plot(x, tb["Surplus Vendu CE"] * 100, label="Surplus Vendu CE")
        ax.set(xlabel="Nombre de consommateurs (en plus)", ylabel="%")
        ax.legend(loc="best")
    elif graphique == 2:
        ax.plot(x, tb["Gain conso."], label="Gain Consommateur")
        ax.plot(x, tb["Gain prod."], label="Gain Producteur")
        ax.set(xlabel="Nombre de consommateurs (en plus)", ylabel="€")
        ax.legend(loc="best")
    elif graphique in (3, 4):
        cons = graphique == 3
        sans, avec = facture(res, False, cons), facture(res, True, cons)
        _barres_empilees(ax, ["Sans CE", "Avec CE"],
                         [[sans[p], avec[p]] for p in POSTES_FACTURE], POSTES_FACTURE)
        ax.set_ylabel("€")
        ax.legend(loc="center left", bbox_to_anchor=(1, 0.5), fontsize=8)
        ax.figure.subplots_adjust(right=0.62)
    else:
        raise ValueError("graphique doit valoir 1, 2, 3 ou 4")
    ax.set_title(GRAPHIQUES[graphique])
    ax.grid(True, alpha=0.3)
    return ax


def tracer_ce_mensuelle(analyse: AnalyseCE, ax=None):
    """Énergie achetée dans la CE par mois et par membre (barres empilées)."""
    import matplotlib.pyplot as plt
    if ax is None:
        _, ax = plt.subplots(figsize=(9, 5))
    cm = analyse.conso_mensuelle
    _barres_empilees(ax, list(cm.index), [cm[c] for c in cm.columns], list(cm.columns))
    ax.set_ylabel("kWh")
    ax.legend(loc="best")
    ax.set_title("Énergie échangée dans la CE par mois")
    return ax


def tracer_dimensionnement(df: pd.DataFrame, ax=None):
    import matplotlib.pyplot as plt
    if ax is None:
        _, ax = plt.subplots(figsize=(9, 5))
    ax.plot(df["Puissance (kW)"], df["Temps de retour (ans)"])
    ax.set(xlabel="Puissance installée (kW)", ylabel="Temps de retour (ans)")
    ax.set_title("Dimensionnement de l'installation")
    ax.grid(True, alpha=0.3)
    return ax


# --------------------------------------------------------------------------- #
# Ligne de commande
# --------------------------------------------------------------------------- #
def _ajouter_options_communes(p: argparse.ArgumentParser) -> None:
    p.add_argument("--fournisseur", default="Total Energie", choices=FOURNISSEURS)
    p.add_argument("--tarifs", help="chemin de tableautarif.csv (défaut : à côté du script)")
    p.add_argument("--prix-vente", type=float, default=0.09,
                   help="prix de vente de la CE au consommateur (€/kWh)")
    p.add_argument("--prix-achat", type=float, default=0.08,
                   help="prix d'achat de la CE au producteur (€/kWh)")
    p.add_argument("--partage-batiment", action="store_true",
                   help="partage au sein d'un même bâtiment (réduction de 80 %% des frais réseau)")
    p.add_argument("--sortie", help="enregistrer le graphique (png, pdf...) au lieu de l'afficher")
    p.add_argument("--export", help="exporter le tableau de résultats (.csv ou .xlsx)")


def _afficher_ou_sauver(sortie: str | None) -> None:
    import matplotlib.pyplot as plt
    if sortie:
        plt.gcf().savefig(sortie, dpi=150, bbox_inches="tight")
        print(f"Graphique enregistré : {sortie}")
    else:
        plt.show()


def _cmd_optim(a) -> None:
    tarifs = charger_tarifs(a.tarifs)
    res = optimiser_rapide(
        puissance=a.puissance, type_prod=a.type, nb_producteurs=a.nb_producteurs,
        conso_producteur=a.conso_producteur, fournisseur=a.fournisseur, tarifs=tarifs,
        conso_consommateur=a.conso_consommateur, nb_conso_max=a.nb_conso_max,
        prix_vente=a.prix_vente, prix_achat=a.prix_achat,
        partage_batiment=a.partage_batiment)
    print(res.table.to_string(index=False, float_format=lambda v: f"{v:.4f}"))
    print()
    print(res.resume())
    if a.export:
        exporter(res.table, a.export)
    tracer_optimisation(res, a.graphique)
    _afficher_ou_sauver(a.sortie)


def _cmd_perso(a) -> None:
    ce = importer_ce(a.fichier)
    tarifs = charger_tarifs(a.tarifs)
    t = tarifs.pour(a.fournisseur)
    kw = dict(prix_vente=a.prix_vente, prix_achat=a.prix_achat,
              partage_batiment=a.partage_batiment)
    verifier_producteur(ce)
    if a.optimiser:
        res = optimiser(Membres.depuis_table(ce), t, conso_consommateur=a.conso_consommateur,
                        nb_conso_max=a.nb_conso_max, **kw)
        print(res.table.to_string(index=False, float_format=lambda v: f"{v:.4f}"))
        print()
        print(res.resume())
        if a.export:
            exporter(res.table, a.export)
        tracer_optimisation(res, a.graphique)
    else:
        an = analyser_ce_perso(ce, t, **kw)
        print(f"Membres : {an.nb_membres} | conso totale : {an.conso_totale:.0f} kWh | "
              f"production estimée : {an.production_estimee:.0f} kWh | "
              f"volume échangé : {an.volume_echange:.0f} kWh")
        print(an.tableau.to_string(index=False, float_format=lambda v: f"{v:.2f}"))
        if a.export:
            exporter(an.tableau, a.export)
        tracer_ce_mensuelle(an)
    _afficher_ou_sauver(a.sortie)


def _cmd_dim(a) -> None:
    t = charger_tarifs(a.tarifs).pour(a.fournisseur)
    df = dimensionner_installation(a.conso, a.type, t)
    print(df.iloc[::10].to_string(index=False, float_format=lambda v: f"{v:.2f}"))
    if a.export:
        exporter(df, a.export)
    tracer_dimensionnement(df)
    _afficher_ou_sauver(a.sortie)


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description="DimCE - dimensionnement de communautés d'énergie")
    sp = p.add_subparsers(dest="cmd", required=True)

    o = sp.add_parser("optim", help="simulation rapide (un producteur + consommateurs)")
    _ajouter_options_communes(o)
    o.add_argument("--puissance", type=float, default=4.0, help="puissance installée totale (kW)")
    o.add_argument("--type", default="Solaire", choices=list(RENDEMENT))
    o.add_argument("--nb-producteurs", type=int, default=1)
    o.add_argument("--conso-producteur", type=float, default=3500.0, help="kWh/an")
    o.add_argument("--conso-consommateur", type=float, default=3500.0, help="kWh/an")
    o.add_argument("--nb-conso-max", type=int, default=10)
    o.add_argument("--graphique", type=int, default=1, choices=[1, 2, 3, 4])
    o.set_defaults(func=_cmd_optim)

    c = sp.add_parser("perso", help="CE personnalisée depuis un fichier .csv/.xls/.xlsx")
    c.add_argument("fichier")
    _ajouter_options_communes(c)
    c.add_argument("--optimiser", action="store_true",
                   help="lancer l'optimisation sur cette CE (sinon : analyse des gains)")
    c.add_argument("--conso-consommateur", type=float, default=3500.0)
    c.add_argument("--nb-conso-max", type=int, default=10)
    c.add_argument("--graphique", type=int, default=1, choices=[1, 2, 3, 4])
    c.set_defaults(func=_cmd_perso)

    d = sp.add_parser("dim", help="dimensionnement de l'installation (temps de retour)")
    _ajouter_options_communes(d)
    d.add_argument("--conso", type=float, default=3500.0, help="consommation annuelle (kWh)")
    d.add_argument("--type", default="Solaire", choices=list(RENDEMENT))
    d.set_defaults(func=_cmd_dim)

    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
