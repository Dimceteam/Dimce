#!/usr/bin/env python3
"""
DimCE - interface graphique (Tkinter + matplotlib).

À placer dans le même dossier que dimce.py, DataCE.mat et tableautarif.csv, puis :
    python dimce_gui.py
"""
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure

import dimce as d

# --- Charte graphique de l'application MATLAB d'origine ---------------------------------
ROUGE_FONCE = "#800000"     # [0.502 0 0]      champs de résultats
ROUGE_TITRE = "#8C0000"     # [0.549 0 0]      bandeau de titre
ROUGE_CLAIR = "#A2142F"     # [0.6353 0.0784 0.1843]  infos CE, production, lignes du tableau
GRIS_FOND = "#F0F0F0"       # [0.9412 ...]     fond des fenêtres
TEXTE = "#262626"           # [0.149 ...]
POLICE = "Tahoma"           # (repli automatique si la police est absente)
ASSETS = d.DOSSIER / "assets"

TYPES = list(d.RENDEMENT)


def fmt(v, dec=2):
    return f"{v:,.{dec}f}".replace(",", " ")


class Graphique(ttk.Frame):
    """Figure matplotlib + barre d'outils."""
    def __init__(self, parent):
        super().__init__(parent)
        self.fig = Figure(figsize=(6, 4), dpi=100)
        self.ax = self.fig.add_subplot(111)
        self.canvas = FigureCanvasTkAgg(self.fig, master=self)
        NavigationToolbar2Tk(self.canvas, self, pack_toolbar=True).update()
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

    def nettoyer(self):
        self.fig.clf()
        self.ax = self.fig.add_subplot(111)
        self.canvas.draw_idle()

    def redessiner(self):
        self.canvas.draw_idle()


def tableau(parent, colonnes, hauteur=8, largeur=110):
    frame = ttk.Frame(parent)
    tv = ttk.Treeview(frame, columns=colonnes, show="headings", height=hauteur,
                      selectmode="browse")
    for c in colonnes:
        tv.heading(c, text=c)
        tv.column(c, width=largeur, anchor="center")
    sy = ttk.Scrollbar(frame, orient="vertical", command=tv.yview)
    sx = ttk.Scrollbar(frame, orient="horizontal", command=tv.xview)
    tv.configure(yscrollcommand=sy.set, xscrollcommand=sx.set)
    tv.grid(row=0, column=0, sticky="nsew")
    sy.grid(row=0, column=1, sticky="ns")
    sx.grid(row=1, column=0, sticky="ew")
    frame.rowconfigure(0, weight=1)
    frame.columnconfigure(0, weight=1)
    return frame, tv
class ScrollableFrame(ttk.Frame):
    """Frame avec barre de défilement verticale (et horizontale optionnelle).

    Le contenu doit être placé dans `self.inner`, pas dans `self`.
    """
    def __init__(self, parent, vertical=True, horizontal=False, **kwargs):
        super().__init__(parent, **kwargs)

        self.canvas = tk.Canvas(self, highlightthickness=0,
                                background=GRIS_FOND, borderwidth=0)
        self.vsb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.hsb = ttk.Scrollbar(self, orient="horizontal", command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=self.vsb.set,
                              xscrollcommand=self.hsb.set)

        self.canvas.grid(row=0, column=0, sticky="nsew")
        if vertical:
            self.vsb.grid(row=0, column=1, sticky="ns")
        if horizontal:
            self.hsb.grid(row=1, column=0, sticky="ew")

        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        # Frame interne : c'est ICI que tu ajoutes tes widgets
        self.inner = ttk.Frame(self.canvas)
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")

        self.inner.bind("<Configure>", self._on_inner_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)

        # Molette : active seulement quand la souris est au-dessus du canvas
        self.canvas.bind("<Enter>", self._activer_molette)
        self.canvas.bind("<Leave>", self._desactiver_molette)

        # Adapter la largeur du inner au canvas (si pas de scroll horizontal)
        self._horizontal = horizontal

    def _on_inner_configure(self, _):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        if not self._horizontal:
            self.canvas.itemconfig(self._win, width=event.width)

    def _activer_molette(self, _):
        self.canvas.bind_all("<MouseWheel>", self._molette)
        self.canvas.bind_all("<Button-4>", self._molette)
        self.canvas.bind_all("<Button-5>", self._molette)

    def _desactiver_molette(self, _):
        self.canvas.unbind_all("<MouseWheel>")
        self.canvas.unbind_all("<Button-4>")
        self.canvas.unbind_all("<Button-5>")

    def _molette(self, event):
        if event.num == 4:
            delta = -1
        elif event.num == 5:
            delta = 1
        else:
            delta = -1 if event.delta > 0 else 1
        self.canvas.yview_scroll(delta, "units")

