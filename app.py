"""
SKAB Bank Statement Extractor - Edition Comptabilité Odoo 18
Génère CSV + Excel avec colonne balance
"""

import streamlit as st
import pandas as pd
import io
import os
import json
import plotly.express as px
from datetime import datetime
from openpyxl import Workbook
from openpyxl.styles import PatternFill, Font, Alignment
from streamlit_local_storage import LocalStorage

# Modules personnalisés
from extractor_openrouter import OpenRouterExtractor
from cleaner import DataCleaner
from bank_configs import get_bank_list, get_bank_config


# ====================== CONFIGURATION ======================
st.set_page_config(page_title="SKAB Extractor - Export Odoo", page_icon="🏦", layout="wide")

st.markdown("""
<style>
    .main-header { background: linear-gradient(135deg, #1B3A5C, #2E75B6); padding: 2rem; border-radius: 16px; color: white; margin-bottom: 2rem; text-align: center; }
    .main-header h1 { margin: 0; font-size: 1.8rem; }
    .main-header p { margin: 0.5rem 0 0 0; opacity: 0.9; }
    .metric-card {
        background: #ffffff;
        padding: 1rem 1.2rem;
        border-radius: 12px;
        border: 1px solid #E0E0E0;
        box-shadow: 0 1px 4px rgba(0,0,0,0.06);
        text-align: center;
    }
    .metric-card .label { font-size: 0.8rem; color: #666; margin-bottom: 4px; text-transform: uppercase; letter-spacing: 0.5px; }
    .metric-card .value { font-size: 1.6rem; font-weight: 700; color: #1B3A5C; }
    .metric-card .value.credit { color: #2ECC71; }
    .metric-card .value.debit { color: #E74C3C; }
    .metric-card .value.balance { color: #1B3A5C; }
    .metric-card .value.positive { color: #2ECC71; }
    .metric-card .value.negative { color: #E74C3C; }
    .stDataFrame { border-radius: 8px; border: 1px solid #E0E0E0; }
</style>
""", unsafe_allow_html=True)


def get_openrouter_key():
    """Clé API OpenRouter depuis les secrets Streamlit.
    Configurer dans .streamlit/secrets.toml ou Streamlit Cloud > Settings > Secrets
    """
    return st.secrets.get("OPENROUTER_API_KEY", "")


# ====================== PERSISTANCE NAVIGATEUR (localStorage) ======================
# La session doit rester disponible côté navigateur (survit à un rafraîchissement
# de page ou à une reconnexion) tant que l'utilisateur ne lance pas une nouvelle
# extraction (bouton "Nouvelle extraction").
LOCAL_STORAGE_KEY = "skab_session_data"
localS = LocalStorage()


def _save_session_to_browser():
    """Enregistre le résultat de l'extraction courante dans le localStorage
    du navigateur, pour pouvoir le restaurer après un rechargement de page."""
    try:
        payload = {
            "df_clean": st.session_state.df_clean.to_json(orient="split", date_format="iso"),
            "stats": st.session_state.stats,
            "banque_selectionnee": st.session_state.banque_selectionnee,
            "uploaded_file_name": st.session_state.get("uploaded_file_name"),
            "failed_pages": st.session_state.failed_pages,
        }
        localS.setItem(LOCAL_STORAGE_KEY, json.dumps(payload), key="skab_set_session")
    except Exception:
        # La persistance navigateur est un confort, pas un pré-requis :
        # on ne bloque jamais l'application si elle échoue (ex : quota localStorage).
        pass


def _clear_session_in_browser():
    """Supprime la session sauvegardée dans le navigateur (nouvelle extraction)."""
    try:
        localS.deleteItem(LOCAL_STORAGE_KEY, key="skab_delete_session")
    except Exception:
        pass


def _restore_session_from_browser() -> bool:
    """Restaure une session précédemment sauvegardée dans le navigateur, si elle
    existe. Retourne True si une session a été restaurée."""
    try:
        raw = localS.getItem(LOCAL_STORAGE_KEY, key="skab_get_session")
        if not raw:
            return False
        payload = json.loads(raw) if isinstance(raw, str) else raw
        df_restored = pd.read_json(io.StringIO(payload["df_clean"]), orient="split")
        st.session_state.df_clean = df_restored
        st.session_state.stats = payload.get("stats")
        st.session_state.banque_selectionnee = payload.get("banque_selectionnee", "UNICS")
        st.session_state.uploaded_file_name = payload.get("uploaded_file_name")
        st.session_state.failed_pages = payload.get("failed_pages", [])
        st.session_state.extraction_done = True
        return True
    except Exception:
        return False


