"""
Configuration des banques pour le système d'extraction de relevés bancaires.
Définit le schéma JSON standardisé et les spécificités de chaque banque (format, clés, prompt LLM).
"""

from typing import Dict, Any, List

# ---------------------------------------------------------------------------
# Schéma JSON standardisé attendu des modèles LLM
# ---------------------------------------------------------------------------
BANK_STATEMENT_SCHEMA: Dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "bank_name": {
            "type": "STRING",
            "description": "Nom officiel de la banque (ex: CCA BANK, AFRILAND FIRST BANK, BGFI, UBA, etc.)"
        },
        "account_number": {
            "type": "STRING",
            "description": "Numéro de compte complet exact extrait du document"
        },
        "account_holder": {
            "type": "STRING",
            "description": "Nom du titulaire du compte exact extrait du document"
        },
        "period_start": {
            "type": "STRING",
            "description": "Date de début de la période du relevé (format YYYY-MM-DD)"
        },
        "period_end": {
            "type": "STRING",
            "description": "Date de fin de la période du relevé (format YYYY-MM-DD)"
        },
        "opening_balance": {
            "type": "NUMBER",
            "description": "Solde initial / solde à nouveau du compte au début de la période"
        },
        "closing_balance": {
            "type": "NUMBER",
            "description": "Solde final / nouveau solde du compte à la fin de la période"
        },
        "currency": {
            "type": "STRING",
            "description": "Devise du compte (ex: XAF, EUR, USD)"
        },
        "transactions": {
            "type": "ARRAY",
            "description": "Liste chronologique de toutes les transactions du relevé",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "date": {
                        "type": "STRING",
                        "description": "Date de la transaction / opération (format YYYY-MM-DD). Pour BGFI, utiliser la Date de Valeur comme date de l'opération."
                    },
                    "value_date": {
                        "type": "STRING",
                        "description": "Date de valeur de la transaction (format YYYY-MM-DD)"
                    },
                    "description": {
                        "type": "STRING",
                        "description": "Libellé / description complète de l'opération"
                    },
                    "reference": {
                        "type": "STRING",
                        "description": "Numéro de pièce / référence de la transaction"
                    },
                    "debit": {
                        "type": "NUMBER",
                        "description": "Montant au débit (retrait/débit/charge). Null ou 0.0 si crédit."
                    },
                    "credit": {
                        "type": "NUMBER",
                        "description": "Montant au crédit (dépôt/remise/avoir). Null ou 0.0 si débit."
                    },
                    "balance": {
                        "type": "NUMBER",
                        "description": "Solde après la transaction si indiqué dans le relevé"
                    }
                },
                "required": ["date", "description"]
            }
        }
    },
    "required": ["bank_name", "account_number", "transactions"]
}

# ---------------------------------------------------------------------------
# Liste complète des banques et microfinances reconnues (Annuaire 2026)
# ---------------------------------------------------------------------------
KNOWN_BANKS: List[str] = [
    # Banques Classiques / Principales
    "CCA BANK",
    "AFRILAND FIRST BANK",
    "AFB/MC2",
    "BGFI",
    "BGFI BANK",
    "UBA",
    "UNITED BANK FOR AFRICA",
    "UNION BANK OF CAMEROON PLC",
    "AFG ATLANTIQUE BANQUE",
    "ATLANTIQUE BANQUE",
    "CBC BANK",
    "COMMERCIAL BANK CAMEROUN",
    "ECOBANK",
    "AFRICA GOLDEN BANK",
    "A. GOLDEN BANK",
    "SOCIETE GENERALE",
    "BICEC",
    "SCB CAMEROUN",

    # Microfinances / Établissements de crédit
    "MUPECI",
    "RURAL INVESTMENT CREDIT",
    "RIC",
    "FIGEC",
    "ADVANS",
    "CEPAC",
    "CCEFI",
    "FINANCIAL HOUSE",
    "UNICS",
    "EXPRESS UNION",
    "LA REGIONALE"
]

# ---------------------------------------------------------------------------
# Instructions spécifiques par banque pour l'extraction LLM
# ---------------------------------------------------------------------------
BANK_SPECIFIC_INSTRUCTIONS: Dict[str, str] = {
    "BGFI": (
        "ATTENTION SPÉCIFICITÉ BGFI : Pour BGFI / BGFI BANK, la 'Date de Valeur' DOIT ABSOLUMENT être utilisée "
        "comme date principale de l'opération ('date'). Remplir également le champ 'value_date' avec cette même date. "
        "Si la Date de Valeur est disponible, elle prime toujours sur la date de comptabilisation/saisie."
    ),
    "BGFI BANK": (
        "ATTENTION SPÉCIFICITÉ BGFI : Pour BGFI / BGFI BANK, la 'Date de Valeur' DOIT ABSOLUMENT être utilisée "
        "comme date principale de l'opération ('date'). Remplir également le champ 'value_date' avec cette même date. "
        "Si la Date de Valeur est disponible, elle prime toujours sur la date de comptabilisation/saisie."
    ),
    "AFRILAND FIRST BANK": (
        "Pour Afriland First Bank, veiller à bien distinguer la référence de la pièce du libellé de l'opération."
    ),
    "UBA": (
        "Pour UBA (United Bank for Africa), s'assurer d'extraire le numéro de compte complet à 13 ou 23 chiffres."
    ),
    "CCA BANK": (
        "Pour CCA Bank, vérifier attentivement les colonnes Débit et Crédit qui sont souvent bien séparées."
    ),
    "CBC BANK": (
        "Pour Commercial Bank Cameroun (CBC), extraire l'intégralité du libellé de transaction."
    )
}

def get_bank_prompt_instruction(bank_hint: str = "") -> str:
    """
    Génère les instructions complémentaires du prompt LLM en fonction de la banque détectée.
    """
    bank_clean = bank_hint.upper().strip() if bank_hint else ""
    instructions = [
        "Extraire fidèlement toutes les transactions du relevé bancaire.",
        "S'assurer que tous les montants numériques sont convertis en nombres flottants (ex: 125000.0).",
        "Convertir toutes les dates au format ISO YYYY-MM-DD."
    ]
    
    if "BGFI" in bank_clean:
        instructions.append(BANK_SPECIFIC_INSTRUCTIONS["BGFI"])
    else:
        # Instruction générale sur les spécificités de banques
        instructions.append(
            "REMARQUE IMPORTANTE : Si le relevé provient de BGFI / BGFI BANK, vous devez utiliser la Date de Valeur "
            "comme date principale de la transaction ('date')."
        )
        
    for key, spec in BANK_SPECIFIC_INSTRUCTIONS.items():
        if key in bank_clean and key not in ["BGFI", "BGFI BANK"]:
            instructions.append(spec)
            
    return "\n".join(f"- {inst}" for inst in instructions)
