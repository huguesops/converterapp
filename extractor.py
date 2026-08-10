"""
Module principal d'extraction pour les relevés bancaires.
Combine la détection automatique de la banque, la lecture PDF locale (pdfplumber/pypdf) 
et l'extraction avancée via modèles d'IA (Gemini / OpenRouter).
"""

import io
import re
import logging
from typing import Dict, Any, Tuple, Optional, List
import pandas as pd
import sys
import os

sys.path.append(os.path.dirname(__file__))
from bank_configs import KNOWN_BANKS
from accounts_database import ACCOUNTS_DIRECTORY, match_account_details
from cleaner import clean_bank_data, clean_amount
from extractor_gemini import extract_statement_with_gemini
from extractor_openrouter import extract_statement_with_openrouter

logger = logging.getLogger(__name__)

def detect_bank_from_pdf_text(text: str) -> Tuple[str, Optional[Dict[str, str]]]:
    """
    Détecte automatiquement la banque et retrouve les infos de compte à partir du texte extrait du PDF.
    """
    text_upper = text.upper()
    detected_bank = ""
    
    # 1. Recherche parmi les banques connues
    for bank in KNOWN_BANKS:
        if bank.upper() in text_upper:
            detected_bank = bank
            break
            
    # 2. Recherche par numéro de compte dans l'annuaire
    matched_account = None
    for entry in ACCOUNTS_DIRECTORY:
        acc_num = entry["account_number"].replace(" ", "").replace("-", "")
        clean_text_nums = re.sub(r'[^\dwW]', '', text)
        if acc_num and acc_num.lower() in clean_text_nums.lower():
            matched_account = entry
            if not detected_bank:
                detected_bank = entry["bank"]
            break
            
    return detected_bank or "Banque Non Spécifiée", matched_account

def extract_pdf_raw_text(pdf_bytes: bytes) -> str:
    """Extraite le texte brut d'un fichier PDF via pdfplumber ou pypdf."""
    full_text = ""
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                txt = page.extract_text()
                if txt:
                    full_text += txt + "\n"
    except Exception as e:
        logger.warning(f"Échec de l'extraction par pdfplumber: {e}")
        try:
            import pypdf
            reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
            for page in reader.pages:
                txt = page.extract_text()
                if txt:
                    full_text += txt + "\n"
        except Exception as ex:
            logger.error(f"Échec de l'extraction par pypdf: {ex}")
            
    return full_text

def extract_tables_pdfplumber(pdf_bytes: bytes) -> List[List[str]]:
    """Tente d'extraire les tables directement via pdfplumber."""
    all_rows = []
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                tables = page.extract_tables()
                for table in tables:
                    for row in table:
                        if row and any(cell for cell in row if cell and str(cell).strip()):
                            all_rows.append([str(cell or "").strip() for cell in row])
    except Exception as e:
        logger.warning(f"Échec d'extraction des tables par pdfplumber: {e}")
    return all_rows

