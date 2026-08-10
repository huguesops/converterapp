"""
Base de données des comptes bancaires basée sur le Classeur2 (Annuaire des Comptes 2026).
Permet l'identification automatique du titulaire, de la banque et du numéro de compte.
"""

from typing import Dict, Any, List, Optional

# Annuaire structuré des comptes répertoriés
ACCOUNTS_DIRECTORY: List[Dict[str, str]] = [
    # CCA BANK
    {"bank": "CCA BANK", "category": "Banque Classique", "holder": "SKAB DISTRIBUTION SARL", "account_number": "10039 10001 00265894401-23"},
    {"bank": "CCA BANK", "category": "Banque Classique", "holder": "KENMEGNE KEMTCHOUANG Alain B.", "account_number": "10039 10001 00750548501-17"},
    {"bank": "CCA BANK", "category": "Banque Classique", "holder": "SKAB NUTRITION ANIMALE SARL", "account_number": "10039 10001 00257907701-56"},
    {"bank": "CCA BANK", "category": "Banque Classique", "holder": "KOUAM KEMTCHOUANG ANNABELLE BLESSING", "account_number": "10039 10001 00772613701-30"},
    {"bank": "CCA BANK", "category": "Banque Classique", "holder": "KENGNE SUZANNE", "account_number": "10039 10001 00175828501-52"},
    {"bank": "CCA BANK", "category": "Banque Classique", "holder": "STE CAMEROUNAISE D'IMPORTATION", "account_number": "10039 10001 00264917501-62"},
    
    # AFRILAND FIRST BANK
    {"bank": "AFRILAND FIRST BANK", "category": "Banque Classique", "holder": "SKAB DISTRIBUTION SARL", "account_number": "10005 00003 07599951001-71"},
    {"bank": "AFRILAND FIRST BANK", "category": "Banque Classique", "holder": "SKAB NUTRITION ANIMALE SARL", "account_number": "10005 00003 05920691001-02"},
    {"bank": "AFRILAND FIRST BANK", "category": "Banque Classique", "holder": "MAGNE", "account_number": "10005 00003 10069461101-68"},
    {"bank": "AFRILAND FIRST BANK", "category": "Banque Classique", "holder": "DJOKO KEMTCHOUANG Arone Balderic", "account_number": "00080-08882511101-59"},
    {"bank": "AFRILAND FIRST BANK", "category": "Banque Classique", "holder": "POUOKAM DJOKO Arlette Jasmine", "account_number": "00080-09021341101-26"},
    {"bank": "AFRILAND FIRST BANK", "category": "Banque Classique", "holder": "KENGNE SUZANNE", "account_number": "10005 00080 10013871051-67"},
    
    # AFB/MC2
    {"bank": "AFB/MC2", "category": "Microfinance", "holder": "KENGNE SUZANNE", "account_number": "371100005043"},
    {"bank": "AFB/MC2", "category": "Microfinance", "holder": "MAGNE", "account_number": "371100005042"},
    
    # BGFI
    {"bank": "BGFI", "category": "Banque Classique", "holder": "MAGNE", "account_number": "10031163051-37"},
    {"bank": "BGFI", "category": "Banque Classique", "holder": "MAGNE", "account_number": "01300 10031163051 37"},
    {"bank": "BGFI", "category": "Banque Classique", "holder": "KENGNE SUZANNE", "account_number": "10037773011-61"},
    {"bank": "BGFI", "category": "Banque Classique", "holder": "KENGNE SUZANNE", "account_number": "01300 10037773011-61"},
    {"bank": "BGFI", "category": "Banque Classique", "holder": "SKAB DISTRIBUTION SARL", "account_number": "40032855011-17"},
    
    # UBA
    {"bank": "UBA", "category": "Banque Classique", "holder": "SKAB DISTRIBUTION SARL", "account_number": "10033 05203 03011000214-86"},
    {"bank": "UBA", "category": "Banque Classique", "holder": "SIKA KEMTCHOUANG Antoine Brayan", "account_number": "3056000074"},
    {"bank": "UBA", "category": "Banque Classique", "holder": "SKAB ELEVAGE SNC", "account_number": "10033 05203 03011000194-52"},
    {"bank": "UBA", "category": "Banque Classique", "holder": "MAGNE", "account_number": "10033 05203 03056000423-85"},
    {"bank": "UBA", "category": "Banque Classique", "holder": "MEDOM KEMTCHOUANG", "account_number": "10033 05203 03056000398-63"},
    {"bank": "UBA", "category": "Banque Classique", "holder": "MIQUEL SARL", "account_number": "03011000336"},
    {"bank": "UBA", "category": "Banque Classique", "holder": "NUTRI BUSINESS CORPORATION", "account_number": "03011000245"},
    
    # UNION BANK OF CAMEROON PLC (UBC)
    {"bank": "UNION BANK OF CAMEROON PLC", "category": "Banque Classique", "holder": "SKAB ELEVAGE SNC", "account_number": "10023 00070 37500100456-48"},
    
    # AFG ATLANTIQUE BANQUE
    {"bank": "AFG ATLANTIQUE BANQUE", "category": "Banque Classique", "holder": "POUOKAM DJOKO Arlette Jasmine", "account_number": "96045950003"},
    {"bank": "AFG ATLANTIQUE BANQUE", "category": "Banque Classique", "holder": "KENMEGNE KEMTCHOUANG Alain B.", "account_number": "10034 0006037360152201-48"},
    
    # CBC BANK
    {"bank": "CBC BANK", "category": "Banque Classique", "holder": "KENMEGNE KEMTCHOUANG Alain B.", "account_number": "37240214105-09"},
    {"bank": "CBC BANK", "category": "Banque Classique", "holder": "SIKA KEMTCHOUANG Antoine Brayan", "account_number": "37340486101-33"},
    {"bank": "CBC BANK", "category": "Banque Classique", "holder": "CBC SKAB NUTRITION SARL", "account_number": "37140594001-23"},
    {"bank": "CBC BANK", "category": "Banque Classique", "holder": "CBC SKAB NUTRITION SARL", "account_number": "37140594001-20"},
    {"bank": "CBC BANK", "category": "Banque Classique", "holder": "SKAB DISTRIBUTION SARL", "account_number": "37140871901-38"},
    {"bank": "CBC BANK", "category": "Banque Classique", "holder": "SKAB ELEVAGE SNC", "account_number": "37140871801-47"},
    
    # ECOBANK
    {"bank": "ECOBANK", "category": "Banque Classique", "holder": "KENMEGNE KEMTCHOUANG Alain B.", "account_number": "31350001338"},
    {"bank": "ECOBANK", "category": "Banque Classique", "holder": "SKAB ELEVAGE SNC", "account_number": "10029 26019 31350016634-25"},
    
    # AFRICA GOLDEN BANK
    {"bank": "AFRICA GOLDEN BANK", "category": "Banque Classique", "holder": "DJOKO KEMTCHOUANG Arone Balderic", "account_number": "10043 0030137300466801-17"},
    {"bank": "AFRICA GOLDEN BANK", "category": "Banque Classique", "holder": "SKAB NUTRITION ANIMALE SARL", "account_number": "10044 0030137100663001-14"},
    
    # MUPECI
    {"bank": "MUPECI", "category": "Microfinance", "holder": "MEDOM KEMTCHOUANG ANGE BRIHANNA", "account_number": "000054300257820192"},
    {"bank": "MUPECI", "category": "Microfinance", "holder": "NZEUYO DJOKO BORIS YVES", "account_number": "000284230842540167"},
    {"bank": "MUPECI", "category": "Microfinance", "holder": "DJUIDJE SIKA NATHANAELLE", "account_number": "000284230842490115"},
    {"bank": "MUPECI", "category": "Microfinance", "holder": "NOUBISSI SIKA FRANCK THEOPHILE", "account_number": "000284230842520185"},
    {"bank": "MUPECI", "category": "Microfinance", "holder": "MBOPDA KENGNE EMMANUEL ELISE", "account_number": "000284230842480124"},
    {"bank": "MUPECI", "category": "Microfinance", "holder": "KOUOBOU MADELEINE CHANTAL", "account_number": "000284230842510194"},
    
    # RURAL INVESTMENT CREDIT
    {"bank": "RURAL INVESTMENT CREDIT", "category": "Microfinance", "holder": "SKAB DISTRIBUTION", "account_number": "10035 01300 70004821051-31"},
    
    # FIGEC
    {"bank": "FIGEC", "category": "Microfinance", "holder": "POUOKAM DJOKO Arlette Jasmine", "account_number": "37223003619"},
    {"bank": "FIGEC", "category": "Microfinance", "holder": "KENMEGNE KEMTCHOUANG Alain B.", "account_number": "37223003590"},
    {"bank": "FIGEC", "category": "Microfinance", "holder": "CHEMFE", "account_number": "37223003629"},
    
    # ADVANS
    {"bank": "ADVANS", "category": "Microfinance", "holder": "POUOKAM DJOKO Arlette Jasmine", "account_number": "00500078177-00"},
    {"bank": "ADVANS", "category": "Microfinance", "holder": "KENMEGNE KEMTCHOUANG Alain B.", "account_number": "00200076145-00"},
    {"bank": "ADVANS", "category": "Microfinance", "holder": "KENGNE SUZANNE", "account_number": "00200112427-43"},
    {"bank": "ADVANS", "category": "Microfinance", "holder": "MAGNE", "account_number": "00200112428-01"},
    
    # CEPAC
    {"bank": "CEPAC", "category": "Microfinance", "holder": "POUOKAM DJOKO Arlette Jasmine", "account_number": "372101002372012138I"},
    {"bank": "CEPAC", "category": "Microfinance", "holder": "KENMEGNE KEMTCHOUANG Alain B.", "account_number": "372101002372010612I"},
    {"bank": "CEPAC", "category": "Microfinance", "holder": "KOUAM KEMTCHOUANG ANABELLE", "account_number": "0237011910I"},
    
    # CCEFI
    {"bank": "CCEFI", "category": "Microfinance", "holder": "CHEBOU DEKAM RACHEL BENEDICTE", "account_number": "372500203084-55"},
    
    # FINANCIAL HOUSE
    {"bank": "FINANCIAL HOUSE", "category": "Microfinance", "holder": "KENMEGNE KEMTCHOUANG Alain B.", "account_number": "303035883721001"},
    {"bank": "FINANCIAL HOUSE", "category": "Microfinance", "holder": "DJOKO KEMTCHOUANG Arone Balderic", "account_number": "303041073731001"},
    {"bank": "FINANCIAL HOUSE", "category": "Microfinance", "holder": "CHEBOU DEKAM RACHEL BENEDICTE", "account_number": "303047883722101"},
    {"bank": "FINANCIAL HOUSE", "category": "Microfinance", "holder": "KENGNE SUZANNE", "account_number": "0303052753722101"},
    {"bank": "FINANCIAL HOUSE", "category": "Microfinance", "holder": "MAGNE", "account_number": "0303052743722101"},
    
    # UNICS
    {"bank": "UNICS", "category": "Microfinance", "holder": "POUOKAM DJOKO Arlette Jasmine", "account_number": "37141400366026"},
    {"bank": "UNICS", "category": "Microfinance", "holder": "POUOKAM DJOKO Arlette Jasmine", "account_number": "37321400366056"}
]

def clean_acc_str(acc: str) -> str:
    """Nettoie un numéro de compte pour comparaison flexible."""
    if not acc:
        return ""
    return "".join(c for c in str(acc) if c.isalnum()).lower()

def match_account_details(account_number_extracted: str, bank_hint: str = "") -> Optional[Dict[str, str]]:
    """
    Recherche un compte dans l'annuaire basé sur le numéro extrait et optionnellement la banque.
    """
    clean_ext = clean_acc_str(account_number_extracted)
    if not clean_ext:
        return None
        
    # Recherche exacte ou sous-chaîne dans l'annuaire
    for entry in ACCOUNTS_DIRECTORY:
        clean_db = clean_acc_str(entry["account_number"])
        if clean_ext == clean_db or clean_ext in clean_db or clean_db in clean_ext:
            if not bank_hint or entry["bank"].lower() in bank_hint.lower() or bank_hint.lower() in entry["bank"].lower():
                return entry
                
    # Deuxième passe : si la banque n'a pas matché strictement, retourner le premier match de numéro
    for entry in ACCOUNTS_DIRECTORY:
        clean_db = clean_acc_str(entry["account_number"])
        if clean_ext in clean_db or clean_db in clean_ext:
            return entry
            
    return None