# Initialisation état session
if "extraction_done" not in st.session_state:
    st.session_state.update({
        "extraction_done": False,
        "show_confirm": False,
        "df_clean": None,
        "stats": None,
        "banque_selectionnee": "UNICS",
        "pdf_bytes_cache": None,
        "extraction_in_progress": False,
        "total_pages": None,
        "current_page": 1,
        "collected_transactions": [],
        "extraction_method": "vision",
        "failed_pages": [],
        "retry_failed_pages": False,
        "last_known_balance": None,
        "uploaded_file_name": None,
        "browser_restore_done": False,
        "browser_restore_attempts": 0,
    })

# Tant qu'aucune extraction n'est déjà chargée en session ET qu'on n'a pas
# encore réussi/abandonné la restauration, on retente à CHAQUE script-run.
# C'est nécessaire car le composant localStorage renvoie `None` au tout
# premier rendu (le temps que son JS se charge côté navigateur) : il faut
# donc laisser passer 1 ou 2 reruns avant que la vraie valeur soit dispo.
if (
    not st.session_state.extraction_done
    and not st.session_state.extraction_in_progress
    and not st.session_state.browser_restore_done
):
    if _restore_session_from_browser():
        st.session_state.browser_restore_done = True
        st.rerun()
    else:
        st.session_state.browser_restore_attempts += 1
        # Au-delà de 5 tentatives, on abandonne (pas de session sauvegardée
        # ou composant indisponible) pour ne pas bloquer l'utilisateur.
        if st.session_state.browser_restore_attempts >= 5:
            st.session_state.browser_restore_done = True

# Nombre de pages traitées par lot avant de rendre la main à Streamlit
# (st.rerun()). Limite la durée d'exécution ininterrompue du script et
# la mémoire utilisée à un instant donné, quel que soit le nombre total
# de pages du document — c'est ce qui évite le blocage sur les gros PDF.
BATCH_SIZE = 8

# ====================== SIDEBAR ======================
with st.sidebar:
    st.title("🏦 SKAB Extractor")
    st.caption("Extraction et conversion de relevés bancaires camerounais")

    uploaded_file = st.file_uploader("📄 Charger le relevé PDF", type=["pdf"])

    # Liste des banques directement dérivée de bank_configs.py : ajouter
    # une banque là-bas suffit à la faire apparaître ici automatiquement.
    BANK_LIST = get_bank_list()
    st.session_state.setdefault("banque_widget", "UNICS")

    # --- DÉTECTION AUTOMATIQUE DE LA BANQUE ---
    # Se déclenche une seule fois par fichier uploadé (via une signature
    # nom+taille) : lit la 1ère page et pré-sélectionne la banque
    # correspondante dans la liste ci-dessous, sans empêcher l'utilisateur
    # de la corriger manuellement ensuite.
    if uploaded_file is not None:
        st.session_state.uploaded_file_name = uploaded_file.name
        file_sig = f"{uploaded_file.name}:{uploaded_file.size}"
        if st.session_state.get("bank_detect_sig") != file_sig:
            st.session_state.bank_detect_sig = file_sig
            if get_openrouter_key():
                with st.spinner("🔍 Détection automatique de la banque..."):
                    try:
                        detector = OpenRouterExtractor(
                            api_key=get_openrouter_key(), mode="vision",
                            banque_nom="Autre banque", verbose_debug=False,
                        )
                        detected = detector.detect_bank(uploaded_file.getvalue())
                    except Exception:
                        detected = None
                if detected:
                    st.session_state.banque_widget = detected
                    st.success(f"🏦 Banque détectée : **{detected}**")
                else:
                    st.info("Banque non détectée automatiquement — sélectionnez-la ci-dessous.")

    banque_sel = st.selectbox("🏦 Banque émettrice", BANK_LIST, key="banque_widget")
    st.session_state.banque_selectionnee = banque_sel

    method = st.radio("🔍 Méthode d'analyse", ["vision", "hybrid"],
                      help="Vision : analyse d'images | Hybride : texte puis vision si nécessaire")

    if not get_openrouter_key():
        st.warning("""
            ⚠️ **Clé API manquante**  
            Ajoutez `OPENROUTER_API_KEY` dans  
            `.streamlit/secrets.toml`
        """)

    if st.button("🔄 Nouvelle extraction", use_container_width=True):
        _clear_session_in_browser()
        for k in list(st.session_state.keys()):
            del st.session_state[k]
        st.rerun()