def remplir(tv, lignes):
    """Remplit un tableau ; les lignes paires (2e, 4e...) portent le tag « impair »
    (utilisé par le tableau des gains : lignes alternées blanc / rouge, comme l'original)."""
    tv.delete(*tv.get_children())
    for i, l in enumerate(lignes):
        tv.insert("", "end", values=l, tags=("impair",) if i % 2 else ())


def appliquer_style(root):
    root.configure(bg=GRIS_FOND)
    st = ttk.Style(root)
    try:
        st.theme_use("clam")               # seul thème dont on peut changer toutes les couleurs
    except tk.TclError:
        pass
    st.configure(".", background=GRIS_FOND, foreground=TEXTE, font=(POLICE, 10))
    st.configure("TLabelframe", background=GRIS_FOND)
    st.configure("TLabelframe.Label", background=GRIS_FOND, foreground=ROUGE_FONCE,
                 font=(POLICE, 10, "bold"))
    st.configure("TButton", font=(POLICE, 10, "bold"), padding=5)
    st.configure("Grand.TButton", font=(POLICE, 13, "bold"), padding=8)
    st.configure("Icone.TButton", font=(POLICE, 10, "bold"), padding=4)
    st.configure("TNotebook", background=GRIS_FOND)
    st.configure("TNotebook.Tab", font=(POLICE, 10, "bold"), padding=(14, 6))
    st.map("TNotebook.Tab", background=[("selected", "white"), ("!selected", "#DADADA")],
           foreground=[("selected", ROUGE_FONCE), ("!selected", TEXTE)])
    st.configure("Horizontal.TProgressbar", background=ROUGE_CLAIR, troughcolor="#DDDDDD")
    st.configure("Treeview", background="white", fieldbackground="white", rowheight=22)
    st.configure("Treeview.Heading", font=(POLICE, 10, "bold"))
    st.configure("Banniere.TLabel", background=ROUGE_TITRE, foreground="white",
                 font=(POLICE, 20, "bold"), anchor="center", justify="center", padding=8)
    st.configure("Rouge.TLabel", background=ROUGE_FONCE, foreground="white",
                 font=(POLICE, 11, "bold"), anchor="center", padding=(8, 3))
    st.configure("Clair.TLabel", background=ROUGE_CLAIR, foreground="white",
                 font=(POLICE, 11, "bold"), anchor="center", padding=(8, 3))


