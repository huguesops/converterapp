"""
Application Streamlit : Convertisseur de Relevés Bancaires PDF en Excel Exploitable.
Prend en charge toutes les banques et microfinances de l'Annuaire 2026 et la spécificité BGFI.
"""

import streamlit as st
import pandas as pd
import sys
import os

sys.path.append(os.path.dirname(__file__))

from bank_configs import KNOWN_BANKS
from accounts_database import ACCOUNTS_DIRECTORY, match_account_details
from extractor import process_bank_statement_pdf
from exporter import export_bank_statement_to_excel
from token_counter import estimate_pdf_tokens

# ---------------------------------------------------------------------------
# Configuration de la page Streamlit
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Convertisseur Relevés Bancaires PDF -> Excel",
    page_icon="🏦",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Style CSS personnalisé
st.markdown("""
<style>
    .main-header {
        font-size: 2.2rem;
        color: #1F4E78;
        font-weight: 700;
        margin-bottom: 0.2rem;
    }
    .sub-header {
        font-size: 1.1rem;
        color: #555555;
        margin-bottom: 1.5rem;
    }
    .bgfi-badge {
        background-color: #FFF2CC;
        color: #8A6D3B;
        padding: 0.4rem 0.8rem;
        border-radius: 5px;
        border: 1px solid #FAEBCC;
        font-weight: 600;
        margin-bottom: 1rem;
    }
    .stButton>button {
        background-color: #1F4E78;
        color: white;
        border-radius: 6px;
        font-weight: 600;
    }
</style>
""", unsafe_allow_text=True)

st.markdown('<div class="main-header">🏦 Convertisseur de Relevés Bancaires PDF vers Excel</div>', unsafe_allow_text=True)
st.markdown('<div class="sub-header">Extrayez, nettoyez et structurez vos relevés de banques et microfinances camerounaises en fichiers Excel comptables exploitables.</div>', unsafe_allow_text=True)

# ---------------------------------------------------------------------------
# Barre Latérale (Sidebar) - Configuration & Sélections
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("⚙️ Paramètres & Banques")
    
    # 1. Choix de la banque ou microfinance
    st.subheader("1. Établissement Financier")
    
    banques_classiques = [
        "Détection Automatique",
        "CCA BANK",
        "AFRILAND FIRST BANK",
        "AFB/MC2",
        "BGFI",
        "BGFI BANK",
        "UBA",
        "UNION BANK OF CAMEROON PLC",
        "AFG ATLANTIQUE BANQUE",
        "CBC BANK",
        "ECOBANK",
        "AFRICA GOLDEN BANK"
    ]
    
    microfinances = [
        "MUPECI",
        "RURAL INVESTMENT CREDIT",
        "FIGEC",
        "ADVANS",
        "CEPAC",
        "CCEFI",
        "FINANCIAL HOUSE",
        "UNICS"
    ]
    
    selected_bank = st.selectbox(
        "Sélectionner la banque / EMF :",
        options=["Détection Automatique"] + banques_classiques[1:] + microfinances,
        help="Choisissez l'établissement du relevé ou laissez sur Détection Automatique."
    )
    
    bank_hint = "" if selected_bank == "Détection Automatique" else selected_bank
    
    # 2. Spécificité BGFI - Date de Valeur
    st.subheader("2. Règles Spécifiques")
    is_bgfi_selected = "BGFI" in selected_bank.upper()
    
    use_bgfi_rule = st.checkbox(
        "📌 Option BGFI : Date de Valeur comme Date d'Opération",
        value=is_bgfi_selected,
        help="Spécificité propre à BGFI : force l'utilisation de la Date de Valeur comme Date des Opérations dans le tableau nettoyé."
    )
    
    if is_bgfi_selected or use_bgfi_rule:
        st.markdown('<div class="bgfi-badge">⚡ Règle BGFI active : La Date de Valeur remplacera la Date d\'opération.</div>', unsafe_allow_text=True)

    # 3. Moteur d'extraction
    st.subheader("3. Moteur d'Extraction IA")
    extraction_mode = st.radio(
        "Méthode d'extraction :",
        options=["Auto / Hybride", "Google Gemini API", "OpenRouter AI", "Extraction Locale (pdfplumber)"],
        index=0
    )
    
    gemini_key = st.text_input("Clé API Google Gemini :", type="password", help="Optionnel mais recommandé pour les scans complexes.")
    openrouter_key = st.text_input("Clé API OpenRouter :", type="password", help="Optionnel pour utiliser Claude-3.5-Sonnet ou GPT-4o.")
    
    st.divider()
    st.markdown("### 📖 Annuaire des Comptes 2026")
    with st.expander("Voir les comptes répertoriés"):
        df_acc = pd.DataFrame(ACCOUNTS_DIRECTORY)
        st.dataframe(df_acc, use_container_width=True, hide_index=True)

