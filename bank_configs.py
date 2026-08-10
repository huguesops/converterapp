"""
Configuration des banques pour la conversion des relevés bancaires PDF.
Contient la liste complète des banques/microfinances du Classeur 2026 et les consignes spécifiques.
"""

from typing import Dict, Any, List

# Schéma JSON standardisé pour l'extraction de relevés bancaires
BANK_STATEMENT_SCHEMA = {
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
            "description": "Nom du titulaire du compte"
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
            "description": "Solde initial du compte au début de la période"
        },
        "closing_balance": {
            "type": "NUMBER",
            "description": "Solde final du compte à la fin de la période"
        },
        "currency": {
            "type": "STRING",
            "description": "Devise du compte (ex: XAF)"
        },
        "transactions": {
            "type": "ARRAY",
            "description": "Liste des transactions du relevé",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "date": {
                        "type": "STRING",
                        "description": "Date d'opération (YYYY-MM-DD). Pour BGFI, utiliser la Date de Valeur comme date d'opération."
                    },
                    "value_date": {
                        "type": "STRING",
                        "description": "Date de valeur (YYYY-MM-DD)"
                    },
                    "description": {
                        "type": "STRING",
                        "description": "Libellé de la transaction"
                    },
                    "reference": {
                        "type": "STRING",
                        "description": "Référence / Numéro de pièce"
                    },
                    "debit": {
                        "type": "NUMBER",
                        "description": "Montant au débit (null si crédit)"
                    },
                    "credit": {
                        "type": "NUMBER",
                        "description": "Montant au crédit (null si débit)"
                    },
                    "balance": {
                        "type": "NUMBER",
                        "description": "Solde après transaction"
                    }
                },
                "required": ["date", "description"]
            }
        }
    },
    "required": ["bank_name", "account_number", "transactions"]
}

# ---------------------------------------------------------------------------
# Liste mise à jour de toutes les banques et microfinances (Classeur 2026)
# ---------------------------------------------------------------------------
KNOWN_BANKS: List[str] = [
    # Banques Classiques
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

    # Microfinances (EMF)
    "MUPECI",
    "RURAL INVESTMENT CREDIT",
    "FIGEC",
    "ADVANS",
    "CEPAC",
    "CCEFI",
    "FINANCIAL HOUSE",
    "UNICS"
]

def get_bank_prompt_instruction(bank_hint: str = "") -> str:
    """
    Retourne les consignes spécifiques à ajouter au prompt LLM selon la banque sélectionnée.
    """
    bank_clean = bank_hint.upper().strip() if bank_hint else ""
    instructions = [
        "Extraire fidèlement toutes les transactions du relevé bancaire.",
        "Convertir tous les montants en valeurs numériques pures (ex: 150000.0).",
        "Format des dates : YYYY-MM-DD."
    ]
    
    if "BGFI" in bank_clean:
        instructions.append(
            "SPÉCIFICITÉ BGFI : La Date de Valeur DOIT impérativement être utilisée "
            "comme Date des Opérations ('date'). Si la Date de Valeur est disponible, elle remplace la date de saisie."
        )
    else:
        instructions.append(
            "REMARQUE : Si le document provient de la banque BGFI, utiliser obligatoirement la Date de Valeur comme date d'opération ('date')."
        )
        
    return "\n".join(f"- {i}" for i in instructions)