# ====================== HEADER ======================
st.markdown('<div class="main-header"><h1>🏦 SKAB Bank Statement Extractor</h1><p>Génération de fichiers d\'importation pour la comptabilité Odoo</p></div>', unsafe_allow_html=True)

# Filet de sécurité : si la restauration automatique depuis le navigateur n'a
# rien trouvé (ou le composant a mis trop de temps à répondre), l'utilisateur
# peut relancer manuellement la tentative sans perdre son upload en cours.
if (
    not st.session_state.extraction_done
    and not st.session_state.extraction_in_progress
    and not uploaded_file
):
    col_restore, _ = st.columns([1, 3])
    with col_restore:
        if st.button("🔁 Restaurer la dernière session", use_container_width=True):
            st.session_state.browser_restore_done = False
            st.session_state.browser_restore_attempts = 0
            st.rerun()

# ====================== EXTRACTION ======================
if (
    uploaded_file
    and not st.session_state.extraction_done
    and not st.session_state.show_confirm
    and not st.session_state.extraction_in_progress
):
    if st.button("🔍 Analyser le relevé", type="primary", use_container_width=True):
        st.session_state.pdf_bytes_cache = uploaded_file.read()
        st.session_state.show_confirm = True
        st.rerun()

if st.session_state.show_confirm:
    if not get_openrouter_key():
        st.error("❌ Clé API OpenRouter manquante. Configurez-la dans les secrets Streamlit.")
    else:
        col1, col2 = st.columns([3, 1])
        with col1:
            st.info(f"**Analyse imminente** — Banque: **{st.session_state.banque_selectionnee}**")
        with col2:
            if st.button("✅ Confirmer l'analyse", type="primary", use_container_width=True):
                # On fige la méthode choisie pour toute la durée de
                # l'extraction (le radio bouton reste modifiable dans la
                # sidebar mais ne doit pas changer le comportement en
                # cours de traitement d'un lot déjà commencé).
                st.session_state.extraction_method = method
                st.session_state.extraction_in_progress = True
                st.session_state.browser_restore_done = True
                st.session_state.show_confirm = False
                st.session_state.total_pages = None
                st.session_state.current_page = 1
                st.session_state.collected_transactions = []
                st.session_state.failed_pages = []
                st.session_state.last_known_balance = None
                st.rerun()

