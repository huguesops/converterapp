"""
SKAB Bank Statement Extractor - Edition Comptabilité Odoo 18
Génère CSV + Excel avec colonne balance
"""

import streamlit as st
import pandas as pd
import io
import plotly.express as px
from datetime import datetime

# Modules personnalisés
from extractor_openrouter import OpenRouterExtractor
from cleaner import DataCleaner
from bank_configs import get_bank_list


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
    })

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
        for k in list(st.session_state.keys()):
            del st.session_state[k]
        st.rerun()

# ====================== HEADER ======================
st.markdown('<div class="main-header"><h1>🏦 SKAB Bank Statement Extractor</h1><p>Génération de fichiers d\'importation pour la comptabilité Odoo</p></div>', unsafe_allow_html=True)

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
            <div class="label">Solde d'ouverture (tel qu'affiché sur le relevé)</div>
            <div class="value {so_class}">{so_val}</div>
        </div>""", unsafe_allow_html=True)
    
    with col2:
        sc = stats.get('solde_cloture')
        sc_class = "positive" if (sc is not None and sc >= 0) else "negative"
        sc_val = f"{sc:,.0f} FCFA" if sc is not None else "N/A"
        st.markdown(f"""
        <div class="metric-card">
            <div class="label">Solde de clôture (tel qu'affiché sur le relevé)</div>
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

    # --- CONTRÔLE RAPIDE DE COHÉRENCE ---
    # Compare le solde de clôture EXACT extrait du relevé au solde de
    # clôture que l'on obtient en partant du solde d'ouverture EXACT et en
    # y ajoutant le flux net des transactions extraites. Permet de
    # confirmer d'un coup d'œil que rien n'a été omis ou mal lu, sans avoir
    # à comparer ligne par ligne avec le PDF d'origine.
    coherent = stats.get('coherent')
    if coherent is not None:
        if coherent:
            st.success(
                "✅ Cohérence vérifiée : solde d'ouverture + flux net des transactions extraites "
                f"= {stats['solde_cloture_calcule']:,.0f} FCFA, conforme au solde de clôture affiché "
                f"sur le relevé ({stats['solde_cloture']:,.0f} FCFA)."
            )
        else:
            st.warning(
                f"⚠️ Écart de {stats['ecart_cloture']:,.0f} FCFA entre le solde de clôture affiché sur "
                f"le relevé ({stats['solde_cloture']:,.0f} FCFA) et celui recalculé à partir du solde "
                f"d'ouverture + flux net des transactions extraites ({stats['solde_cloture_calcule']:,.0f} FCFA). "
                "Cela indique probablement une ligne manquante ou un montant mal lu — vérifiez les données "
                "extraites ci-dessous par rapport au PDF original."
            )
    elif stats.get('solde_ouverture') is None or stats.get('solde_cloture') is None:
        st.info(
            "ℹ️ Solde d'ouverture et/ou de clôture non détecté(s) automatiquement dans les données "
            "extraites — vérifiez-les manuellement contre le PDF original."
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
    pc1, pc2, pc3, pc4 = st.columns(4)
    pc1.metric("Lignes", len(df_filtered))
    pc2.metric("Total crédits", f"{period_stats.get('total_credit', 0):,.0f}")
    pc3.metric("Total débits", f"{period_stats.get('total_debit', 0):,.0f}")
    pc4.metric("Flux net", f"{period_stats.get('net', 0):,.0f}")

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
        with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
            # Feuille 1 : Données de la période sélectionnée
            sheet1_cols = ['Date', 'Référence', 'Libellé', 'Débit', 'Crédit', 'Solde']
            sheet1_df = df_filtered[[c for c in sheet1_cols if c in df_filtered.columns]]
            sheet1_df.to_excel(writer, sheet_name='Relevé', index=False)

            # Feuille 2 : Export Odoo
            odoo_export.to_excel(writer, sheet_name='Export Odoo', index=False)

            # Feuille 3 : Résumé (période sélectionnée)
            résumé_df = pd.DataFrame([
                ('Période', label_periode),
                ('Total crédits', period_stats.get('total_credit', 0)),
                ('Total débits', period_stats.get('total_debit', 0)),
                ('Solde net', period_stats.get('net', 0)),
                ('Solde ouverture (relevé)', period_stats.get('solde_ouverture', 'N/A')),
                ('Solde clôture (relevé)', period_stats.get('solde_cloture', 'N/A')),
                ('Solde clôture recalculé (ouverture + flux net)', period_stats.get('solde_cloture_calcule', 'N/A')),
                ('Écart clôture', period_stats.get('ecart_cloture', 'N/A')),
                ('Nombre de transactions', period_stats.get('total_transactions', 0)),
            ], columns=['Indicateur', 'Valeur'])
            résumé_df.to_excel(writer, sheet_name='Résumé', index=False)

        excel_buffer.seek(0)
        st.download_button(
            label="📥 Télécharger Excel",
            data=excel_buffer.getvalue(),
            file_name=f"EXPORT_{st.session_state.banque_selectionnee}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary",
            use_container_width=True,
        )

    st.success("✅ Export prêt !")
