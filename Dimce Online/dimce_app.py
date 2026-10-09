"""
DimCE - interface web (Streamlit).

À placer dans le même dossier que dimce.py, DataCE.mat et tableautarif.csv, puis :
    pip install streamlit numpy pandas scipy matplotlib openpyxl
    streamlit run dimce_app.py
"""
import io
import os
import threading
import tempfile
import base64
from pathlib import Path
import numpy as np
import pandas as pd
import streamlit as st
from matplotlib.figure import Figure

import dimce as d

ICO = Path(__file__).resolve().parent / "dimce.ico"
st.set_page_config(page_title="DimCE Online", page_icon=str(ICO) if ICO.exists() else None,
                   layout="wide")

# Limites pour un usage multi-utilisateurs (réglables par variables d'environnement)
NB_CONSO_MAX = int(os.environ.get("DIMCE_MAX_CONSO", 100))
NB_SIMUL_PARALLELES = int(os.environ.get("DIMCE_MAX_SIMUL", 2))


@st.cache_resource
def _verrou_simulations() -> threading.BoundedSemaphore:
    """Partagé entre toutes les sessions : limite les optimisations simultanées."""
    return threading.BoundedSemaphore(NB_SIMUL_PARALLELES)

DEFAUTS = {"fournisseur": "Total Energie", "prix_vente": 0.09, "prix_achat": 0.08,
           "partage": False, "mode": "Simulation rapide", "type_prod": "Solaire",
           "puissance": 4.0, "nb_prod": 1, "conso_prod": 3500.0,
           "conso_cons": 3500.0, "nb_max": 10}


# ----------------------------------------------------------------- état
def init_etat():
    for k, v in DEFAUTS.items():
        st.session_state.setdefault(k, v)
    if "tarif_table" not in st.session_state:
        t = d.charger_tarifs()
        st.session_state.tarif_table = t.table.copy()
        st.session_state.tarif_date = t.date
    if "ce_df" not in st.session_state:
        st.session_state.ce_df = d.ce_vide().astype({"Nom": object})
        st.session_state.ce_ver = 0
    st.session_state.setdefault("res", None)


def reinitialiser():
    for k, v in DEFAUTS.items():
        st.session_state[k] = v
    st.session_state.res = None
    t = d.charger_tarifs()
    st.session_state.tarif_table = t.table.copy()


def tarifs_courants() -> d.Tarifs:
    return d.Tarifs(st.session_state.tarif_table, st.session_state.tarif_date)


def tarif_vecteur() -> np.ndarray:
    return tarifs_courants().pour(st.session_state.fournisseur)


def prix() -> tuple[float, float]:
    pv, pa = st.session_state.prix_vente, st.session_state.prix_achat
    d._verifier_prix(pv, pa)          # lève ValueError si achat > vente
    return pv, pa


def nettoyer_ce(df: pd.DataFrame) -> pd.DataFrame:
    """Rend exploitable le tableau saisi (cases vides -> 0, lignes vides ignorées)."""
    df = df.copy()
    for c in d.COLONNES_CE[1:]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    vide = df["Nom"].isna() & df[d.COLONNES_CE[1:]].isna().all(axis=1)
    df = df[~vide].reset_index(drop=True)
    df[d.COLONNES_CE[1:]] = df[d.COLONNES_CE[1:]].fillna(0.0).clip(lower=0.0)
    df["Nom"] = [str(n) if pd.notna(n) and str(n).strip() else f"Membre {i + 1}"
                 for i, n in enumerate(df["Nom"])]
    return df


