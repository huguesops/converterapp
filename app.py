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
    })

# ====================== SIDEBAR ======================
with st.sidebar:
    st.title("🏦 SKAB Extractor")
    st.caption("Extraction et conversion de relevés bancaires camerounais")

    uploaded_file = st.file_uploader("📄 Charger le relevé PDF", type=["pdf"])

    banque_sel = st.selectbox("🏦 Banque émettrice", [
        "Financial House S.A", "BGFI Bank", "UNICS", "CEPAC", "ADVANS",
        "MUPECI", "SCB Cameroun", "BICEC", "UBA Cameroun", "Autre banque"
    ], index=2)
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
if uploaded_file and not st.session_state.extraction_done and not st.session_state.show_confirm:
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
                with st.spinner("Extraction en cours..."):
                    try:
                        progress_bar = st.progress(0, text="Initialisation...")

                        def progress_callback(step, msg):
                            progress_bar.progress(min(step, 100), text=msg)

                        extractor = OpenRouterExtractor(
                            api_key=get_openrouter_key(),
                            mode=method,
                            banque_nom=st.session_state.banque_selectionnee,
                            progress_callback=progress_callback,
                            verbose_debug=False,
                        )

                        df_raw = extractor.extract(st.session_state.pdf_bytes_cache)

                        cleaner = DataCleaner()
                        df_clean = cleaner.clean(df_raw, banque_nom=st.session_state.banque_selectionnee)

                        st.session_state.df_clean = df_clean
                        st.session_state.stats = cleaner.get_statistics(df_clean)
                        st.session_state.extraction_done = True
                        st.session_state.show_confirm = False
                        st.rerun()

                    except Exception as e:
                        st.error(f"❌ Erreur lors de l'extraction : {str(e)}")

# ====================== RÉSULTATS ======================
if st.session_state.extraction_done and st.session_state.df_clean is not None:
    df_display = st.session_state.df_clean.copy()

    # Nettoyage dates
    df_display['Date'] = pd.to_datetime(df_display['Date'], dayfirst=True, errors='coerce')
    df_display = df_display.dropna(subset=['Date'])

    # Métriques - Cartes personnalisées visibles
    stats = st.session_state.stats
    
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
            <div class="label">Solde d'ouverture</div>
            <div class="value {so_class}">{so_val}</div>
        </div>""", unsafe_allow_html=True)
    
    with col2:
        sc = stats.get('solde_cloture')
        sc_class = "positive" if (sc is not None and sc >= 0) else "negative"
        sc_val = f"{sc:,.0f} FCFA" if sc is not None else "N/A"
        st.markdown(f"""
        <div class="metric-card">
            <div class="label">Solde de clôture</div>
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

    # Afficher toutes les colonnes : Date, Référence, Libellé, Débit, Crédit, Solde
    display_cols = ['Date', 'Référence', 'Libellé', 'Débit', 'Crédit', 'Solde']
    display_df = df_display[[c for c in display_cols if c in df_display.columns]]
    st.dataframe(display_df, use_container_width=True, height=400)

    # --- EXPORT ---
    st.divider()
    st.subheader("💾 Export")

    col_csv, col_xlsx = st.columns(2)

    with col_csv:
        # CSV Odoo
        odoo_export = df_display.copy()
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
            # Feuille 1 : Données complètes
            sheet1_cols = ['Date', 'Référence', 'Libellé', 'Débit', 'Crédit', 'Solde']
            sheet1_df = df_display[[c for c in sheet1_cols if c in df_display.columns]]
            sheet1_df.to_excel(writer, sheet_name='Relevé', index=False)

            # Feuille 2 : Export Odoo
            odoo_export.to_excel(writer, sheet_name='Export Odoo', index=False)

            # Feuille 3 : Résumé
            résumé_df = pd.DataFrame([
                ('Période début', stats.get('periode_debut', '')),
                ('Période fin', stats.get('periode_fin', '')),
                ('Total crédits', stats.get('total_credit', 0)),
                ('Total débits', stats.get('total_debit', 0)),
                ('Solde net', stats.get('net', 0)),
                ('Solde ouverture', stats.get('solde_ouverture', 'N/A')),
                ('Solde clôture', stats.get('solde_cloture', 'N/A')),
                ('Nombre de transactions', stats.get('total_transactions', 0)),
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