# ---------------------------------------------------------------------------
# Zone Principale - Chargement PDF & Traitement
# ---------------------------------------------------------------------------
uploaded_file = st.file_uploader("📂 Déposez votre relevé bancaire PDF ici :", type=["pdf"])

if uploaded_file is not None:
    pdf_bytes = uploaded_file.read()
    st.info(f"📄 Fichier chargé : **{uploaded_file.name}** ({len(pdf_bytes) / 1024:.1f} KB - ~{estimate_pdf_tokens(pdf_bytes)} tokens estimés)")
    
    if st.button("🚀 Lancer la Conversion en Excel", use_container_width=True):
        with st.spinner("Analyse et structuration du relevé en cours..."):
            
            method_code = "AUTO"
            if extraction_mode == "Google Gemini API":
                method_code = "GEMINI"
            elif extraction_mode == "OpenRouter AI":
                method_code = "OPENROUTER"
            elif extraction_mode == "Extraction Locale (pdfplumber)":
                method_code = "LOCAL"
                
            try:
                df, meta = process_bank_statement_pdf(
                    pdf_bytes=pdf_bytes,
                    extraction_method=method_code,
                    gemini_key=gemini_key,
                    openrouter_key=openrouter_key,
                    bank_hint=bank_hint,
                    force_bgfi_date=use_bgfi_rule
                )
                
                st.session_state["extracted_df"] = df
                st.session_state["extracted_meta"] = meta
                st.success("✅ Conversion terminée avec succès !")
                
            except Exception as e:
                st.error(f"❌ Erreur lors du traitement du relevé : {str(e)}")

# ---------------------------------------------------------------------------
# Visualisation & Exportation des Résultats
# ---------------------------------------------------------------------------
if "extracted_df" in st.session_state and "extracted_meta" in st.session_state:
    df = st.session_state["extracted_df"]
    meta = st.session_state["extracted_meta"]
    
    st.divider()
    st.subheader("📊 Métadonnées & Identification du Compte")
    
    m_col1, m_col2, m_col3, m_col4, m_col5 = st.columns(5)
    
    m_col1.metric("Banque", meta.get("bank_name", "Inconnue"))
    m_col2.metric("Titulaire", meta.get("account_holder", "Non identifié"))
    m_col3.metric("Numéro de Compte", meta.get("account_number", "Inconnu"))
    
    tot_deb = df["Débit"].sum() if "Débit" in df.columns else 0.0
    tot_cred = df["Crédit"].sum() if "Crédit" in df.columns else 0.0
    
    m_col4.metric("Total Débits (Sorties)", f"{tot_deb:,.2f} XAF")
    m_col5.metric("Total Crédits (Entrées)", f"{tot_cred:,.2f} XAF")
    
    if meta.get("is_bgfi_applied"):
        st.warning("⚠️ Règle BGFI appliquée : Les dates affichées dans la colonne 'Date' correspondent aux Dates de Valeur.")

    st.subheader("📝 Aperçu du Relevé Nettoyé (Éditable)")
    edited_df = st.data_editor(
        df,
        use_container_width=True,
        num_rows="dynamic",
        column_config={
            "Débit": st.column_config.NumberColumn("Débit (XAF)", format="%.2f"),
            "Crédit": st.column_config.NumberColumn("Crédit (XAF)", format="%.2f"),
            "Solde": st.column_config.NumberColumn("Solde (XAF)", format="%.2f")
        }
    )
    
    st.subheader("📥 Téléchargement de l'Excel Exploitable")
    
    # Génération du fichier Excel
    excel_data = export_bank_statement_to_excel(edited_df, meta)
    
    file_name_out = f"Releve_{meta.get('bank_name', 'Banque')}_{meta.get('account_number', 'Compte')}.xlsx".replace(" ", "_")
    
    st.download_button(
        label="💾 Télécharger le Fichier Excel (.xlsx)",
        data=excel_data,
        file_name=file_name_out,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True
    )
