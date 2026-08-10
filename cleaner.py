"""
Nettoyage et structuration des données de relevés bancaires.
Applique la règle propre à BGFI (Date de valeur -> Date d'opération) et la mise en forme des colonnes.
"""

import pandas as pd
import re
from typing import Dict, Any, Tuple, Optional
import sys
import os

sys.path.append(os.path.dirname(__file__))
from accounts_database import match_account_details

def clean_amount(val: Any) -> Optional[float]:
    """Nettoie et convertit une valeur en float."""
    if pd.isna(val) or val is None or str(val).strip() in ["", "-", "None", "nan", "null"]:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip()
    s = re.sub(r'[^\d.,\-]', '', s)
    if not s:
        return None
    if ',' in s and '.' in s:
        if s.find('.') < s.find(','):
            s = s.replace('.', '').replace(',', '.')
        else:
            s = s.replace(',', '')
    elif ',' in s:
        s = s.replace(',', '.')
    try:
        return float(s)
    except ValueError:
        return None

def clean_bank_data(data: Dict[str, Any], bank_hint: str = "", force_bgfi_date: bool = False) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    Nettoie les données brutes extraites et applique les règles métiers (dont BGFI Date de valeur).
    """
    bank_name = data.get("bank_name", bank_hint or "Banque Non Spécifiée").upper().strip()
    account_number = data.get("account_number", "").strip()
    account_holder = data.get("account_holder", "").strip()
    
    is_bgfi = "BGFI" in bank_name or force_bgfi_date
    
    # Rapprochement automatique avec l'annuaire des comptes
    account_info = match_account_details(account_number, bank_name)
    if account_info:
        if not account_holder or account_holder.lower() in ["inconnu", "unknown", ""]:
            account_holder = account_info["holder"]
        if not bank_name or bank_name == "BANQUE NON SPÉCIFIÉE":
            bank_name = account_info["bank"]
            
    meta = {
        "bank_name": bank_name,
        "account_number": account_number,
        "account_holder": account_holder,
        "period_start": data.get("period_start", ""),
        "period_end": data.get("period_end", ""),
        "opening_balance": clean_amount(data.get("opening_balance")),
        "closing_balance": clean_amount(data.get("closing_balance")),
        "currency": data.get("currency", "XAF"),
        "is_bgfi_applied": is_bgfi
    }
    
    raw_txs = data.get("transactions", [])
    if not raw_txs:
        df = pd.DataFrame(columns=["Date", "Date Valeur", "Référence", "Libellé / Description", "Débit", "Crédit", "Solde"])
        return df, meta
        
    cleaned_rows = []
    for tx in raw_txs:
        op_date = str(tx.get("date", "") or "").strip()
        val_date = str(tx.get("value_date", "") or "").strip()
        
        # Spécificité BGFI : la Date de valeur devient la Date des opérations
        if is_bgfi:
            if val_date and val_date.lower() not in ["none", "nan", ""]:
                op_date = val_date
            elif op_date:
                val_date = op_date
                
        debit = clean_amount(tx.get("debit"))
        credit = clean_amount(tx.get("credit"))
        balance = clean_amount(tx.get("balance"))
        
        cleaned_rows.append({
            "Date": op_date,
            "Date Valeur": val_date if val_date else op_date,
            "Référence": str(tx.get("reference", "") or "").strip(),
            "Libellé / Description": str(tx.get("description", "") or "").strip(),
            "Débit": debit if debit and debit > 0 else None,
            "Crédit": credit if credit and credit > 0 else None,
            "Solde": balance
        })
        
    df = pd.DataFrame(cleaned_rows)
    return df, meta