class Champ:
    """Étiquette + champ numérique."""
    def __init__(self, parent, row, texte, defaut, largeur=10):
        ttk.Label(parent, text=texte).grid(row=row, column=0, sticky="w", pady=2)
        self.var = tk.StringVar(value=str(defaut))
        self.entry = ttk.Entry(parent, textvariable=self.var, width=largeur, justify="right")
        self.entry.grid(row=row, column=1, sticky="e", padx=(8, 0), pady=2)

    def get(self, minimum=None, entier=False):
        try:
            v = float(self.var.get().replace(",", "."))
        except ValueError:
            raise ValueError(f"Valeur numérique invalide : « {self.var.get()} »")
        if minimum is not None and v < minimum:
            raise ValueError(f"La valeur doit être ≥ {minimum} (reçu : {v:g}).")
        return int(round(v)) if entier else v

    def set(self, v):
        self.var.set(str(v))


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self._imgs = {}
        self.withdraw()                    # le temps d'afficher l'écran de démarrage
        appliquer_style(self)
        self.title("DimCE")
        self.attributes('-zoomed', True)
        icone = self.img("app_icon")       # icône de fenêtre = carte des 9 communes
        if icone:
            self.iconphoto(True, icone)
        splash = self._splash()
        try:
            self.tarifs = d.charger_tarifs()
        except Exception as e:                       # fichier manquant, etc.
            messagebox.showerror("Tarifs", f"Impossible de lire tableautarif.csv :\n{e}")
            raise SystemExit(1)
        self.ce = d.ce_vide()
        self.res = None            # dernier ResultatOptimisation
        self.analyse = None        # dernière AnalyseCE
        self.dim_df = None
        self.fournisseur = tk.StringVar(value="Total Energie")
        self.partage = tk.BooleanVar(value=False)
        self.prix_vente = tk.StringVar(value="0.09")
        self.prix_achat = tk.StringVar(value="0.08")

        self._barre_haut()
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        self._onglet_simulation()
        self._onglet_perso()
        # self._onglet_dim()
        self._onglet_tarifs()
        self.nb.bind("<<NotebookTabChanged>>", self._changement_onglet)
        self._menu()
        if splash:
            self.update()
            self.after(1500, lambda: (splash.destroy(), self.deiconify()))
        else:
            self.deiconify()

    # ------------------------------------------------------------- images
    def img(self, nom):
        """PhotoImage depuis assets/ (None si absente : l'appli reste utilisable)."""
        if nom not in self._imgs:
            try:
                self._imgs[nom] = tk.PhotoImage(file=str(ASSETS / f"{nom}.png"))
            except tk.TclError:
                self._imgs[nom] = None
        return self._imgs[nom]

    def _splash(self):
        im = self.img("splash")
        if not im:
            return None
        w = tk.Toplevel(self)
        w.overrideredirect(True)
        tk.Label(w, image=im, bd=0).pack()
        w.update_idletasks()
        x = (w.winfo_screenwidth() - im.width()) // 2
        y = (w.winfo_screenheight() - im.height()) // 2
        w.geometry(f"{im.width()}x{im.height()}+{x}+{y}")
        w.update()
        return w

    # ------------------------------------------------------------------ commun
    def _menu(self):
        m = tk.Menu(self)
        f = tk.Menu(m, tearoff=0)
        f.add_command(label="Configuration par défaut", command=self.defaut)
        f.add_command(label="Exporter les données d'optimisation",
                      command=lambda: self._exporter(self.res.table if self.res else None))
        f.add_command(label="Exporter les informations de la CE personnalisée",
                      command=lambda: self._exporter(self.analyse.tableau if self.analyse else None))
        f.add_separator()
        f.add_command(label="Quitter", command=self.destroy)
        m.add_cascade(label="Fichier", menu=f)
        a = tk.Menu(m, tearoff=0)
        a.add_command(label="À propos de DimCE", command=lambda: messagebox.showinfo(
            "À propos de DimCE",
            "DimCE est un logiciel de dimensionnement qui permet de connaître le nombre "
            "optimal et maximal de membres consommateurs d'une communauté d'énergie.\n\n"
            "Contact : dimce@ikmail.com"))
        m.add_cascade(label="Aide", menu=a)
        self.config(menu=m)

    def _barre_haut(self):
        b = ttk.LabelFrame(self, text="Données économiques")
        b.pack(fill="x", padx=6, pady=6)
        ttk.Label(b, text="Fournisseur :").pack(side="left", padx=(8, 2))
        cb = ttk.Combobox(b, textvariable=self.fournisseur, values=d.FOURNISSEURS,
                          state="readonly", width=14)
        cb.pack(side="left")
        cb.bind("<<ComboboxSelected>>", lambda e: self._fournisseur_change())
        self.lbl_date = ttk.Label(b, text=f"(tarifs {self.tarifs.date})")
        self.lbl_date.pack(side="left", padx=6)
        ttk.Label(b, text="Prix vente CE → conso (€/kWh) :").pack(side="left", padx=(20, 2))
        ttk.Entry(b, textvariable=self.prix_vente, width=7, justify="right").pack(side="left")
        ttk.Label(b, text="Prix achat CE ← prod (€/kWh) :").pack(side="left", padx=(20, 2))
        ttk.Entry(b, textvariable=self.prix_achat, width=7, justify="right").pack(side="left")
        ttk.Checkbutton(b, text="Partage dans un même bâtiment", variable=self.partage,
                        command=self._prix_change).pack(side="left", padx=20)
        for v in (self.prix_vente, self.prix_achat):
            v.trace_add("write", lambda *a: None)

    def _prix(self):
        """Lit et valide les deux prix (règle : achat ≤ vente)."""
        try:
            pv = float(self.prix_vente.get().replace(",", "."))
            pa = float(self.prix_achat.get().replace(",", "."))
        except ValueError:
            raise ValueError("Les prix doivent être des nombres.")
        if pv < 0 or pa < 0:
            raise ValueError("Les prix ne peuvent pas être négatifs.")
        if pa > pv:
            raise ValueError("Le prix d'achat de la CE au producteur doit être plus petit "
                             "que le prix de vente au consommateur.")
        return pv, pa

    def _tarif(self):
        return self.tarifs.pour(self.fournisseur.get())

    def _fournisseur_change(self):
        self._remplir_tarifs()
        self._prix_change()

    def _prix_change(self):
        if self.nb.index(self.nb.select()) == 1:
            self.maj_perso()

    def _changement_onglet(self, _):
        if self.nb.index(self.nb.select()) == 1:
            self.maj_perso()

    def _erreur(self, e):
        messagebox.showerror("Erreur", str(e), parent=self)

    def _exporter(self, df):
        if df is None or len(df) == 0:
            messagebox.showinfo("Export", "Rien à exporter pour le moment.")
            return
        f = filedialog.asksaveasfilename(defaultextension=".xlsx",
                                         filetypes=[("Excel", "*.xlsx"), ("CSV", "*.csv")])
        if f:
            try:
                d.exporter(df, f)
            except Exception as e:
                self._erreur(e)

    # ------------------------------------------------------- onglet Simulation
    def _onglet_simulation(self):
        t = ttk.Frame(self.nb)
        self.nb.add(t, text="Simulation CE")
   #     ttk.Label(t, text="DimCE : Interface d'optimisation pour Communauté d'énergie",
   #               style="Banniere.TLabel").pack(side="top", fill="x")
        g = ttk.Frame(t)
        g.pack(side="left", fill="y", padx=8, pady=8)

        self.mode = tk.StringVar(value="rapide")
        box = ttk.LabelFrame(g, text="Type de simulation")
        box.pack(fill="x")
        ttk.Radiobutton(box, text="Simulation rapide", value="rapide", variable=self.mode,
                        command=self._mode_change).pack(anchor="w")
        ttk.Radiobutton(box, text="Simulation sur CE personnalisée", value="perso",
                        variable=self.mode, command=self._mode_change).pack(anchor="w")

        p = ttk.LabelFrame(g, text="Producteur")
        p.pack(fill="x", pady=8)
        self.type_prod = tk.StringVar(value="Solaire")
        ttk.Label(p, text="Type de production").grid(row=0, column=0, sticky="w")
        self.cb_type = ttk.Combobox(p, textvariable=self.type_prod, values=TYPES,
                                    state="readonly", width=14)
        self.cb_type.grid(row=0, column=1, padx=(8, 0))
        self.cb_type.bind("<<ComboboxSelected>>", lambda e: self._maj_prod_annuelle())
        self.f_puiss = Champ(p, 1, "Puissance totale installée (kW)", 4)
        self.f_nbprod = Champ(p, 2, "Nombre de producteurs", 1)
        self.f_conso_prod = Champ(p, 3, "Conso. annuelle d'un producteur (kWh)", 3500)
        for f in (self.f_puiss, self.f_nbprod):
            f.var.trace_add("write", lambda *a: self._maj_prod_annuelle())
        self.lbl_prod = ttk.Label(p, text="Production annuelle : -")
        self.lbl_prod.grid(row=4, column=0, columnspan=2, sticky="w", pady=(4, 0))

        c = ttk.LabelFrame(g, text="Consommateurs")
        c.pack(fill="x")
        self.f_conso = Champ(c, 0, "Conso. annuelle d'un consommateur (kWh)", 3500)
        self.f_nbmax = Champ(c, 1, "Nombre maximum de consommateurs", 10)

        self.btn_lancer = ttk.Button(g, text="Lancer l'optimisation", style="Grand.TButton",
                                     command=self.lancer)
        self.btn_lancer.pack(fill="x", pady=(12, 2))
        self.progress = ttk.Progressbar(g, maximum=1.0)
        self.progress.pack(fill="x")
        ttk.Button(g, text="Configuration par défaut", style="Grand.TButton",
                   command=self.defaut).pack(fill="x", pady=(6, 2))
        ttk.Button(g, text="Quitter", style="Grand.TButton",
                   command=self.destroy).pack(fill="x", pady=(2, 6))

        r_container = ScrollableFrame(g, vertical=True, horizontal=False)
        r_container.pack(side="left", fill="y", padx=4, pady=8)
        r = ttk.LabelFrame(r_container.inner, text="Résultats")
        #r.pack(fill="both", expand=True)
        r.columnconfigure(0, weight=1)
        # r = ttk.LabelFrame(g, text="Résultats")
        r.pack(fill="x", pady=4)
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
                ttk.Label(r, text=txt, font=(POLICE, 10, "bold"), foreground=ROUGE_FONCE
                          ).grid(row=i, column=0, columnspan=2, sticky="w", padx=6, pady=(6, 0))
                continue
            ttk.Label(r, text=txt).grid(row=i, column=0, sticky="w", padx=6, pady=2)
            self.res_vars[cle] = tk.StringVar(value="?")
            ttk.Label(r, textvariable=self.res_vars[cle], style="Rouge.TLabel", width=11
                      ).grid(row=i, column=1, padx=6, pady=2)

        droite = ttk.Frame(t)
        droite.pack(side="left", fill="both", expand=True, padx=(0, 8), pady=8)
        self.choix_graph = tk.StringVar(value=d.GRAPHIQUES[1])
        self.cb_graph = ttk.Combobox(droite, textvariable=self.choix_graph, state="disabled",
                                     values=[d.GRAPHIQUES[i] for i in (1, 2, 3, 4)])
        self.cb_graph.pack(fill="x")
        self.cb_graph.bind("<<ComboboxSelected>>", lambda e: self._tracer_opti())
        self.graph_opti = Graphique(droite)
        self.graph_opti.pack(fill="both", expand=True)
        fr, self.tv_opti = tableau(droite, ("Nbr de Conso.", "Autosuffisance conso.",
                                            "Surplus Vendu CE", "Gain conso.", "Gain prod."), 7)
        fr.pack(fill="x")
        self._mode_change()
        self._maj_prod_annuelle()

    def _mode_change(self):
        etat = "normal" if self.mode.get() == "rapide" else "disabled"
        for w in (self.f_puiss, self.f_nbprod, self.f_conso_prod):
            w.entry.configure(state=etat)
        self.cb_type.configure(state="readonly" if etat == "normal" else "disabled")
        self.tv_opti.heading("Gain prod.", text="Gain prod." if etat == "normal"
                             else "Gain prod. principal")

    def _maj_prod_annuelle(self):
        try:
            p, n = self.f_puiss.get(0.1), self.f_nbprod.get(1, entier=True)
            self.lbl_prod.config(text=f"Production annuelle : "
                                      f"{fmt(p * d.RENDEMENT[self.type_prod.get()], 0)} kWh")
        except ValueError:
            self.lbl_prod.config(text="Production annuelle : -")

    def defaut(self):
        self.fournisseur.set("Total Energie")
        self.prix_achat.set("0.08")
        self.prix_vente.set("0.09")
        self.partage.set(False)
        self.f_conso.set(3500)
        self.f_nbmax.set(10)
        self.f_conso_prod.set(3500)
        self.f_nbprod.set(1)
        self.f_puiss.set(4)
        self.type_prod.set("Solaire")
        self.mode.set("rapide")
        self._mode_change()
        self._remplir_tarifs()
        self.res = None
        self.graph_opti.nettoyer()
        remplir(self.tv_opti, [])
        self.cb_graph.configure(state="disabled")
        self._maj_champs_res(None)
        self.progress["value"] = 0

    def lancer(self):
        try:
            pv, pa = self._prix()
            conso = self.f_conso.get(1)
            nbmax = self.f_nbmax.get(1, entier=True)
            if nbmax > 10000:
                raise ValueError("Le nombre maximum de consommateurs est limité à 10 000.")
            if self.mode.get() == "rapide":
                membres = d.Membres.simulation_rapide(
                    self.f_puiss.get(0.1), self.type_prod.get(), self.f_conso_prod.get(0))
                nbprod = self.f_nbprod.get(1, entier=True)
                prod_annuel = self.f_puiss.get(0.1) / nbprod * d.RENDEMENT[self.type_prod.get()]
            else:
                try:
                    d.verifier_producteur(self.ce)
                except ValueError as e:
                    self.nb.select(1)
                    raise e
                membres, nbprod, prod_annuel = d.Membres.depuis_table(self.ce), 1, None
        except ValueError as e:
            return self._erreur(e)
        if not messagebox.askokcancel("Confirmation", "Voulez-vous lancer l'optimisation ?"):
            return

        self.btn_lancer.config(state="disabled")

        def prog(x):
            self.progress["value"] = x
            self.update_idletasks()
        try:
            self.res = d.optimiser(membres, self._tarif(), conso_consommateur=conso,
                                   nb_conso_max=nbmax, prix_vente=pv, prix_achat=pa,
                                   partage_batiment=self.partage.get(), nb_prod=nbprod,
                                   prod_annuel=prod_annuel, progression=prog)
        except Exception as e:
            self._erreur(e)
            return
        finally:
            self.btn_lancer.config(state="normal")
        self.progress["value"] = 1
        remplir(self.tv_opti, [(int(r[0]), f"{r[1]:.2%}", f"{r[2]:.2%}",
                                f"{r[3]:.2f} €/an", f"{r[4]:.2f} €/an")
                               for r in self.res.table.itertuples(index=False)])
        self.cb_graph.configure(state="readonly")
        self.choix_graph.set(d.GRAPHIQUES[1])
        self._tracer_opti()
        self._maj_champs_res(self.res)

    def _maj_champs_res(self, res):
        v = self.res_vars
        if res is None:
            for var in v.values():
                var.set("?")
            return
        s, o = res.ligne_surplus_max, res.ligne_opti
        v["nb_max"].set(str(res.nb_conso_surplus_max))
        v["part_max"].set(f"{s['Surplus Vendu CE']:.2%}")
        v["gc_max"].set(f"{s['Gain conso.']:.2f}")
        v["gp_max"].set(f"{s['Gain prod.']:.2f}")
        v["nb_opti"].set(str(res.nb_conso_opti))
        v["gc_opti"].set(f"{o['Gain conso.']:.2f}")
        v["gp_opti"].set(f"{o['Gain prod.']:.2f}")

    def _tracer_opti(self):
        if not self.res:
            return
        num = {v: k for k, v in d.GRAPHIQUES.items()}[self.choix_graph.get()]
        self.graph_opti.nettoyer()
        d.tracer_optimisation(self.res, num, ax=self.graph_opti.ax)
        self.graph_opti.fig.tight_layout() if num < 3 else \
            self.graph_opti.fig.subplots_adjust(left=0.1, right=0.6)
        self.graph_opti.redessiner()

    # ------------------------------------------------------ onglet CE perso
    def _onglet_perso(self):
        t = ttk.Frame(self.nb)
        self.nb.add(t, text="Personnaliser la CE")
        haut = ttk.Frame(t)
        haut.pack(fill="x", padx=8, pady=8)

        f = ttk.LabelFrame(haut, text="Ajouter un membre")
        f.pack(side="left", fill="y")
        self.nom = tk.StringVar()
        ttk.Label(f, text="Nom").grid(row=0, column=0, sticky="w")
        ttk.Entry(f, textvariable=self.nom, width=14).grid(row=0, column=1, padx=6)
        self.m = {}
        champs = [("Conso. particulier (kWh/an)", 3500, "part"),
                  ("Conso. industrie (kWh/an)", 0, "usine"),
                  ("Conso. administration (kWh/an)", 0, "admin"),
                  ("Solaire (kW)", 0, "sol"), ("Éolien (kW)", 0, "eol"),
                  ("Bio/Cogén. (kW)", 0, "bio"),
                  ("Puissance batterie (kW)", 0, "pbat"), ("Capacité batterie (kWh)", 0, "cbat")]
        for i, (lab, dv, k) in enumerate(champs, start=1):
            self.m[k] = Champ(f, i, lab, dv, 9)
        ttk.Button(f, text="Ajouter membre", image=self.img("user"), compound="top",
                   style="Icone.TButton", command=self.ajouter).grid(
            row=len(champs) + 1, column=0, columnspan=2, sticky="ew", pady=6)

        mid = ttk.Frame(haut)
        mid.pack(side="left", fill="both", expand=True, padx=8)
        cols = ("Nom", "Conso. particulier", "Conso. usine", "Conso. admin.", "Solaire kW",
                "Éolien kW", "Bio kW", "Batterie kW", "Capa. batt. kWh")
        fr, self.tv_ce = tableau(mid, cols, 9, 95)
        fr.pack(fill="both", expand=True)
        self.tv_ce.bind("<Double-1>", self._edit_cellule)
        bt = ttk.Frame(mid)
        bt.pack(fill="x", pady=4)
        for txt, cmd, ico in [("Effacer le membre", self.suppr_membre, "delete"),
                              ("Effacer la CE", self.suppr_ce, "cancel"),
                              ("Importer Fichier CE", self.importer, "import"),
                              ("Exporter Fichier CE", self.exporter_ce, "export")]:
            ttk.Button(bt, text=txt, image=self.img(ico), compound="top",
                       style="Icone.TButton", command=cmd).pack(side="left", padx=3)
        ttk.Label(mid, text="Astuce : double-cliquez sur une cellule pour la modifier.").pack(anchor="w")

        info = ttk.LabelFrame(t, text="Informations sur la CE")
        info.pack(fill="x", padx=8)
        self.info_vars = {}
        for i, (txt, cle) in enumerate([("Nombre de membres", "n"), ("Consommation totale", "conso"),
                                        ("Production totale", "prod"),
                                        ("Volume total échangé CE", "vol"),("Volume injecté", "rest")]):
            ttk.Label(info, text=txt).grid(row=0, column=2 * i, sticky="e", padx=(10, 4), pady=6)
            self.info_vars[cle] = tk.StringVar(value="0")
            ttk.Label(info, textvariable=self.info_vars[cle], style="Clair.TLabel", width=13
                      ).grid(row=0, column=2 * i + 1, padx=(0, 6), pady=6)

        bas = ttk.Frame(t)
        bas.pack(fill="both", expand=True, padx=8, pady=6)
        self.graph_ce = Graphique(bas)
        self.graph_ce.pack(side="left", fill="both", expand=True)
        cols2 = ("Nom", "Autosuffisance", "Autoconsommation", "Achat CE", "Surplus vendu CE",
                 "Gain grâce à la CE")
        fr2, self.tv_gain = tableau(bas, cols2, 8, 150)
        self.tv_gain.tag_configure("impair", background=GRIS_FOND, foreground="black")
        fr2.pack(side="left", fill="both", expand=True, padx=(8, 0))
        self._rafraichir_table_ce()

    def _lire_membre(self):
        nom = self.nom.get().strip()
        if not nom:
            raise ValueError("Veuillez donner un nom au membre.")
        v = {k: self.m[k].get(0) for k in self.m}
        return nom, v

    def ajouter(self):
        try:
            nom, v = self._lire_membre()
        except ValueError as e:
            return self._erreur(e)
        self.ce = d.ajouter_membre(self.ce, nom, v["part"], v["usine"], v["admin"], v["sol"],
                                   v["eol"], v["bio"], v["pbat"], v["cbat"])
        self.nom.set("")
        for k, dv in {"part": 3500}.items():
            self.m[k].set(dv)
        for k in self.m:
            if k != "part":
                self.m[k].set(0)
        self.maj_perso()

    def suppr_membre(self):
        sel = self.tv_ce.selection()
        if not sel:
            return messagebox.showinfo("Suppression", "Sélectionnez d'abord un membre.")
        if messagebox.askokcancel("Confirmation", "Voulez-vous supprimer le membre sélectionné ?"):
            i = self.tv_ce.index(sel[0])
            self.ce = self.ce.drop(self.ce.index[i]).reset_index(drop=True)
            self.maj_perso()

    def suppr_ce(self):
        if messagebox.askokcancel("Confirmation", "Voulez-vous supprimer cette CE ?"):
            self.ce = d.ce_vide()
            self.maj_perso()

    def importer(self):
        f = filedialog.askopenfilename(filetypes=[("Fichiers CE", "*.xlsx *.xls *.csv")])
        if f:
            try:
                self.ce = d.importer_ce(f)
            except Exception as e:
                return self._erreur(e)
            self.maj_perso()

    def exporter_ce(self):
        self._exporter(self.ce)

    def _edit_cellule(self, ev):
        if self.tv_ce.identify_region(ev.x, ev.y) != "cell":
            return
        item = self.tv_ce.identify_row(ev.y)
        col = int(self.tv_ce.identify_column(ev.x)[1:]) - 1
        i = self.tv_ce.index(item)
        nom_col = d.COLONNES_CE[col]
        actuel = self.ce.iloc[i][nom_col]
        v = simpledialog.askstring("Modifier", f"{nom_col} :", initialvalue=str(actuel), parent=self)
        if v is None:
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
        v["n"].set(str(n))
        v["conso"].set(f"{fmt(conso, 0)} kWh")
        v["prod"].set(f"{fmt(prod, 0)} kWh")
        v["vol"].set(f"{fmt(volume, 0)} kWh")
        v["rest"].set(f"{fmt(rest, 0)} kWh")

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
                                     partage_batiment=self.partage.get())
        except Exception as e:
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

    # --------------------------------------------- onglet dimensionnement
    def _onglet_dim(self):
        t = ttk.Frame(self.nb)
        self.nb.add(t, text="Dimensionnement installation")
        g = ttk.Frame(t)
        g.pack(side="left", fill="y", padx=8, pady=8)
        self.type_dim = tk.StringVar(value="Solaire")
        ttk.Label(g, text="Type de production").grid(row=0, column=0, sticky="w")
        ttk.Combobox(g, textvariable=self.type_dim, values=TYPES, state="readonly",
                     width=14).grid(row=0, column=1, padx=6)
        self.f_conso_dim = Champ(g, 1, "Consommation annuelle (kWh)", 3500)
        self.f_puiss_dim = Champ(g, 2, "Puissance à installer (kW)", 4)
        ttk.Button(g, text="Calculer", command=self.calc_dim).grid(
            row=3, column=0, columnspan=2, sticky="ew", pady=10, ipady=4)
        ttk.Label(g, text="▼ ▼ ▼", foreground=ROUGE_CLAIR, anchor="center",
                  font=(POLICE, 20, "bold")).grid(row=4, column=0, columnspan=2, sticky="ew")
        self.lbl_dim = ttk.Label(g, text="Production annuelle : -", style="Clair.TLabel",
                                 wraplength=280)
        self.lbl_dim.grid(row=5, column=0, columnspan=2, sticky="ew")
        self.graph_dim = Graphique(t)
        self.graph_dim.pack(side="left", fill="both", expand=True, padx=8, pady=8)

    def calc_dim(self):
        try:
            c = self.f_conso_dim.get(1)
            puiss = self.f_puiss_dim.get(0.1)
            self.config(cursor="watch")
            self.update_idletasks()
            df = d.dimensionner_installation(c, self.type_dim.get(), self._tarif())
        except Exception as e:
            self.config(cursor="")
            return self._erreur(e)
        self.config(cursor="")
        self.dim_df = df
        self.graph_dim.nettoyer()
        d.tracer_dimensionnement(df, ax=self.graph_dim.ax)
        self.graph_dim.fig.tight_layout()
        self.graph_dim.redessiner()
        self.lbl_dim.config(text=f"Production annuelle pour {puiss:g} kW : "
                                 f"{fmt(puiss * d.RENDEMENT[self.type_dim.get()], 0)} kWh")

    # ---------------------------------------------------------- onglet tarifs
    def _onglet_tarifs(self):
        t = ttk.Frame(self.nb)
        self.nb.add(t, text="Tarifs")
        ttk.Label(t, text="Tarifs du fournisseur choisi (double-clic pour modifier une valeur, "
                          "valable pour cette session).").pack(anchor="w", padx=8, pady=6)
        fr, self.tv_tarif = tableau(t, ("Poste", "Valeur"), 15, 200)
        self.tv_tarif.column("Poste", width=420, anchor="w")
        fr.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.tv_tarif.bind("<Double-1>", self._edit_tarif)
        self._remplir_tarifs()

    def _remplir_tarifs(self):
        v = self._tarif()
        remplir(self.tv_tarif, [(n, f"{x:g}") for n, x in zip(d.LIGNES_TARIF, v)])
        self.lbl_date.config(text=f"(tarifs {self.tarifs.date})")

    def _edit_tarif(self, ev):
        item = self.tv_tarif.identify_row(ev.y)
        if not item:
            return
        i = self.tv_tarif.index(item)
        actuel = self._tarif()[i]
        v = simpledialog.askstring("Modifier le tarif", d.LIGNES_TARIF[i],
                                   initialvalue=f"{actuel:g}", parent=self)
        if v is None:
            return
        try:
            x = float(v.replace(",", "."))
        except ValueError:
            x = 0.0                                   # comme dans MATLAB : invalide -> 0
        self.tarifs.table.iloc[i, self.tarifs.table.columns.get_loc(self.fournisseur.get())] = x
        self._remplir_tarifs()
        self._prix_change()


if __name__ == "__main__":
    App().mainloop()