def telechargements(df: pd.DataFrame, nom: str, cle: str):
    c2, c1, _ = st.columns([1, 1, 4])
    c1.download_button("⬇ Exporter en .CSV", df.to_csv(index=False).encode("utf-8"),
                       file_name=f"{nom}.csv", mime="text/csv", key=f"{cle}_csv")
    try:
        buf = io.BytesIO()
        df.to_excel(buf, index=False)
        c2.download_button("⬇ Exporter en .XLSX", buf.getvalue(), file_name=f"{nom}.xlsx", key=f"{cle}_xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    except ImportError:
        c2.caption("(installez openpyxl pour l'export Excel)")


def figure(tracer, *args, taille=(9, 4.8), tight=True, **kw):
    fig = Figure(figsize=taille)
    ax = fig.add_subplot(111)
    tracer(*args, ax=ax, **kw)
    if tight:
        fig.tight_layout()
    return fig


def _couleur_rgb(c) -> str:
    """Convertit une couleur matplotlib (floats 0-1) en chaîne CSS 'rgb(r,g,b)'."""
    r, g, b = (int(round(255 * v)) for v in c[:3])
    return f"rgb({r},{g},{b})"


# ----------------------------------------------------------------- barre latérale
def barre_laterale():
    sb = st.sidebar
    if ICO.exists():
        ico_data = base64.b64encode(ICO.read_bytes()).decode("utf-8")
        logo = f'<img src="data:image/x-icon;base64,{ico_data}" width="40">'
    else:
        logo = ""
    sb.markdown(
        f'{logo}<span style="font-size:1.5em;font-weight:600;vertical-align:middle;'
        f'margin-left:10px;">DimCE Online</span>',
        unsafe_allow_html=True,
    )
    sb.caption("Dimensionnement de communautés d'énergie")
    sb.subheader("Données économiques")
    sb.selectbox("Fournisseur", d.FOURNISSEURS, key="fournisseur")
    sb.caption(f"Tarifs du {st.session_state.tarif_date}")
    sb.number_input("Prix de vente CE → consommateur (€/kWh)", min_value=0.0, step=0.01,
                    format="%.3f", key="prix_vente")
    sb.number_input("Prix d'achat CE ← producteur (€/kWh)", min_value=0.0, step=0.01,
                    format="%.3f", key="prix_achat")
    sb.checkbox("Partage dans un même bâtiment (−80 % des frais réseau)", key="partage")
    sb.button("Configuration par défaut", on_click=reinitialiser, use_container_width=True)
    sb.divider()
    sb.caption("Contact : dimce@ikmail.com")


# ----------------------------------------------------------------- onglet 1
def onglet_simulation():
    st.radio("Type de simulation", ["Simulation rapide", "Simulation sur CE personnalisée"],
             key="mode", horizontal=True)
    rapide = st.session_state.mode == "Simulation rapide"

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Producteur**")
        st.selectbox("Type de production", list(d.RENDEMENT), key="type_prod", disabled=not rapide)
        st.number_input("Puissance totale installée (kW)", min_value=0.1, step=0.5,
                        key="puissance", disabled=not rapide)
        st.number_input("Nombre de producteurs", min_value=1, step=1, key="nb_prod",
                        disabled=not rapide)
        st.number_input("Conso. annuelle d'un producteur (kWh)", min_value=0.0, step=100.0,
                        key="conso_prod", disabled=not rapide)
        if rapide:
            st.caption(f"Production annuelle : "
                       f"{st.session_state.puissance * d.RENDEMENT[st.session_state.type_prod]:,.0f} kWh")
        else:
            st.caption("Les producteurs sont ceux définis dans l'onglet « Personnaliser la CE ».")
    with c2:
        st.markdown("**Consommateurs**")
        st.number_input("Conso. annuelle d'un consommateur (kWh)", min_value=1.0, step=100.0,
                        key="conso_cons")
        st.number_input("Nombre maximum de consommateurs", min_value=1, max_value=NB_CONSO_MAX,
                        step=1, key="nb_max")

    if st.button("Lancer l'optimisation", type="primary"):
        lancer(rapide)

    res = st.session_state.res
    if res is None:
        st.info("Aucun résultat pour le moment : lancez l'optimisation.")
        return
    resultats(res)


def lancer(rapide: bool):
    ss = st.session_state
    try:
        pv, pa = prix()
        if rapide:
            membres = d.Membres.simulation_rapide(ss.puissance, ss.type_prod, ss.conso_prod)
            nb_prod = int(ss.nb_prod)
            prod_annuel = ss.puissance / nb_prod * d.RENDEMENT[ss.type_prod]
        else:
            ce = nettoyer_ce(ss.get("ce_edit_df", ss.ce_df))
            d.verifier_producteur(ce)
            if len(ce) > 200:
                raise ValueError("La CE personnalisée est limitée à 200 membres sur ce serveur.")
            membres, nb_prod, prod_annuel = d.Membres.depuis_table(ce), 1, None
    except ValueError as e:
        st.error(str(e))
        return
    verrou = _verrou_simulations()
    if not verrou.acquire(blocking=False):
        st.warning("Le serveur est occupé par d'autres simulations. Réessayez dans un instant.")
        return
    barre = st.progress(0.0, text="Optimisation en cours…")
    try:
        ss.res = d.optimiser(membres, tarif_vecteur(), conso_consommateur=ss.conso_cons,
                             nb_conso_max=min(int(ss.nb_max), NB_CONSO_MAX), prix_vente=pv,
                             prix_achat=pa, partage_batiment=ss.partage, nb_prod=nb_prod,
                             prod_annuel=prod_annuel,
                             progression=lambda x: barre.progress(x, text="Optimisation en cours…"))
    except Exception as e:
        st.error(f"Erreur pendant l'optimisation : {e}")
    finally:
        verrou.release()
        barre.empty()


def resultats(res: d.ResultatOptimisation):
    s, o = res.ligne_surplus_max, res.ligne_opti
    a, b = st.columns(2)
    with a:
        st.subheader(f"Au maximum d'énergie vendue : {res.nb_conso_surplus_max} conso.")
        m1, m2, m3 = st.columns(3)
        m1.metric("Surplus vendu", f"{s['Surplus Vendu CE']:.2%}")
        m2.metric("Gain producteur", f"{s['Gain prod.']:.2f} €/an")
        m3.metric("Gain conso.", f"{s['Gain conso.']:.2f} €/an")
    with b:
        st.subheader(f"À l'optimum : {res.nb_conso_opti} conso.")
        m1, m2 = st.columns(2)
        m1.metric("Gain producteur", f"{o['Gain prod.']:.2f} €/an")
        m2.metric("Gain conso.", f"{o['Gain conso.']:.2f} €/an")

    choix = st.selectbox("Graphique", list(d.GRAPHIQUES.values()))
    num = {v: k for k, v in d.GRAPHIQUES.items()}[choix]
    st.pyplot(figure(d.tracer_optimisation, res, num, taille=(10, 4.8), tight=num < 3))
    if num in (3, 4):
        st.caption("Factures à l'optimum, avec le poste « Prix énergie » ajusté selon la CE.")
        st.dataframe(pd.DataFrame({"Sans CE": d.facture(res, False, num == 3),
                                   "Avec CE": d.facture(res, True, num == 3)}).round(2),
                     use_container_width=True)

    aff = pd.DataFrame({
        "Nbr de Conso.": res.table["Nbr de Conso."].astype(int),
        "Autosuffisance conso.": res.table["Autosuffisance conso."].map("{:.2%}".format),
        "Surplus Vendu CE": res.table["Surplus Vendu CE"].map("{:.2%}".format),
        "Gain conso.": res.table["Gain conso."].map("{:.2f} €/an".format),
        "Gain prod.": res.table["Gain prod."].map("{:.2f} €/an".format)})
    st.dataframe(aff, hide_index=True, use_container_width=True)
    telechargements(res.table, "optimisation_CE", "opti")


# ----------------------------------------------------------------- onglet 2
def onglet_perso():
    st.caption("Ajoutez des lignes en bas du tableau, modifiez les cellules ou supprimez des lignes "
               "(cochez-les puis touche Suppr). Consommations en kWh/an, puissances en kW, "
               "capacité de batterie en kWh.")
    ss = st.session_state
    cfg = {"Nom": st.column_config.TextColumn("Nom")}
    libelles = {"Consommationannelleparticulier": "Conso. particulier (kWh)",
                "Consommationannelleusine": "Conso. industrie (kWh)",
                "ConsommationannelleAdministration": "Conso. administration (kWh)",
                "PuissanceinstalleeSol": "Solaire (kW)", "PuissanceinstalleeEol": "Éolien (kW)",
                "PuissanceinstalleeBio": "Bio/Cogén. (kW)", "PuissanceinstalleeBatt": "Batterie (kW)",
                "Capabat": "Capa. batterie (kWh)"}
    for c, lab in libelles.items():
        cfg[c] = st.column_config.NumberColumn(lab, min_value=0.0, format="%.1f", default=0.0)
    cfg["Consommationannelleparticulier"] = st.column_config.NumberColumn(
        libelles["Consommationannelleparticulier"], min_value=0.0, format="%.1f", default=3500.0)

    edit = st.data_editor(ss.ce_df, num_rows="dynamic", column_config=cfg, use_container_width=True,
                          key=f"ce_editor_{ss.ce_ver}")
    ss.ce_edit_df = edit

    c1, c2 = st.columns([3, 1])
    with c1:
        f = st.file_uploader("Importer une CE (.csv ou .xlsx)", type=["csv", "xlsx"])
        if f is not None and st.button("Charger ce fichier"):
            try:
                with tempfile.TemporaryDirectory() as tmp:
                    p = Path(tmp) / f.name
                    p.write_bytes(f.getvalue())
                    ss.ce_df = d.importer_ce(p).astype({"Nom": object})
                ss.ce_ver += 1
                st.rerun()
            except Exception as e:
                st.error(f"Import impossible : {e}")
    with c2:
        st.write("")
        st.write("")
        if st.button("Supprimer la CE"):
            ss.ce_df = d.ce_vide().astype({"Nom": object})
            ss.ce_ver += 1
            st.rerun()
    ce = nettoyer_ce(edit)
    telechargements(ce, "CE_personnalisee", "ce")

    st.divider()
    n = len(ce)
    conso = float(ce[d.COLONNES_CE[1:4]].sum().sum()) if n else 0.0
    prod = float(ce["PuissanceinstalleeBio"].sum() * d.RENDEMENT["Cogen/Biometh."]
                 + ce["PuissanceinstalleeSol"].sum() * d.RENDEMENT["Solaire"]
                 + ce["PuissanceinstalleeEol"].sum() * d.RENDEMENT["Eolien"]) if n else 0.0
    if n == 0 or prod == 0:
        m = st.columns(5)
        m[0].metric("Membres", n)
        m[1].metric("Consommation totale", f"{conso:,.0f} kWh")
        m[2].metric("Production estimée", f"{prod:,.0f} kWh")
        m[3].metric("Volume échangé", "0 kWh")
        m[4].metric("Volume injecté", "0 kWh")
        if n and prod == 0:
            st.info("Ajoutez au moins un membre producteur pour voir les gains de la CE.")
        return
    try:
        pv, pa = prix()
        an = d.analyser_ce_perso(ce, tarif_vecteur(), prix_vente=pv, prix_achat=pa,
                                 partage_batiment=ss.partage)
    except ValueError as e:
        st.error(str(e))
        return
    m = st.columns(5)
    m[0].metric("Membres", an.nb_membres)
    m[1].metric("Consommation totale", f"{an.conso_totale:,.0f} kWh")
    m[2].metric("Production estimée", f"{an.production_estimee:,.0f} kWh")
    m[3].metric("Volume échangé", f"{an.volume_echange:,.0f} kWh")
    m[4].metric("Volume injecté", f"{an.volume_injection:,.0f} kWh")
    # --- graphique : on récupère le dict {nom: couleur} renvoyé par tracer_ce_mensuelle
    fig = Figure(figsize=(9, 4.8))
    ax = fig.add_subplot(111)
    couleurs = d.tracer_ce_mensuelle(an, ax=ax)
    fig.tight_layout()
    st.pyplot(fig)

    # --- tableau des gains avec la colonne "Nom" colorée comme les barres empilées
    def _style_ligne(row):
        c = couleurs.get(row["Nom"])
        if c is None:
            return [""] * len(row)
        css = f"background-color: {_couleur_rgb(c)}; color: white; font-weight: bold"
        return [css] + [""] * (len(row) - 1)

    styler = (an.tableau.style
              .apply(_style_ligne, axis=1)
              .format({c: "{:.2f}" for c in an.tableau.columns[1:]}))
    st.dataframe(styler, hide_index=True, use_container_width=True)
    telechargements(an.tableau, "gains_CE", "gains")


# ----------------------------------------------------------------- onglet 3
@st.cache_data(show_spinner="Calcul en cours…")
def _dim(conso: float, type_prod: str, tarif: tuple) -> pd.DataFrame:
    return d.dimensionner_installation(conso, type_prod, np.array(tarif))


def onglet_dim():
    c1, c2, c3 = st.columns(3)
    type_dim = c1.selectbox("Type de production", list(d.RENDEMENT), key="type_dim")
    conso = c2.number_input("Consommation annuelle (kWh)", min_value=1.0, value=3500.0,
                            step=100.0, key="conso_dim")
    puiss = c3.number_input("Puissance à installer (kW)", min_value=0.1, value=4.0,
                            step=0.5, key="puiss_dim")
    df = _dim(conso, type_dim, tuple(tarif_vecteur()))
    st.caption(f"Production annuelle pour {puiss:g} kW : "
               f"{puiss * d.RENDEMENT[type_dim]:,.0f} kWh")

    def tracer(df, ax):
        d.tracer_dimensionnement(df, ax=ax)
        ax.axvline(puiss, color="tab:red", ls="--", lw=1)
    st.pyplot(figure(tracer, df))
    st.caption("Le temps de retour n'est défini que pour des puissances entre 0 et 50 kW "
               "(plage de la courbe de prix).")
    telechargements(df, "dimensionnement", "dim")


# ----------------------------------------------------------------- onglet 4
def onglet_tarifs():
    f = st.session_state.fournisseur
    st.caption(f"Tarifs du fournisseur « {f} ». Les modifications valent pour cette session "
               "(le bouton « Configuration par défaut » les annule).")
    col = st.session_state.tarif_table[[f]].copy()
    col.columns = ["Valeur"]
    edit = st.data_editor(col, use_container_width=True, key=f"tarifs_{f}", height=500)
    st.session_state.tarif_table[f] = pd.to_numeric(edit["Valeur"], errors="coerce").fillna(0.0).values


# ----------------------------------------------------------------- main
def main():
    init_etat()
    barre_laterale()
    t1, t2, t3 = st.tabs(["Simulation CE", "Personnaliser la CE", "Tarifs"])
    # t1, t2, t3, t4 = st.tabs(["Simulation CE", "Personnaliser la CE",
    #                           "Dimensionnement installation", "Tarifs"])
    # Ordre d'exécution (différent de l'ordre d'affichage) : les tarifs modifiés puis la CE
    # personnalisée doivent être lus avant les onglets qui en dépendent.
    with t3:
        onglet_tarifs()
    with t2:
        onglet_perso()
    with t1:
        onglet_simulation()
    # with t4:
    #     # onglet_dim()


main()