def parse_local_pdf(pdf_bytes: bytes, bank_hint: str = "") -> Dict[str, Any]:
    """
    Parser local basé sur des expressions régulières et l'extraction de tables pdfplumber.
    """
    text = extract_pdf_raw_text(pdf_bytes)
    detected_bank, matched_acc = detect_bank_from_pdf_text(text)
    
    bank_name = bank_hint or detected_bank
    account_number = matched_acc["account_number"] if matched_acc else ""
    account_holder = matched_acc["holder"] if matched_acc else ""
    
    # Si le numéro de compte n'est pas trouvé dans l'annuaire, tenter un regex générique
    if not account_number:
        acc_match = re.search(r'(?:compte|n°|numéro)\s*:\s*([\d\s\-]{8,25})', text, re.IGNORECASE)
        if acc_match:
            account_number = acc_match.group(1).strip()
            
    # Détection des dates de période
    dates = re.findall(r'\b(\d{2}[/\.-]\d{2}[/\.-]\d{4}|\d{4}[/\.-]\d{2}[/\.-]\d{2})\b', text)
    period_start = dates[0] if len(dates) > 0 else ""
    period_end = dates[1] if len(dates) > 1 else ""
    
    # Extraire les lignes du tableau
    rows = extract_tables_pdfplumber(pdf_bytes)
    transactions = []
    
    # Pattern regex pour lignes de transaction
    # (ex: 12/05/2026 14/05/2026 VIREMENT CLIENT REF123 150000.00)
    tx_pattern = re.compile(
        r'(\d{2}[/\.-]\d{2}[/\.-]\d{4})\s+'                  # Date op
        r'(?:(\d{2}[/\.-]\d{2}[/\.-]\d{4})\s+)?'             # Date valeur (optionnelle)
        r'(.+?)\s+'                                           # Libellé
        r'([\d\s.,]{3,15})\s*$'                              # Montant/Solde
    )
    
    if rows:
        for row in rows:
            # Recherche de colonnes contenant des dates et montants
            row_str = " | ".join(row)
            date_matches = re.findall(r'\b\d{2}[/\.-]\d{2}[/\.-]\d{4}\b', row_str)
            if date_matches:
                op_date = date_matches[0]
                val_date = date_matches[1] if len(date_matches) > 1 else op_date
                
                # Extraire les nombres (débit/crédit/solde)
                numbers = [clean_amount(cell) for cell in row if clean_amount(cell) is not None]
                debit = numbers[0] if len(numbers) > 0 else None
                credit = numbers[1] if len(numbers) > 1 else None
                balance = numbers[2] if len(numbers) > 2 else None
                
                desc = " ".join([c for c in row if c and not re.match(r'^\d{2}[/\.-]\d{2}[/\.-]\d{4}$', c) and clean_amount(c) is None])
                
                transactions.append({
                    "date": op_date,
                    "value_date": val_date,
                    "description": desc or "Opération bancaire",
                    "reference": "",
                    "debit": debit,
                    "credit": credit,
                    "balance": balance
                })
    else:
        # Tenter d'extraire ligne par ligne du texte
        for line in text.split('\n'):
            line = line.strip()
            match = tx_pattern.search(line)
            if match:
                op_date = match.group(1)
                val_date = match.group(2) or op_date
                desc = match.group(3)
                amount = clean_amount(match.group(4))
                
                transactions.append({
                    "date": op_date,
                    "value_date": val_date,
                    "description": desc,
                    "reference": "",
                    "debit": amount if amount and amount < 0 else None,
                    "credit": amount if amount and amount > 0 else None,
                    "balance": None
                })

    return {
        "bank_name": bank_name,
        "account_number": account_number,
        "account_holder": account_holder,
        "period_start": period_start,
        "period_end": period_end,
        "opening_balance": None,
        "closing_balance": None,
        "currency": "XAF",
        "transactions": transactions
    }

def process_bank_statement_pdf(
    pdf_bytes: bytes,
    extraction_method: str = "AUTO",
    gemini_key: str = "",
    openrouter_key: str = "",
    bank_hint: str = "",
    force_bgfi_date: bool = False
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    Fonction orchestratrice principale pour l'extraction et le traitement d'un relevé bancaire PDF.
    
    Paramètres :
    - pdf_bytes : Octets du fichier PDF
    - extraction_method : "AUTO", "GEMINI", "OPENROUTER" ou "LOCAL"
    - gemini_key : Clé API Gemini
    - openrouter_key : Clé API OpenRouter
    - bank_hint : Banque suggérée ou sélectionnée
    - force_bgfi_date : Forcer l'application de la règle Date de Valeur -> Date Opération
    """
    raw_data = None
    
    if extraction_method == "GEMINI" or (extraction_method == "AUTO" and gemini_key):
        try:
            raw_data = extract_statement_with_gemini(pdf_bytes, api_key=gemini_key, bank_hint=bank_hint)
        except Exception as e:
            logger.warning(f"Échec extraction Gemini ({e}), passage aux alternatives...")
            
    if not raw_data and (extraction_method == "OPENROUTER" or (extraction_method == "AUTO" and openrouter_key)):
        try:
            raw_data = extract_statement_with_openrouter(pdf_bytes, api_key=openrouter_key, bank_hint=bank_hint)
        except Exception as e:
            logger.warning(f"Échec extraction OpenRouter ({e}), passage à l'extraction locale...")
            
    if not raw_data:
        raw_data = parse_local_pdf(pdf_bytes, bank_hint=bank_hint)
        
    # Nettoyage et application des règles métiers (BGFI, formats, totaux, annuaire)
    df, meta = clean_bank_data(raw_data, bank_hint=bank_hint, force_bgfi_date=force_bgfi_date)
    return df, meta
