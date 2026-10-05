#!/usr/bin/env python3
"""
DimCE - interface graphique PySide6 (Qt) + matplotlib.

À placer dans le même dossier que dimce.py, DataCE.mat et tableautarif.csv, puis :
    pip install PySide6
    python dimce_gui_qt.py

Nouveauté par rapport à la version Tkinter : l'optimisation tourne dans un thread
séparé (l'interface reste fluide) et peut être interrompue avec le bouton « Arrêter ».
"""
import sys
import platform
from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QAction, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFormLayout, QFrame, QGridLayout,
    QGroupBox, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QMainWindow,
    QMessageBox, QProgressBar, QPushButton, QRadioButton, QScrollArea, QSplashScreen,
    QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget, QAbstractItemView,
)

import matplotlib
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure

import dimce as d

ASSETS = d.DOSSIER / "assets"
TYPES = list(d.RENDEMENT)

STYLE = """
QMainWindow, QWidget { background: #F0F0F0; color: #262626; font-family: Tahoma; font-size: 10pt; }
QGroupBox { font-weight: bold; border: 1px solid #BBBBBB; border-radius: 4px;
            margin-top: 12px; padding-top: 8px; }
QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; color: #800000; }
QLineEdit, QComboBox { background: white; border: 1px solid #AAAAAA; padding: 2px 4px; }
QLineEdit:disabled, QComboBox:disabled { background: #E4E4E4; color: #888888; }
QPushButton { font-weight: bold; padding: 5px 12px; }
QPushButton#grand { font-size: 13pt; padding: 8px; }
QPushButton#stop { background: #800000; color: white; }
QPushButton#stop:disabled { background: #C9C9C9; color: #888888; }
QLabel#rouge { background: #800000; color: white; font-weight: bold; padding: 3px 8px; }
QLabel#clair { background: #A2142F; color: white; font-weight: bold; padding: 3px 8px; }
QLabel#titre { color: #800000; font-weight: bold; }
QProgressBar { border: 1px solid #BBBBBB; background: #DDDDDD; text-align: center; }
QProgressBar::chunk { background: #A2142F; }
QTabWidget::pane { border: 1px solid #BBBBBB; }
QTabBar::tab { padding: 6px 14px; font-weight: bold; background: #DADADA; }
QTabBar::tab:selected { background: white; color: #800000; }
QTableWidget { background: white; alternate-background-color: #F0F0F0; gridline-color: #DDDDDD; }
QHeaderView::section { font-weight: bold; padding: 3px; }
QScrollArea { border: none; }
"""
def configurer_style(app: QApplication) -> None:
    """Adapte le style selon la plateforme."""
    systeme = platform.system()

    if systeme == "Windows":
        # Windows : style natif daté + ignore les QSS → on force Fusion
        app.setStyle("Fusion")
        app.setFont(QFont("Segoe UI", 10))
        app.setStyleSheet(STYLE)
        # import qdarkstyle
        # app.setStyleSheet(qdarkstyle.load_stylesheet(qt_api="pyside6"))

    elif systeme == "Darwin":  # macOS
        app.setStyleSheet(STYLE)

    else:  # Linux et autres
        app.setStyleSheet(STYLE)

def fmt(v, dec=2):
    return f"{v:,.{dec}f}".replace(",", " ")


def icone(nom):
    p = ASSETS / f"{nom}.png"
    return QIcon(str(p)) if p.exists() else QIcon()


