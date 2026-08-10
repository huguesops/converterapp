"""
Application Streamlit pour la conversion de relevés bancaires PDF en Excel.
Intègre la liste complète des banques du classeur 2026 et la règle spécifique BGFI.
"""

import sys
import os

# Résolution du chemin absolu du dossier de l'application pour Streamlit Cloud
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

import streamlit as st
import pandas as pd

# Imports robustes sans imports relatifs qui provoquent des erreurs sur Streamlit Cloud
import bank_configs
import accounts_database
import cleaner
import exporter
import token_counter
import extractor

# Récupération des constantes et fonctions avec fallbacks de sécurité
KNOWN_BANKS = getattr(bank_configs, 'KNOWN_BANKS', [])
ACCOUNTS_DIRECTORY = getattr(accounts_database, 'ACCOUNTS_DIRECTORY', [])
export_bank_statement_to_excel = getattr(exporter, 'export_bank_statement_to_excel', None)
estimate_pdf_tokens = getattr(token_counter, 'estimate_pdf_tokens', lambda x: 0)

# Détection de la fonction d'extraction dans extractor.py
process_bank_statement_pdf = None
for func_name in ['process_bank_statement_pdf', 'extract_bank_statement', 'extract_statement', 'process_pdf']:
    if hasattr(extractor, func_name):
        process_bank_statement_pdf = getattr(extractor, func_name)
        break

if process_bank_statement_pdf is None:
    st.error("❌ Impossible de trouver la fonction d'extraction dans extractor.py.")

st.set_page_config(
    page_title="Convertisseur Relevés Bancaires PDF -> Excel",
    page_icon="🏦",
    layout="wide"
)

st.title("🏦 Convertisseur de Relevés Bancaires PDF vers Excel")
st.caption("Conversion et structuration de relevés bancaires (Banques Classiques et Microfinances).")

# Barre latérale
with st.sidebar:
    st.header("⚙️ Configuration")
    
    all_banks = [
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
        "AFRICA GOLDEN BANK",
        "MUPECI",
        "RURAL INVESTMENT CREDIT",
        "FIGEC",
        "ADVANS",
        "CEPAC",
        "CCEFI",
        "FINANCIAL HOUSE",
        "UNICS"
    ]
    
    selected_bank = st.selectbox("Sélectionner la banque / EMF :", options=all_banks)
    bank_hint = "" if selected_bank == "Détection Automatique" else selected_bank
    
    is_bgfi = "BGFI" in selected_bank.upper()
    
    use_bgfi_rule = st.checkbox(
        "📌 Spécificité BGFI : Date de Valeur comme Date des Opérations",
        value=is_bgfi,
        help="Pour BGFI, la Date de Valeur est utilisée comme Date des Opérations."
    )
    
    if is_bgfi or use_bgfi_rule:
        st.info("⚡ Règle BGFI active : La Date de Valeur remplacera la Date d'opération dans le relevé.")
        
    extraction_mode = st.radio(
        "Moteur d'extraction :",
        options=["Auto / Hybride", "Google Gemini API", "OpenRouter AI", "Extraction Locale"]
    )
    
    gemini_key = st.text_input("Clé API Gemini :", type="password")
    openrouter_key = st.text_input("Clé API OpenRouter :", type="password")

# Traitement du fichier
uploaded_file = st.file_uploader("📂 Charger votre relevé bancaire PDF :", type=["pdf"])

if uploaded_file is not None:
    pdf_bytes = uploaded_file.read()
    st.write(f"📄 Document : **{uploaded_file.name}** ({len(pdf_bytes) / 1024:.1f} KB)")
    
    if st.button("🚀 Convertir en Excel", type="primary"):
        with st.spinner("Traitement en cours..."):
            method = "AUTO"
            if extraction_mode == "Google Gemini API":
                method = "GEMINI"
            elif extraction_mode == "OpenRouter AI":
                method = "OPENROUTER"
            elif extraction_mode == "Extraction Locale":
                method = "LOCAL"
                
            try:
                if process_bank_statement_pdf:
                    df, meta = process_bank_statement_pdf(
                        pdf_bytes=pdf_bytes,
                        extraction_method=method,
                        gemini_key=gemini_key,
                        openrouter_key=openrouter_key,
                        bank_hint=bank_hint,
                        force_bgfi_date=use_bgfi_rule
                    )
                    
                    st.session_state["extracted_df"] = df
                    st.session_state["extracted_meta"] = meta
                    st.success("✅ Conversion réussie !")
                else:
                    st.error("Fonction d'extraction introuvable dans extractor.py.")
            except Exception as e:
                st.error(f"❌ Erreur : {str(e)}")

if "extracted_df" in st.session_state and "extracted_meta" in st.session_state:
    df = st.session_state["extracted_df"]
    meta = st.session_state["extracted_meta"]
    
    st.subheader("📊 Informations Extraintes")
    c1, c2, c3 = st.columns(3)
    c1.metric("Banque", meta.get("bank_name", "N/A"))
    c2.metric("Titulaire", meta.get("account_holder", "N/A"))
    c3.metric("Numéro de Compte", meta.get("account_number", "N/A"))
    
    st.subheader("📝 Aperçu du Relevé")
    edited_df = st.data_editor(df, use_container_width=True, num_rows="dynamic")
    
    if export_bank_statement_to_excel:
        excel_bytes = export_bank_statement_to_excel(edited_df, meta)
        filename = f"Releve_{meta.get('bank_name', 'Banque')}_{meta.get('account_number', 'Compte')}.xlsx".replace(" ", "_")
        
        st.download_button(
            label="📥 Télécharger le fichier Excel (.xlsx)",
            data=excel_bytes,
            file_name=filename,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