# ====================== EXTRACTION PAR LOTS ======================
# Le traitement est découpé en lots de BATCH_SIZE pages. Chaque exécution
# du script ne traite qu'un lot, puis appelle st.rerun() : ça borne le
# temps d'exécution ininterrompue et la mémoire utilisée quel que soit le
# nombre total de pages, et ça donne une vraie progression visible (au
# lieu d'un unique appel bloquant de plusieurs dizaines de minutes sur
# les gros documents, qui pouvait dépasser une limite de la plateforme).
if st.session_state.extraction_in_progress:
    if not get_openrouter_key():
        st.error("❌ Clé API OpenRouter manquante. Configurez-la dans les secrets Streamlit.")
        st.session_state.extraction_in_progress = False
    else:
        try:
            extractor = OpenRouterExtractor(
                api_key=get_openrouter_key(),
                mode=st.session_state.extraction_method,
                banque_nom=st.session_state.banque_selectionnee,
                verbose_debug=False,
            )

            if st.session_state.extraction_method != "vision":
                # Mode hybride : texte d'abord (léger), un seul passage.
                # Ne bascule sur l'image que si le PDF est scanné.
                with st.spinner("Extraction en cours (mode hybride)..."):
                    df_raw = extractor.extract(st.session_state.pdf_bytes_cache)
                st.session_state.failed_pages = sorted(set(extractor.failed_pages))
                cleaner = DataCleaner()
                df_clean = cleaner.clean(df_raw, banque_nom=st.session_state.banque_selectionnee)
                df_clean = cleaner.check_consistency(df_clean)
                st.session_state.df_clean = df_clean
                st.session_state.stats = cleaner.get_statistics(df_clean, banque_nom=st.session_state.banque_selectionnee)
                st.session_state.extraction_done = True
                st.session_state.extraction_in_progress = False
                _save_session_to_browser()
                st.rerun()
            else:
                if st.session_state.total_pages is None:
                    st.session_state.total_pages = extractor.get_total_pages(st.session_state.pdf_bytes_cache)
                    if not st.session_state.total_pages:
                        st.error("❌ Impossible de lire le PDF (nombre de pages introuvable).")
                        st.session_state.extraction_in_progress = False
                        st.stop()
                    st.rerun()

                total_pages = st.session_state.total_pages
                current = st.session_state.current_page
                batch_end = min(current + BATCH_SIZE - 1, total_pages)

                st.progress(
                    (current - 1) / total_pages,
                    text=f"🔍 Analyse en cours — pages {current} à {batch_end} sur {total_pages}...",
                )

                batch_transactions = extractor.extract_transactions(
                    st.session_state.pdf_bytes_cache, current, batch_end, total_pages,
                    starting_balance=st.session_state.last_known_balance,
                )
                st.session_state.collected_transactions.extend(batch_transactions)
                # Le solde de la dernière transaction lue sur ce lot sert
                # d'indice de continuité pour le lot suivant (aide le modèle
                # à s'auto-vérifier sur la première page du prochain lot).
                st.session_state.last_known_balance = extractor.last_balance_hint
                # On mémorise toute page qui a échoué (conversion ou API,
                # après épuisement des tentatives + fallback) pour pouvoir
                # le signaler à l'utilisateur et proposer un nouvel essai
                # ciblé, plutôt que de laisser l'échec passer inaperçu.
                st.session_state.failed_pages = sorted(
                    set(st.session_state.failed_pages) | set(extractor.failed_pages)
                )
                st.session_state.current_page = batch_end + 1

                if st.session_state.current_page > total_pages:
                    df_raw = extractor.build_dataframe(st.session_state.collected_transactions)
                    cleaner = DataCleaner()
                    df_clean = cleaner.clean(df_raw, banque_nom=st.session_state.banque_selectionnee)
                    df_clean = cleaner.check_consistency(df_clean)
                    st.session_state.df_clean = df_clean
                    st.session_state.stats = cleaner.get_statistics(df_clean, banque_nom=st.session_state.banque_selectionnee)
                    st.session_state.extraction_done = True
                    st.session_state.extraction_in_progress = False
                    _save_session_to_browser()

                st.rerun()

        except Exception as e:
            st.error(f"❌ Erreur lors de l'extraction : {str(e)}")
            st.session_state.extraction_in_progress = False

# ====================== NOUVEL ESSAI SUR PAGES EN ÉCHEC ======================
# Relance uniquement les pages qui ont échoué (voir failed_pages), sans
# retraiter tout le document. Uniquement pour le mode vision : c'est là
# que le suivi par page a un sens (le mode hybride ne travaille pas par
# page unique).
if st.session_state.retry_failed_pages:
    if not get_openrouter_key():
        st.error("❌ Clé API OpenRouter manquante.")
        st.session_state.retry_failed_pages = False
    else:
        try:
            extractor = OpenRouterExtractor(
                api_key=get_openrouter_key(),
                mode="vision",
                banque_nom=st.session_state.banque_selectionnee,
                verbose_debug=False,
            )
            pages_a_reessayer = list(st.session_state.failed_pages)
            hint = st.session_state.collected_transactions[-1].get("solde") if st.session_state.collected_transactions else None
            with st.spinner(f"Nouvel essai sur {len(pages_a_reessayer)} page(s)..."):
                new_transactions = extractor.extract_specific_pages(
                    st.session_state.pdf_bytes_cache, pages_a_reessayer, st.session_state.total_pages,
                    starting_balance=hint,
                )
            st.session_state.collected_transactions.extend(new_transactions)
            # Ne restent en échec que les pages toujours ratées après ce nouvel essai
            st.session_state.failed_pages = sorted(set(extractor.failed_pages))

            df_raw = extractor.build_dataframe(st.session_state.collected_transactions)
            cleaner = DataCleaner()
            df_clean = cleaner.clean(df_raw, banque_nom=st.session_state.banque_selectionnee)
            df_clean = cleaner.check_consistency(df_clean)
            st.session_state.df_clean = df_clean
            st.session_state.stats = cleaner.get_statistics(df_clean, banque_nom=st.session_state.banque_selectionnee)
            st.session_state.retry_failed_pages = False
            _save_session_to_browser()
            st.rerun()
        except Exception as e:
            st.error(f"❌ Erreur lors du nouvel essai : {str(e)}")
            st.session_state.retry_failed_pages = False