# --------------------------------------------------------------------------- #
# Widgets utilitaires
# --------------------------------------------------------------------------- #
class Graphique(QWidget):
    """Figure matplotlib + barre d'outils."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.fig = Figure(figsize=(6, 4), dpi=100)
        self.ax = self.fig.add_subplot(111)
        self.canvas = FigureCanvasQTAgg(self.fig)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(NavigationToolbar2QT(self.canvas, self))
        lay.addWidget(self.canvas)

    def nettoyer(self):
        self.fig.clf()
        self.ax = self.fig.add_subplot(111)
        self.canvas.draw_idle()

    def redessiner(self):
        self.canvas.draw_idle()


def creer_table(colonnes, largeur=100, hauteur_min=120):
    t = QTableWidget(0, len(colonnes))
    t.setHorizontalHeaderLabels(list(colonnes))
    t.setEditTriggers(QAbstractItemView.NoEditTriggers)
    t.setSelectionBehavior(QAbstractItemView.SelectRows)
    t.setSelectionMode(QAbstractItemView.SingleSelection)
    t.setAlternatingRowColors(True)
    t.verticalHeader().setVisible(False)
    t.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
    for i in range(len(colonnes)):
        t.setColumnWidth(i, largeur)
    t.setMinimumHeight(hauteur_min)
    return t


def remplir(t, lignes):
    t.setRowCount(0)
    t.setRowCount(len(lignes))
    for i, ligne in enumerate(lignes):
        for j, v in enumerate(ligne):
            it = QTableWidgetItem(str(v))
            it.setTextAlignment(Qt.AlignCenter)
            t.setItem(i, j, it)


class Champ:
    """Étiquette + champ numérique ajoutés à un QFormLayout."""
    def __init__(self, form, texte, defaut, largeur=90):
        self.edit = QLineEdit(str(defaut))
        self.edit.setAlignment(Qt.AlignRight)
        self.edit.setFixedWidth(largeur)
        form.addRow(texte, self.edit)

    def get(self, minimum=None, entier=False):
        txt = self.edit.text()
        try:
            v = float(txt.replace(",", "."))
        except ValueError:
            raise ValueError(f"Valeur numérique invalide : « {txt} »")
        if minimum is not None and v < minimum:
            raise ValueError(f"La valeur doit être ≥ {minimum} (reçu : {v:g}).")
        return int(round(v)) if entier else v

    def set(self, v):
        self.edit.setText(str(v))

    def setEnabled(self, b):
        self.edit.setEnabled(b)


# --------------------------------------------------------------------------- #
# Calcul dans un thread, avec annulation
# --------------------------------------------------------------------------- #
class _Annule(Exception):
    pass


class OptimWorker(QThread):
    progression = Signal(float)
    termine = Signal(object)
    erreur = Signal(str)
    annule = Signal()

    def __init__(self, membres, tarif, kwargs, parent=None):
        super().__init__(parent)
        self._membres, self._tarif, self._kwargs = membres, tarif, kwargs
        self._stop = False

    def arreter(self):
        """Demande l'arrêt : pris en compte au début de l'étape suivante."""
        self._stop = True

    def run(self):
        def prog(x):
            if self._stop:
                raise _Annule()
            self.progression.emit(float(x))

        try:
            res = d.optimiser(self._membres, self._tarif, progression=prog, **self._kwargs)
        except _Annule:
            self.annule.emit()
            return
        except Exception as e:  # noqa: BLE001
            self.erreur.emit(str(e))
            return
        self.termine.emit(res)


# --------------------------------------------------------------------------- #
# Fenêtre principale
# --------------------------------------------------------------------------- #
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("DimCE")
        ic = icone("app_icon")
        if not ic.isNull():
            self.setWindowIcon(ic)
        try:
            self.tarifs = d.charger_tarifs()
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(None, "Tarifs", f"Impossible de lire tableautarif.csv :\n{e}")
            raise SystemExit(1)

        self.ce = d.ce_vide()
        self.res = None
        self.analyse = None
        self.worker = None

        central = QWidget()
        self.setCentralWidget(central)
        lay = QVBoxLayout(central)
        lay.addWidget(self._barre_haut())
        self.tabs = QTabWidget()
        lay.addWidget(self.tabs, 1)
        self.tabs.addTab(self._onglet_simulation(), "Simulation CE")
        self.tabs.addTab(self._onglet_perso(), "Personnaliser la CE")
        self.tabs.addTab(self._onglet_tarifs(), "Tarifs")
        self.tabs.currentChanged.connect(self._changement_onglet)
        self._menu()
        
    # ------------------------------------------------------------- commun
    def _menu(self):
        mb = self.menuBar()
        f = mb.addMenu("Fichier")
        for txt, cb in [
            ("Configuration par défaut", self.defaut),
            ("Exporter les données d'optimisation",
             lambda: self._exporter(self.res.table if self.res else None)),
            ("Exporter les informations de la CE personnalisée",
             lambda: self._exporter(self.analyse.tableau if self.analyse else None)),
        ]:
            a = QAction(txt, self)
            a.triggered.connect(cb)
            f.addAction(a)
        f.addSeparator()
        q = QAction("Quitter", self)
        q.triggered.connect(self.close)
        f.addAction(q)
        h = mb.addMenu("Aide")
        ap = QAction("À propos de DimCE", self)
        ap.triggered.connect(lambda: QMessageBox.about(
            self, "À propos de DimCE",
            "DimCE est un logiciel de dimensionnement qui permet de connaître le nombre "
            "optimal et maximal de membres consommateurs d'une communauté d'énergie.\n\n"
            "Contact : dimce@ikmail.com"))
        h.addAction(ap)

    def _barre_haut(self):
        self.topbar = QGroupBox("Données économiques")
        lay = QHBoxLayout(self.topbar)
        lay.addWidget(QLabel("Fournisseur :"))
        self.cb_fourn = QComboBox()
        self.cb_fourn.addItems(d.FOURNISSEURS)
        self.cb_fourn.setCurrentText("Total Energie")
        self.cb_fourn.currentIndexChanged.connect(self._fournisseur_change)
        lay.addWidget(self.cb_fourn)
        self.lbl_date = QLabel(f"(tarifs {self.tarifs.date})")
        lay.addWidget(self.lbl_date)
        lay.addSpacing(20)
        lay.addWidget(QLabel("Prix vente CE → conso (€/kWh) :"))
        self.prix_vente = QLineEdit("0.09")
        self.prix_vente.setFixedWidth(60)
        self.prix_vente.setAlignment(Qt.AlignRight)
        self.prix_vente.editingFinished.connect(self._prix_change)
        lay.addWidget(self.prix_vente)
        lay.addSpacing(20)
        lay.addWidget(QLabel("Prix achat CE ← prod (€/kWh) :"))
        self.prix_achat = QLineEdit("0.08")
        self.prix_achat.setFixedWidth(60)
        self.prix_achat.setAlignment(Qt.AlignRight)
        self.prix_achat.editingFinished.connect(self._prix_change)
        lay.addWidget(self.prix_achat)
        lay.addSpacing(20)
        self.chk_partage = QCheckBox("Partage dans un même bâtiment")
        self.chk_partage.toggled.connect(self._prix_change)
        lay.addWidget(self.chk_partage)
        lay.addStretch(1)
        return self.topbar

    def _prix(self):
        try:
            pv = float(self.prix_vente.text().replace(",", "."))
            pa = float(self.prix_achat.text().replace(",", "."))
        except ValueError:
            raise ValueError("Les prix doivent être des nombres.")
        if pv < 0 or pa < 0:
            raise ValueError("Les prix ne peuvent pas être négatifs.")
        if pa > pv:
            raise ValueError("Le prix d'achat de la CE au producteur doit être plus petit "
                             "que le prix de vente au consommateur.")
        return pv, pa

    def _tarif(self):
        return self.tarifs.pour(self.cb_fourn.currentText())

    def _fournisseur_change(self):
        self._remplir_tarifs()
        self._prix_change()

    def _prix_change(self, *_):
        if self.tabs.currentIndex() == 1:
            self.maj_perso()

    def _changement_onglet(self, i):
        if i == 1:
            self.maj_perso()

    def _erreur(self, e):
        QMessageBox.critical(self, "Erreur", str(e))

    def _exporter(self, df):
        if df is None or len(df) == 0:
            QMessageBox.information(self, "Export", "Rien à exporter pour le moment.")
            return
        f, filtre = QFileDialog.getSaveFileName(self, "Exporter", "",
                                                "Excel (*.xlsx);;CSV (*.csv)")
        if not f:
            return
        if "." not in f.rsplit("/", 1)[-1]:
            f += ".csv" if "csv" in filtre.lower() else ".xlsx"
        try:
            d.exporter(df, f)
        except Exception as e:  # noqa: BLE001
            self._erreur(e)

    # ------------------------------------------------------- onglet Simulation
    def _onglet_simulation(self):
        page = QWidget()
        lay = QHBoxLayout(page)

        # ---- panneau gauche (défilant)
        gauche = QWidget()
        g = QVBoxLayout(gauche)

        self.panneau_params = QWidget()
        pp = QVBoxLayout(self.panneau_params)
        pp.setContentsMargins(0, 0, 0, 0)

        box = QGroupBox("Type de simulation")
        bl = QVBoxLayout(box)
        self.rb_rapide = QRadioButton("Simulation rapide")
        self.rb_perso = QRadioButton("Simulation sur CE personnalisée")
        self.rb_rapide.setChecked(True)
        self.rb_rapide.toggled.connect(self._mode_change)
        bl.addWidget(self.rb_rapide)
        bl.addWidget(self.rb_perso)
        pp.addWidget(box)

        self.box_prod = QGroupBox("Producteur")
        fp = QFormLayout(self.box_prod)
        self.cb_type = QComboBox()
        self.cb_type.addItems(TYPES)
        self.cb_type.currentIndexChanged.connect(self._maj_prod_annuelle)
        fp.addRow("Type de production", self.cb_type)
        self.f_puiss = Champ(fp, "Puissance totale installée (kW)", 4)
        self.f_nbprod = Champ(fp, "Nombre de producteurs", 1)
        self.f_conso_prod = Champ(fp, "Conso. annuelle d'un producteur (kWh)", 3500)
        for f in (self.f_puiss, self.f_nbprod):
            f.edit.textChanged.connect(self._maj_prod_annuelle)
        self.lbl_prod = QLabel("Production annuelle : -")
        fp.addRow(self.lbl_prod)
        pp.addWidget(self.box_prod)

        bc = QGroupBox("Consommateurs")
        fc = QFormLayout(bc)
        self.f_conso = Champ(fc, "Conso. annuelle d'un consommateur (kWh)", 3500)
        self.f_nbmax = Champ(fc, "Nombre maximum de consommateurs", 10)
        pp.addWidget(bc)
        g.addWidget(self.panneau_params)

        self.btn_lancer = QPushButton("Lancer l'optimisation")
        self.btn_lancer.setObjectName("grand")
        self.btn_lancer.clicked.connect(self.lancer)
        g.addWidget(self.btn_lancer)

        self.btn_stop = QPushButton("Arrêter la simulation")
        self.btn_stop.setObjectName("stop")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.arreter)
        g.addWidget(self.btn_stop)

        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setValue(0)
        g.addWidget(self.progress)
        self.lbl_statut = QLabel("")
        g.addWidget(self.lbl_statut)

        self.btn_defaut = QPushButton("Configuration par défaut")
        self.btn_defaut.setObjectName("grand")
        self.btn_defaut.clicked.connect(self.defaut)
        g.addWidget(self.btn_defaut)
        r = QGroupBox("Résultats")
        gr = QGridLayout(r)
        self.res_vars = {}
        lignes = [("Au maximum d'énergie vendue", None),
                  ("Nombre de consommateurs", "nb_max"),
                  ("Énergie produite vendue à la CE", "part_max"),
                  ("Gain par consommateur (€/an)", "gc_max"),
                  ("Gain par producteur (€/an)", "gp_max"),
                  ("À l'optimum", None),
                  ("Nombre de consommateurs", "nb_opti"),
                  ("Gain par consommateur (€/an)", "gc_opti"),
                  ("Gain par producteur (€/an)", "gp_opti")]
        for i, (txt, cle) in enumerate(lignes):
            if cle is None:
                t = QLabel(txt)
                t.setObjectName("titre")
                gr.addWidget(t, i, 0, 1, 2)
                continue
            gr.addWidget(QLabel(txt), i, 0)
            lb = QLabel("?")
            lb.setObjectName("rouge")
            lb.setAlignment(Qt.AlignCenter)
            lb.setMinimumWidth(90)
            self.res_vars[cle] = lb
            gr.addWidget(lb, i, 1)
        g.addWidget(r)
        g.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(gauche)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFixedWidth(420)
        lay.addWidget(scroll)

        # ---- partie droite
        droite = QVBoxLayout()
        self.cb_graph = QComboBox()
        self.cb_graph.addItems([d.GRAPHIQUES[i] for i in (1, 2, 3, 4)])
        self.cb_graph.setEnabled(False)
        self.cb_graph.currentIndexChanged.connect(self._tracer_opti)
        droite.addWidget(self.cb_graph)
        self.graph_opti = Graphique()
        droite.addWidget(self.graph_opti, 1)
        self.tv_opti = creer_table(("Nbr de Consommateurs", "Autosuffisance Conso.", "Surplus Vendu CE",
                                    "Gain consommateur", "Gain producteur"), 150, 160)
        self.tv_opti.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tv_opti.horizontalHeader().setStretchLastSection(False)
        self.tv_opti.horizontalHeader().setMinimumSectionSize(120)   # largeur mini par colonne
        self.tv_opti.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        droite.addWidget(self.tv_opti)
        lay.addLayout(droite, 1)

        self._mode_change()
        self._maj_prod_annuelle()
        return page

    def _mode_change(self, *_):
        rapide = self.rb_rapide.isChecked()
        for w in (self.f_puiss, self.f_nbprod, self.f_conso_prod):
            w.setEnabled(rapide)
        self.cb_type.setEnabled(rapide)
        self.tv_opti.horizontalHeaderItem(4).setText(
            "Gain producteur" if rapide else "Gain prod. principal")

    def _maj_prod_annuelle(self, *_):
        try:
            p = self.f_puiss.get(0.1)
            self.f_nbprod.get(1, entier=True)
            self.lbl_prod.setText("Production annuelle : "
                                  f"{fmt(p * d.RENDEMENT[self.cb_type.currentText()], 0)} kWh")
        except ValueError:
            self.lbl_prod.setText("Production annuelle : -")

    def defaut(self):
        if self.worker is not None:
            return
        self.cb_fourn.setCurrentText("Total Energie")
        self.prix_achat.setText("0.08")
        self.prix_vente.setText("0.09")
        self.chk_partage.setChecked(False)
        self.f_conso.set(3500)
        self.f_nbmax.set(10)
        self.f_conso_prod.set(3500)
        self.f_nbprod.set(1)
        self.f_puiss.set(4)
        self.cb_type.setCurrentText("Solaire")
        self.rb_rapide.setChecked(True)
        self._mode_change()
        self._remplir_tarifs()
        self.res = None
        self.graph_opti.nettoyer()
        remplir(self.tv_opti, [])
        self.cb_graph.setEnabled(False)
        self._maj_champs_res(None)
        self.progress.setValue(0)
        self.lbl_statut.setText("")

    # ---- lancement / arrêt
    def _set_running(self, running):
        self.panneau_params.setEnabled(not running)
        self.topbar.setEnabled(not running)
        self.btn_defaut.setEnabled(not running)
        self.btn_lancer.setEnabled(not running)
        self.btn_stop.setEnabled(running)

    def lancer(self):
        if self.worker is not None:
            return
        try:
            pv, pa = self._prix()
            conso = self.f_conso.get(1)
            nbmax = self.f_nbmax.get(1, entier=True)
            if nbmax > 10000:
                raise ValueError("Le nombre maximum de consommateurs est limité à 10 000.")
            if self.rb_rapide.isChecked():
                puiss = self.f_puiss.get(0.1)
                typ = self.cb_type.currentText()
                membres = d.Membres.simulation_rapide(puiss, typ, self.f_conso_prod.get(0))
                nbprod = self.f_nbprod.get(1, entier=True)
                prod_annuel = puiss / nbprod * d.RENDEMENT[typ]
            else:
                try:
                    d.verifier_producteur(self.ce)
                except ValueError:
                    self.tabs.setCurrentIndex(1)
                    raise
                membres, nbprod, prod_annuel = d.Membres.depuis_table(self.ce.copy()), 1, None
        except ValueError as e:
            return self._erreur(e)

        if QMessageBox.question(self, "Confirmation",
                                "Voulez-vous lancer l'optimisation ?") != QMessageBox.Yes:
            return

        kwargs = dict(conso_consommateur=conso, nb_conso_max=nbmax, prix_vente=pv,
                      prix_achat=pa, partage_batiment=self.chk_partage.isChecked(),
                      nb_prod=nbprod, prod_annuel=prod_annuel)
        self.worker = OptimWorker(membres, self._tarif(), kwargs, self)
        self.worker.progression.connect(self._maj_progression)
        self.worker.termine.connect(self._optim_terminee)
        self.worker.erreur.connect(self._optim_erreur)
        self.worker.annule.connect(self._optim_annulee)
        self.worker.finished.connect(self._worker_fini)
        self.progress.setValue(0)
        self.lbl_statut.setText("Simulation en cours…")
        self._set_running(True)
        self.worker.start()

    def arreter(self):
        if self.worker is not None:
            self.worker.arreter()
            self.btn_stop.setEnabled(False)
            self.lbl_statut.setText("Arrêt en cours (fin de l'étape courante)…")

    def _maj_progression(self, x):
        self.progress.setValue(int(x * 1000))

    def _worker_fini(self):
        w, self.worker = self.worker, None
        if w is not None:
            w.deleteLater()
        self._set_running(False)

    def _optim_erreur(self, msg):
        self.lbl_statut.setText("Erreur pendant la simulation.")
        self.progress.setValue(0)
        self._erreur(msg)

    def _optim_annulee(self):
        self.lbl_statut.setText("Simulation arrêtée par l'utilisateur.")
        self.progress.setValue(0)

    def _optim_terminee(self, res):
        self.res = res
        self.progress.setValue(1000)
        self.lbl_statut.setText("Simulation terminée.")
        remplir(self.tv_opti, [(int(r[0]), f"{r[1]:.2%}", f"{r[2]:.2%}",
                                f"{r[3]:.2f} €/an", f"{r[4]:.2f} €/an")
                               for r in res.table.itertuples(index=False)])
        self.cb_graph.blockSignals(True)
        self.cb_graph.setCurrentIndex(0)
        self.cb_graph.blockSignals(False)
        self.cb_graph.setEnabled(True)
        self._tracer_opti()
        self._maj_champs_res(res)

    def _maj_champs_res(self, res):
        v = self.res_vars
        if res is None:
            for lb in v.values():
                lb.setText("?")
            return
        s, o = res.ligne_surplus_max, res.ligne_opti
        v["nb_max"].setText(str(res.nb_conso_surplus_max))
        v["part_max"].setText(f"{s['Surplus Vendu CE']:.2%}")
        v["gc_max"].setText(f"{s['Gain conso.']:.2f}")
        v["gp_max"].setText(f"{s['Gain prod.']:.2f}")
        v["nb_opti"].setText(str(res.nb_conso_opti))
        v["gc_opti"].setText(f"{o['Gain conso.']:.2f}")
        v["gp_opti"].setText(f"{o['Gain prod.']:.2f}")

    def _tracer_opti(self, *_):
        if not self.res:
            return
        num = self.cb_graph.currentIndex() + 1
        self.graph_opti.nettoyer()
        d.tracer_optimisation(self.res, num, ax=self.graph_opti.ax)
        if num < 3:
            self.graph_opti.fig.tight_layout()
        else:
            self.graph_opti.fig.subplots_adjust(left=0.1, right=0.6)
        self.graph_opti.redessiner()

    # ------------------------------------------------------ onglet CE perso
    def _onglet_perso(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        haut = QHBoxLayout()
        lay.addLayout(haut)

        f = QGroupBox("Ajouter un membre")
        fl = QFormLayout(f)
        self.nom = QLineEdit()
        self.nom.setFixedWidth(110)
        fl.addRow("Nom", self.nom)
        self.m = {}
        champs = [("Conso. particulier (kWh/an)", 3500, "part"),
                  ("Conso. industrie (kWh/an)", 0, "usine"),
                  ("Conso. administration (kWh/an)", 0, "admin"),
                  ("Solaire (kW)", 0, "sol"), ("Éolien (kW)", 0, "eol"),
                  ("Bio/Cogén. (kW)", 0, "bio"),
                  ("Puissance batterie (kW)", 0, "pbat"), ("Capacité batterie (kWh)", 0, "cbat")]
        for lab, dv, k in champs:
            self.m[k] = Champ(fl, lab, dv, 80)
        b = QPushButton("Ajouter membre")
        b.setIcon(icone("user"))
        b.clicked.connect(self.ajouter)
        fl.addRow(b)
        haut.addWidget(f)

        mid = QVBoxLayout()
        cols = ("Nom", "Conso. particulier", "Conso. usine", "Conso. admin.", "Solaire kW",
                "Éolien kW", "Bio kW", "Batterie kW", "Capa. batt. kWh")
        self.tv_ce = creer_table(cols, 95, 200)
        header = self.tv_ce.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(120)   # largeur mini par colonne
        self.tv_ce.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.tv_ce.cellDoubleClicked.connect(self._edit_cellule)
        mid.addWidget(self.tv_ce, 1)
        bt = QHBoxLayout()
        for txt, cmd, ico in [("Effacer le membre", self.suppr_membre, "delete"),
                              ("Effacer la CE", self.suppr_ce, "cancel"),
                              ("Importer Fichier CE", self.importer, "import"),
                              ("Exporter Fichier CE", self.exporter_ce, "export")]:
            bb = QPushButton(txt)
            bb.setIcon(icone(ico))
            bb.clicked.connect(cmd)
            bt.addWidget(bb)
        bt.addStretch(1)
        mid.addLayout(bt)
        mid.addWidget(QLabel("Astuce : double-cliquez sur une cellule pour la modifier."))
        haut.addLayout(mid, 1)

        info = QGroupBox("Informations sur la CE")
        il = QHBoxLayout(info)
        self.info_vars = {}
        for txt, cle in [("Nombre de membres : ", "n"), ("Consommation totale : ", "conso"),
                         ("Production totale : ", "prod"), ("Volume total échangé CE : ", "vol"),
                         ("Volume injecté : ", "rest")]:
            il.addWidget(QLabel(txt))
            lb = QLabel("0")
            lb.setObjectName("clair")
            lb.setAlignment(Qt.AlignCenter)
            lb.setMinimumWidth(110)
            self.info_vars[cle] = lb
            il.addWidget(lb)
        lay.addWidget(info)

        bas = QHBoxLayout()
        self.graph_ce = Graphique()
        bas.addWidget(self.graph_ce, 1)
        cols2 = ("Nom", "Autosuffisance", "Autoconsommation", "Achat CE", "Surplus vendu CE",
                 "Gain grâce à la CE")
        self.tv_gain = creer_table(cols2, 150, 200)
        bas.addWidget(self.tv_gain, 1)
        lay.addLayout(bas, 1)
        self._rafraichir_table_ce()
        return page

    def _lire_membre(self):
        nom = self.nom.text().strip()
        if not nom:
            raise ValueError("Veuillez donner un nom au membre.")
        return nom, {k: self.m[k].get(0) for k in self.m}

    def ajouter(self):
        try:
            nom, v = self._lire_membre()
        except ValueError as e:
            return self._erreur(e)
        self.ce = d.ajouter_membre(self.ce, nom, v["part"], v["usine"], v["admin"], v["sol"],
                                   v["eol"], v["bio"], v["pbat"], v["cbat"])
        self.nom.clear()
        for k in self.m:
            self.m[k].set(3500 if k == "part" else 0)
        self.maj_perso()

    def suppr_membre(self):
        i = self.tv_ce.currentRow()
        if i < 0:
            return QMessageBox.information(self, "Suppression", "Sélectionnez d'abord un membre.")
        if QMessageBox.question(self, "Confirmation",
                                "Voulez-vous supprimer le membre sélectionné ?") == QMessageBox.Yes:
            self.ce = self.ce.drop(self.ce.index[i]).reset_index(drop=True)
            self.maj_perso()

    def suppr_ce(self):
        if QMessageBox.question(self, "Confirmation",
                                "Voulez-vous supprimer cette CE ?") == QMessageBox.Yes:
            self.ce = d.ce_vide()
            self.maj_perso()

    def importer(self):
        f, _ = QFileDialog.getOpenFileName(self, "Importer une CE", "",
                                           "Fichiers CE (*.xlsx *.xls *.csv)")
        if f:
            try:
                self.ce = d.importer_ce(f)
            except Exception as e:  # noqa: BLE001
                return self._erreur(e)
            self.maj_perso()

    def exporter_ce(self):
        self._exporter(self.ce)

    def _edit_cellule(self, i, col):
        nom_col = d.COLONNES_CE[col]
        actuel = self.ce.iloc[i][nom_col]
        v, ok = QInputDialog.getText(self, "Modifier", f"{nom_col} :", text=str(actuel))
        if not ok:
            return
        if col == 0:
            self.ce.at[i, "Nom"] = v
        else:
            try:
                x = float(v.replace(",", "."))
                if x < 0:
                    raise ValueError
            except ValueError:
                return self._erreur("Valeur numérique positive attendue.")
            self.ce.at[i, nom_col] = x
        self.maj_perso()

    def _rafraichir_table_ce(self):
        remplir(self.tv_ce, [(r[0],) + tuple(f"{x:g}" for x in r[1:])
                             for r in self.ce.itertuples(index=False)])

    def _maj_info(self, n, conso, prod, volume, rest):
        v = self.info_vars
        v["n"].setText(str(n))
        v["conso"].setText(f"{fmt(conso, 0)} kWh")
        v["prod"].setText(f"{fmt(prod, 0)} kWh")
        v["vol"].setText(f"{fmt(volume, 0)} kWh")
        v["rest"].setText(f"{fmt(rest, 0)} kWh")

    def maj_perso(self):
        """Équivalent de updateInfoCE."""
        self._rafraichir_table_ce()
        self.graph_ce.nettoyer()
        remplir(self.tv_gain, [])
        self.analyse = None
        n = len(self.ce)
        conso = float(self.ce[d.COLONNES_CE[1:4]].sum().sum()) if n else 0.0
        prod = float(self.ce["PuissanceinstalleeBio"].sum() * d.RENDEMENT["Cogen/Biometh."]
                     + self.ce["PuissanceinstalleeSol"].sum() * d.RENDEMENT["Solaire"]
                     + self.ce["PuissanceinstalleeEol"].sum() * d.RENDEMENT["Eolien"]) if n else 0.0
        if n == 0 or prod == 0:
            self._maj_info(n, conso, prod, 0.0, 0.0)
            return
        try:
            pv, pa = self._prix()
            an = d.analyser_ce_perso(self.ce, self._tarif(), prix_vente=pv, prix_achat=pa,
                                     partage_batiment=self.chk_partage.isChecked())
        except Exception as e:  # noqa: BLE001
            self._maj_info(n, conso, prod, 0.0, 0.0)
            return self._erreur(e)
        self.analyse = an
        self._maj_info(n, conso, prod, an.volume_echange, an.volume_injection)
        remplir(self.tv_gain, [
            (r["Nom"], f"{r['Autosuffisance (%)']:.2f}%", f"{r['Autoconsommation (%)']:.2f}%",
             f"{r['Achat CE (kWh)']:.0f} kWh ({r['Achat CE (%)']:.2f}%) {r['Achat CE (€)']:.0f} €",
             f"{r['Surplus vendu CE (kWh)']:.0f} kWh ({r['Surplus vendu CE (%)']:.2f}%) "
             f"{r['Surplus vendu CE (€)']:.0f} €", f"{r['Gain grâce à la CE (€)']:.0f} €")
            for _, r in an.tableau.iterrows()])
        d.tracer_ce_mensuelle(an, ax=self.graph_ce.ax)
        self.graph_ce.fig.tight_layout()
        self.graph_ce.redessiner()

    # ---------------------------------------------------------- onglet tarifs
    def _onglet_tarifs(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.addWidget(QLabel("Tarifs du fournisseur choisi (double-clic pour modifier une "
                             "valeur, valable pour cette session)."))
        self.tv_tarif = creer_table(("Poste", "Valeur"), 200, 300)
        self.tv_tarif.setColumnWidth(0, 420)
        self.tv_tarif.horizontalHeader().setStretchLastSection(True)
        self.tv_tarif.cellDoubleClicked.connect(self._edit_tarif)
        lay.addWidget(self.tv_tarif, 1)
        self._remplir_tarifs()
        return page

    def _remplir_tarifs(self):
        v = self._tarif()
        remplir(self.tv_tarif, [(n, f"{x:g}") for n, x in zip(d.LIGNES_TARIF, v)])
        self.lbl_date.setText(f"(tarifs {self.tarifs.date})")

    def _edit_tarif(self, i, _col):
        actuel = self._tarif()[i]
        v, ok = QInputDialog.getText(self, "Modifier le tarif", d.LIGNES_TARIF[i],
                                     text=f"{actuel:g}")
        if not ok:
            return
        try:
            x = float(v.replace(",", "."))
        except ValueError:
            x = 0.0                                   # comme dans MATLAB : invalide -> 0
        self.tarifs.table.iloc[i, self.tarifs.table.columns.get_loc(
            self.cb_fourn.currentText())] = x
        self._remplir_tarifs()
        self._prix_change()

    # ------------------------------------------------------------- fermeture
    def closeEvent(self, ev):
        if self.worker is not None:
            self.worker.arreter()
            self.worker.wait()
        super().closeEvent(ev)


def main():
    matplotlib.use("QtAgg")
    app = QApplication(sys.argv)
    configurer_style(app)
    win = MainWindow()

    splash_png = ASSETS / "splash.png"
    if splash_png.exists():
        splash = QSplashScreen(QPixmap(str(splash_png)))
        splash.show()
        app.processEvents()

        def ouvrir():
            splash.close()
            win.showMaximized()
        QTimer.singleShot(5000, ouvrir)
    else:
        win.showMaximized()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
