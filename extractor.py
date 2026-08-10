"""
Module principal d'extraction pour les relevés bancaires.
Combine la détection automatique de la banque, la lecture PDF locale (pdfplumber/pypdf) 
et l'extraction avancée via modèles d'IA (Gemini / OpenRouter).
"""

import sys
import os

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

import io
import re
import logging
from typing import Dict, Any, Tuple, Optional, List
import pandas as pd

import bank_configs
import accounts_database
import cleaner
import extractor_gemini
import extractor_openrouter

KNOWN_BANKS = getattr(bank_configs, 'KNOWN_BANKS', [])
ACCOUNTS_DIRECTORY = getattr(accounts_database, 'ACCOUNTS_DIRECTORY', [])
match_account_details = getattr(accounts_database, 'match_account_details', None)
clean_bank_data = getattr(cleaner, 'clean_bank_data', None)
clean_amount = getattr(cleaner, 'clean_amount', None)

logger = logging.getLogger(__name__)

def detect_bank_from_pdf_text(text: str) -> Tuple[str, Optional[Dict[str, str]]]:
    """Détecte automatiquement la banque et retrouve les infos de compte."""
    text_upper = text.upper()
    detected_bank = ""
    for bank in KNOWN_BANKS:
        if bank.upper() in text_upper:
            detected_bank = bank
            break
            
    matched_account = None
    if match_account_details:
        for entry in ACCOUNTS_DIRECTORY:
            acc_num = entry.get("account_number", "").replace(" ", "").replace("-", "")
            clean_text_nums = re.sub(r'[^\dwW]', '', text)
            if acc_num and acc_num.lower() in clean_text_nums.lower():
                matched_account = entry
                if not detected_bank:
                    detected_bank = entry.get("bank", "")
                break
            
    return detected_bank or "Banque Non Spécifiée", matched_account

def extract_pdf_raw_text(pdf_bytes: bytes) -> str:
    """Extraite le texte brut d'un fichier PDF."""
    full_text = ""
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                txt = page.extract_text()
                if txt:
                    full_text += txt + "\n"
    except Exception as e:
        logger.warning(f"pdfplumber: {e}")
        try:
            import pypdf
            reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
            for page in reader.pages:
                txt = page.extract_text()
                if txt:
                    full_text += txt + "\n"
        except Exception as ex:
            logger.error(f"pypdf: {ex}")
    return full_text

def parse_local_pdf(pdf_bytes: bytes, bank_hint: str = "") -> Dict[str, Any]:
    """Parser local pour relevés PDF."""
    text = extract_pdf_raw_text(pdf_bytes)
    detected_bank, matched_acc = detect_bank_from_pdf_text(text)
    
    bank_name = bank_hint or detected_bank
    account_number = matched_acc["account_number"] if matched_acc else ""
    account_holder = matched_acc["holder"] if matched_acc else ""
    
    return {
        "bank_name": bank_name,
        "account_number": account_number,
        "account_holder": account_holder,
        "period_start": "",
        "period_end": "",
        "opening_balance": None,
        "closing_balance": None,
        "currency": "XAF",
        "transactions": []
    }

def process_bank_statement_pdf(
    pdf_bytes: bytes,
    extraction_method: str = "AUTO",
    gemini_key: str = "",
    openrouter_key: str = "",
    bank_hint: str = "",
    force_bgfi_date: bool = False
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Fonction principale d'extraction et nettoyage."""
    raw_data = None
    
    if (extraction_method == "GEMINI" or (extraction_method == "AUTO" and gemini_key)) and hasattr(extractor_gemini, 'extract_statement_with_gemini'):
        try:
            raw_data = extractor_gemini.extract_statement_with_gemini(pdf_bytes, api_key=gemini_key, bank_hint=bank_hint)
        except Exception as e:
            logger.warning(f"Échec Gemini: {e}")
            
    if not raw_data and (extraction_method == "OPENROUTER" or (extraction_method == "AUTO" and openrouter_key)) and hasattr(extractor_openrouter, 'extract_statement_with_openrouter'):
        try:
            raw_data = extractor_openrouter.extract_statement_with_openrouter(pdf_bytes, api_key=openrouter_key, bank_hint=bank_hint)
        except Exception as e:
            logger.warning(f"Échec OpenRouter: {e}")
            
    if not raw_data:
        raw_data = parse_local_pdf(pdf_bytes, bank_hint=bank_hint)
        
    if clean_bank_data:
        df, meta = clean_bank_data(raw_data, bank_hint=bank_hint, force_bgfi_date=force_bgfi_date)
    else:
        df, meta = pd.DataFrame(raw_data.get("transactions", [])), raw_data
        
    return df, meta

# Alias de compatibilité pour garantir l'importation quel que soit le nom attendu
extract_bank_statement = process_bank_statement_pdf
extract_statement = process_bank_statement_pdf
process_pdf = process_bank_statement_pdf