# ====================== RÉSULTATS ======================
if st.session_state.extraction_done and st.session_state.df_clean is not None:
    df_display = st.session_state.df_clean.copy()

    # Nettoyage dates
    df_display['Date'] = pd.to_datetime(df_display['Date'], dayfirst=True, errors='coerce')
    df_display = df_display.dropna(subset=['Date'])

    # --- PAGES EN ÉCHEC ---
    if st.session_state.failed_pages:
        pages_str = ", ".join(str(p) for p in st.session_state.failed_pages)
        col_warn, col_btn = st.columns([4, 1])
        with col_warn:
            st.error(
                f"⚠️ {len(st.session_state.failed_pages)} page(s) n'ont pas pu être lues "
                f"après plusieurs tentatives et ne sont PAS incluses ci-dessous : page(s) {pages_str}. "
                f"Ce sont les transactions manquantes les plus probables."
            )
        with col_btn:
            if st.session_state.extraction_method == "vision" and st.button("🔄 Relancer ces pages", use_container_width=True):
                st.session_state.retry_failed_pages = True
                st.rerun()

    # --- FILTRE PAR DATE ---
    # Déplacé plus bas, juste au-dessus du tableau "Données extraites" —
    # voir section correspondante. Les indicateurs et le graphique
    # ci-dessous portent sur l'ENSEMBLE du relevé.
    stats = st.session_state.stats or {}

    def fmt(val):
        if val is None or val == 'N/A':
            return 'N/A'
        return f"{val:,.0f} FCFA"
    
    col1, col2, col3 = st.columns(3)
    with col1:
        so = stats.get('solde_ouverture')
        so_class = "positive" if (so is not None and so >= 0) else "negative"
        so_val = f"{so:,.0f} FCFA" if so is not None else "N/A"
        st.markdown(f"""
        <div class="metric-card">
            <div class="label">Solde d'ouverture (relevé)</div>
            <div class="value {so_class}">{so_val}</div>
        </div>""", unsafe_allow_html=True)
    
    with col2:
        sc = stats.get('solde_cloture')
        sc_class = "positive" if (sc is not None and sc >= 0) else "negative"
        sc_val = f"{sc:,.0f} FCFA" if sc is not None else "N/A"
        st.markdown(f"""
        <div class="metric-card">
            <div class="label">Solde de clôture (relevé)</div>
            <div class="value {sc_class}">{sc_val}</div>
        </div>""", unsafe_allow_html=True)
    
    with col3:
        net = stats.get('net', 0)
        net_class = "positive" if net >= 0 else "negative"
        st.markdown(f"""
        <div class="metric-card">
            <div class="label">Flux net</div>
            <div class="value {net_class}">{net:,.0f} FCFA</div>
        </div>""", unsafe_allow_html=True)

    st.caption(
        "🔎 Solde d'ouverture = montant de la première ligne du tableau de données extraites "
        "ci-dessous ; solde de clôture = montant de la dernière ligne (pas recalculés) — "
        "comparez-les au solde affiché sur le document original pour un premier contrôle visuel."
    )

    # --- CONTRÔLE DE COHÉRENCE OUVERTURE ↔ CLÔTURE ---
    # Le solde de clôture exact du relevé doit être égal au solde
    # d'ouverture exact + le flux net des transactions extraites. C'est le
    # contrôle le plus direct de la complétude/exactitude de l'extraction :
    # si l'écart est proche de 0, les données extraites concordent avec les
    # deux soldes réellement imprimés sur le relevé.
    ecart_oc = stats.get('ecart_ouverture_cloture')
    if ecart_oc is None:
        if stats.get('solde_ouverture') is None or stats.get('solde_cloture') is None:
            st.info(
                "ℹ️ Contrôle de cohérence indisponible : le solde d'ouverture et/ou de "
                "clôture n'a pas été détecté parmi les lignes extraites. Vérifiez-les "
                "manuellement sur le relevé original."
            )
    elif abs(ecart_oc) <= 1:
        st.success(
            f"✅ Cohérence vérifiée : solde d'ouverture ({stats['solde_ouverture']:,.0f} FCFA) "
            f"+ flux net ({stats['net']:,.0f} FCFA) = solde de clôture attendu, conforme au "
            f"solde de clôture du relevé ({stats['solde_cloture']:,.0f} FCFA)."
        )
    else:
        st.warning(
            f"⚠️ Écart de {ecart_oc:,.0f} FCFA entre le solde de clôture du relevé "
            f"({stats['solde_cloture']:,.0f} FCFA) et le solde attendu à partir de l'ouverture "
            f"+ flux net ({stats['solde_ouverture'] + stats['net']:,.0f} FCFA). Cela indique "
            f"probablement une transaction manquante ou mal lue — vérifiez les lignes en "
            f"anomalie ci-dessous."
        )
    
    col4, col5, col6 = st.columns(3)
    with col4:
        st.markdown(f"""
        <div class="metric-card">
            <div class="label">Total crédits</div>
            <div class="value credit">{stats.get('total_credit', 0):,.0f} FCFA</div>
        </div>""", unsafe_allow_html=True)
    
    with col5:
        st.markdown(f"""
        <div class="metric-card">
            <div class="label">Total débits</div>
            <div class="value debit">{stats.get('total_debit', 0):,.0f} FCFA</div>
        </div>""", unsafe_allow_html=True)
    
    with col6:
        st.markdown(f"""
        <div class="metric-card">
            <div class="label">Lignes extraites</div>
            <div class="value balance">{len(df_display)}</div>
        </div>""", unsafe_allow_html=True)

    # --- TABLEAU DE BORD / GRAPHIQUE ---
    st.subheader("📊 Flux de trésorerie")

    df_display['Débit'] = pd.to_numeric(df_display['Débit'], errors='coerce').fillna(0)
    df_display['Crédit'] = pd.to_numeric(df_display['Crédit'], errors='coerce').fillna(0)
    df_display['Solde_cumulé'] = df_display['Crédit'].cumsum() - df_display['Débit'].cumsum()

    df_chart = df_display.groupby('Date').agg({
        'Débit': 'sum',
        'Crédit': 'sum',
        'Solde_cumulé': 'last'
    }).reset_index()

    # Graphique plus lisible : barres débit/crédit + ligne solde
    fig = px.bar(
        df_chart,
        x='Date',
        y=['Crédit', 'Débit'],
        title="Mouvements bancaires",
        barmode='group',
        color_discrete_map={"Crédit": "#2ECC71", "Débit": "#E74C3C"},
        height=400,
    )
    fig.add_scatter(
        x=df_chart['Date'],
        y=df_chart['Solde_cumulé'],
        mode='lines+markers',
        name='Solde',
        line=dict(color="#1B3A5C", width=3),
        marker=dict(size=6),
        yaxis='y',
    )
    fig.update_layout(
        hovermode="x unified",
        yaxis_title="Montant (FCFA)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=40, r=20, t=40, b=40),
        font=dict(size=12),
    )
    st.plotly_chart(fig, use_container_width=True)

    # -- Données complètes (avec balance) --
    st.divider()
    st.subheader("📋 Données extraites")

    # --- FILTRE PAR DATE (au niveau des données extraites) ---
    # Zoome sur une période précise pour vérifier la cohérence (comparer
    # visuellement au PDF) sans dérouler tout le relevé. Streamlit ré-exécute
    # le script à chaque changement de date : le résumé et le tableau
    # ci-dessous se recalculent donc automatiquement, sans bouton "Appliquer".
    date_min = df_display['Date'].min().date()
    date_max = df_display['Date'].max().date()
    col_d1, col_d2 = st.columns(2)
    with col_d1:
        date_debut = st.date_input("Du", value=date_min, min_value=date_min, max_value=date_max)
    with col_d2:
        date_fin = st.date_input("Au", value=date_max, min_value=date_min, max_value=date_max)

    if date_debut > date_fin:
        st.warning("⚠️ La date de début est postérieure à la date de fin.")
        df_filtered = df_display.iloc[0:0]
    else:
        df_filtered = df_display[
            (df_display['Date'].dt.date >= date_debut) & (df_display['Date'].dt.date <= date_fin)
        ]

    # --- RÉSUMÉ AUTO-REGROUPÉ DE LA PÉRIODE SÉLECTIONNÉE ---
    # Se recalcule à chaque changement de date (rerun Streamlit automatique).
    cleaner_for_stats = DataCleaner()
    period_stats = cleaner_for_stats.get_statistics(df_filtered, banque_nom=st.session_state.banque_selectionnee)
    is_full_period = (date_debut == date_min and date_fin == date_max)
    label_periode = "période complète" if is_full_period else f"{date_debut.strftime('%d/%m/%Y')} → {date_fin.strftime('%d/%m/%Y')}"
    st.caption(f"Résumé pour la période sélectionnée ({label_periode}) :")
    pc1, pc2, pc3, pc4, pc5, pc6 = st.columns(6)
    pc1.metric("Lignes", len(df_filtered))
    pc2.metric("Total crédits", f"{period_stats.get('total_credit', 0):,.0f}")
    pc3.metric("Total débits", f"{period_stats.get('total_debit', 0):,.0f}")
    pc4.metric("Flux net", f"{period_stats.get('net', 0):,.0f}")
    p_so = period_stats.get('solde_ouverture')
    p_sc = period_stats.get('solde_cloture')
    pc5.metric("Solde ouverture (relevé)", f"{p_so:,.0f}" if p_so is not None else "N/A")
    pc6.metric("Solde clôture (relevé)", f"{p_sc:,.0f}" if p_sc is not None else "N/A")
    if not is_full_period and p_so is None and p_sc is None:
        st.caption(
            "Solde ouverture/clôture non disponibles sur une sous-période qui n'inclut pas "
            "les lignes d'ouverture/clôture du relevé — sélectionnez la période complète pour "
            "le contrôle de cohérence."
        )

    # --- CONTRÔLE DE COHÉRENCE (sur la période affichée) ---
    if 'Écart' in df_filtered.columns:
        anomalies = df_filtered[df_filtered['Écart'].notna() & (df_filtered['Écart'].abs() > 1)]
        if len(anomalies) > 0:
            st.warning(
                f"⚠️ {len(anomalies)} ligne(s) sur la période affichée présentent un solde "
                f"incohérent avec la ligne précédente (montant probablement mal lu, ou ligne "
                f"manquante juste avant). Vérifiez-les contre le PDF original."
            )
            with st.expander("Voir les lignes en anomalie"):
                st.dataframe(
                    anomalies[[c for c in ['Date', 'Libellé', 'Débit', 'Crédit', 'Solde', 'Écart'] if c in anomalies.columns]],
                    use_container_width=True,
                )

    # Afficher toutes les colonnes : Date, Référence, Libellé, Débit, Crédit, Solde, Écart
    display_cols = ['Date', 'Référence', 'Libellé', 'Débit', 'Crédit', 'Solde', 'Écart']
    display_df = df_filtered[[c for c in display_cols if c in df_filtered.columns]]
    st.dataframe(display_df, use_container_width=True, height=400)

    # --- EXPORT ---
    st.divider()
    st.subheader("💾 Export")
    st.caption(f"L'export ci-dessous porte sur la période sélectionnée ci-dessus ({label_periode}, {len(df_filtered)} ligne(s)).")

    col_csv, col_xlsx = st.columns(2)

    with col_csv:
        # CSV Odoo
        odoo_export = df_filtered.copy()
        odoo_export = odoo_export.rename(columns={
            'Date': 'date',
            'Libellé': 'payment_ref',
            'Référence': 'ref',
        })
        odoo_export['amount'] = odoo_export['Crédit'].fillna(0) - odoo_export['Débit'].fillna(0)
        odoo_export['ref'] = odoo_export['ref'].replace(0, '').replace('0.0', '')

        # Inclure la colonne solde dans le CSV
        if 'Solde' in odoo_export.columns:
            csv_cols = ['date', 'payment_ref', 'amount', 'ref', 'Solde']
        else:
            csv_cols = ['date', 'payment_ref', 'amount', 'ref']

        final_csv = odoo_export[[c for c in csv_cols if c in odoo_export.columns]]

        csv_buffer = io.StringIO()
        final_csv.to_csv(csv_buffer, index=False, encoding='utf-8-sig', sep=',')
        st.download_button(
            label="📥 Télécharger CSV",
            data=csv_buffer.getvalue(),
            file_name=f"EXPORT_{st.session_state.banque_selectionnee}.csv",
            mime="text/csv",
            type="primary",
            use_container_width=True,
        )

    with col_xlsx:
        # Excel complet avec toutes les colonnes + balance
        excel_buffer = io.BytesIO()

        # --- Feuille 1 : "RELEVE" (Date / Libellé / Montant / Solde courant),
        # au format du relevé bancaire de référence (CCA) ---
        sheet1_cols = ['Date', 'Libellé', 'Débit', 'Crédit', 'Solde']
        sheet1_df = df_filtered[[c for c in sheet1_cols if c in df_filtered.columns]].reset_index(drop=True)

        # Les relevés volumineux sont traités par lots de pages : le modèle
        # d'extraction relève, sur chaque page, la ligne de "solde
        # d'ouverture"/"solde de clôture" qu'il y voit — ce qui produit une
        # ligne de solde à CHAQUE frontière de lot (tous les 8 pages), et pas
        # uniquement au tout début/à la toute fin du relevé complet. Ces
        # lignes ne sont pas de vraies transactions : leur montant ne doit
        # pas s'ajouter au flux, et elles ne doivent pas apparaître dans le
        # fichier Excel final (la colonne "Solde courant" fait déjà ce
        # travail de report de solde, ligne par ligne).
        bank_cfg = get_bank_config(st.session_state.banque_selectionnee)
        # Fallback générique si la config de la banque ne fournit pas (ou plus)
        # de patterns : on ne veut jamais laisser une ligne de solde
        # d'ouverture/clôture non filtrée se retrouver traitée comme une
        # transaction (voir colonne "Montant" ci-dessous).
        solde_pattern = "|".join(
            bank_cfg.solde_ouverture_patterns + bank_cfg.solde_cloture_patterns
        ) or r"ouverture|opening|cl[ôo]ture|cloture|solde\s+d[ée]but|report\s+solde"
        if 'Libellé' in sheet1_df.columns:
            lib_lower = sheet1_df['Libellé'].astype(str).str.lower()
            is_solde_row = lib_lower.str.contains(solde_pattern, na=False, regex=True)
            sheet1_df = sheet1_df[~is_solde_row].reset_index(drop=True)

        montant_series = (
            pd.to_numeric(sheet1_df.get('Crédit'), errors='coerce').fillna(0)
            - pd.to_numeric(sheet1_df.get('Débit'), errors='coerce').fillna(0)
        )
        solde_series = pd.to_numeric(sheet1_df.get('Solde'), errors='coerce') if 'Solde' in sheet1_df.columns else None

        # Solde d'ouverture déduit de la 1ère ligne (solde relevé - montant de la 1ère ligne)
        # → ce solde alimente uniquement la colonne "Solde courant" (via la
        # formule de la première ligne ci-dessous), jamais la colonne "Montant".
        opening_balance = 0.0
        if solde_series is not None and len(solde_series) and pd.notna(solde_series.iloc[0]):
            opening_balance = float(solde_series.iloc[0]) - float(montant_series.iloc[0])

        wb = Workbook()
        ws = wb.active
        ws.title = "RELEVE"

        headers = ["Date", "Libellé", "Montant", "Solde courant"]
        header_fill = PatternFill("solid", fgColor="1F3864")
        header_font = Font(bold=True, color="FFFFFF", size=11)
        header_align = Alignment(horizontal="center", vertical="center")
        for col_idx, h in enumerate(headers, 1):
            c = ws.cell(row=1, column=col_idx, value=h)
            c.font = header_font
            c.fill = header_fill
            c.alignment = header_align

        row_ptr = 2
        for i in range(len(sheet1_df)):
            date_val = sheet1_df.iloc[i].get('Date')
            libelle = sheet1_df.iloc[i].get('Libellé', '')
            montant = float(montant_series.iloc[i])

            c_date = ws.cell(row=row_ptr, column=1, value=date_val)
            c_date.number_format = 'yyyy-mm-dd'

            ws.cell(row=row_ptr, column=2, value=libelle)

            c_montant = ws.cell(row=row_ptr, column=3, value=montant)
            # Convention bancaire : crédit sans signe (format standard), débit = signe (-)
            c_montant.number_format = '#,##0;-#,##0'

            c_solde = ws.cell(row=row_ptr, column=4)
            if row_ptr == 2:
                c_solde.value = f"={opening_balance:.0f}+C{row_ptr}"
            else:
                c_solde.value = f"=D{row_ptr - 1}+C{row_ptr}"
            c_solde.number_format = '#,##0;-#,##0'

            row_ptr += 1

        ws.column_dimensions['A'].width = 19.11
        ws.column_dimensions['B'].width = 80.55
        ws.column_dimensions['C'].width = 16
        ws.column_dimensions['D'].width = 18
        ws.freeze_panes = "A5"

        wb.save(excel_buffer)
        excel_buffer.seek(0)

        # Le fichier Excel de sortie porte le même nom que le PDF uploadé.
        source_pdf_name = (
            st.session_state.get("uploaded_file_name")
            or (uploaded_file.name if uploaded_file else None)
            or f"EXPORT_{st.session_state.banque_selectionnee}.pdf"
        )
        excel_file_name = f"{os.path.splitext(source_pdf_name)[0]}.xlsx"

        st.download_button(
            label="📥 Télécharger Excel",
            data=excel_buffer.getvalue(),
            file_name=excel_file_name,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary",
            use_container_width=True,
        )

    st.success("✅ Export prêt !")
