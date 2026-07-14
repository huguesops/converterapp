"""
bank_configs.py - Version 5.0
Configurations spécifiques par banque camerounaise
Structure détaillée pour guider l'IA avec précision
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class BankConfig:
    nom: str
    code: str
    emoji: str

    # Noms de colonnes possibles dans le relevé
    col_date: List[str] = field(default_factory=lambda: ["Date", "Date Opération"])
    col_ref: List[str] = field(default_factory=lambda: ["Référence", "Ref", "Cheq#", "N° Pièce", "Batch/Ref"])
    col_libelle: List[str] = field(default_factory=lambda: ["Libellé", "Désignation", "Particulars", "Libellé de l'opération"])
    col_date_valeur: List[str] = field(default_factory=lambda: ["Date Valeur", "Valeur", "ValueDate"])
    col_debit: List[str] = field(default_factory=lambda: ["Débit", "Debit", "Debits"])
    col_credit: List[str] = field(default_factory=lambda: ["Crédit", "Credit", "Credits"])
    col_solde: List[str] = field(default_factory=lambda: ["Solde", "Balance"])

    # Patterns pour détecter les lignes spéciales
    solde_ouverture_patterns: List[str] = field(default_factory=lambda: [
        r"ouverture", r"opening balance", r"report solde", r"solde antérieur", r"solde debut"
    ])
    solde_cloture_patterns: List[str] = field(default_factory=lambda: [
        r"cl[ôo]ture", r"cloture", r"solde final", r"solde crediteur", r"total mouvements"
    ])

    # Description détaillée de la structure du relevé pour l'IA
    structure_description: str = "Relevé bancaire standard avec colonnes Date, Référence, Libellé, Date Valeur, Débit, Crédit, Solde."

    # Instructions spécifiques pour l'IA
    specific_instructions: str = ""

    # Indication du format de date
    date_format_hint: str = "JJ/MM/AAAA"

    # Motifs de lignes de continuation (libellé multi-lignes)
    continuation_patterns: List[str] = field(default_factory=lambda: [
        r"^\s+",  # Ligne commençant par des espaces (continuation)
    ])

    # Mots-clés pour identifier les lignes non-transaction
    skip_patterns: List[str] = field(default_factory=lambda: [
        r"historique compte", r"relev[ée]", r"page\s+\d+", r"imprim[ée]",
        r"titulaire", r"compte n", r"iban", r"période du", r"solde précédent",
        r"total des", r"nombre d['']", r"taux", r"agence", r"guichet",
        r"relevé du", r"du\s+\d{2}", r"au\s+\d{2}", r"devise",
    ])


BANK_CONFIGS: Dict[str, BankConfig] = {
    # =================================================================
    # FINANCIAL HOUSE S.A
    # =================================================================
    "Financial House S.A": BankConfig(
        nom="Financial House S.A",
        code="FH",
        emoji="🏛️",
        col_ref=["Batch/Ref", "Référence"],
        col_libelle=["Libellé", "Description"],
        structure_description="""Le relevé Financial House a cette structure EXACTE :
- En-tête : logo FH, "FINANCIAL HOUSE S.A", infos compte (titulaire, N° compte, période)
- Tableau avec colonnes : Date | Batch/Ref | Libellé | Valeur | Débit | Crédit | Solde
- Le libellé peut être sur 1 à 3 lignes (continuation sans date)
- Les montants sont en FCFA avec séparateur d'espace pour les milliers (ex: "1 234 567")
- Le solde d'ouverture est marqué "Solde d'ouverture" ou "Report N+1"
- Le solde de clôture est marqué "Solde de clôture"
- Les frais bancaires apparaissent sans référence""",
        specific_instructions="""Financial House S.A :
1. La colonne Batch/Ref contient une référence batch (ex: "B123456/1")
2. Les libellés multi-lignes DOIVENT être fusionnés en une seule ligne
3. Les montants contiennent des espaces comme séparateurs de milliers → les supprimer
4. La ligne "Solde d'ouverture" doit être incluse avec son montant
5. La ligne "Solde de clôture" doit être incluse avec son montant
6. Les opérations de frais sont souvent sans référence mais ont une date""",
    ),

    # =================================================================
    # BGFI BANK
    # =================================================================
    "BGFI Bank": BankConfig(
        nom="BGFI Bank",
        code="BGFI",
        emoji="🔷",
        col_ref=["N° Pièce", "Référence", "Pièce N°"],
        col_libelle=["Libellé", "Libellé opération"],
        structure_description="""Relevé BGFI Bank Cameroun - Structure typique :
- En-tête : logo BGFI, "BGFI BANK CAMEROUN", infos compte
- Tableau : Date | N° Pièce | Libellé | Date Valeur | Débit | Crédit | Solde
- La colonne N° Pièce est un numéro de pièce comptable (ex: "123456")
- Les frais bancaires sont toujours marqués en Débit
- Les intérêts créditeurs apparaissent en Crédit
- Format montant : séparateur milliers espace, virgule décimale""",
        specific_instructions="""BGFI Bank :
1. La colonne 'N° Pièce' est la référence à extraire
2. Les frais (tenue de compte, commission, etc.) sont TOUJOURS en Débit
3. Les chèques émis ont le numéro du chèque dans le libellé
4. Les remises de chèques ont un libellé commençant par "REMISE"
5. Ne pas confondre la colonne Date Valeur avec la Date d'opération""",
    ),

    # =================================================================
    # UNICS
    # =================================================================
    "UNICS": BankConfig(
        nom="UNICS",
        code="UNICS",
        emoji="🏦",
        col_ref=["Cheq#", "Référence"],
        col_libelle=["Particulars", "Particularités"],
        structure_description="""Relevé UNICS Cameroun - Structure spécifique :
- En-tête bleu "UNICS", infos compte
- Tableau avec colonnes : Date | Cheq# | Particulars | Débit | Crédit | Solde
- La colonne 'Particulars' contient la description de l'opération (peut être très long)
- Les retraits chèques commencent par "WDL chq no."
- Les crédits cash commencent par "CASH CREDIT BY"
- Les virements entrants par "TRF CREDIT BY" ou "CASH CREDIT BY"
- Les chèques impayés par "CHQ UNPAID"
- Pas de colonne Date Valeur séparée""",
        specific_instructions="""UNICS - TRÈS IMPORTANT :
1. La colonne 'Particulars' EST le libellé à extraire
2. Les lignes "WDL chq no." (Withdrawal cheque) contiennent le NOM du bénéficiaire - NE PAS COUPER
3. Les lignes "CASH CREDIT BY" contiennent le déposant - GARDER L'INTÉGRALITÉ
4. Les montants sont en FCFA SANS virgule (ex: 308000 pour 308 000)
5. Les chèques peuvent avoir des descriptions sur 2-3 lignes mais avec la même date
6. Extraire TOUTES les lignes même si les libellés sont longs et complexes
7. Les lignes commençant par un espace sont des continuations""",
    ),

    # =================================================================
    # CEPAC
    # =================================================================
    "CEPAC": BankConfig(
        nom="CEPAC",
        code="CEPAC",
        emoji="🏦",
        col_ref=["Référence", "VE N°", "CHQ N°", "N° Chèque"],
        col_libelle=["Désignation", "Libellé"],
        col_date_valeur=["Date Valeur", "Valeur"],
        structure_description="""Relevé CEPAC Cameroun - Structure :
- En-tête : "CEPAC", infos compte client
- Tableau : Date | Référence (VE N° ou CHQ N°) | Désignation | Date Valeur | Débit | Crédit | Solde
- 'Désignation' est le libellé principal de l'opération
- VE N° = Virement Entrant, CHQ N° = Chèque
- Le solde de clôture est souvent marqué 'SOLDE CRÉDITEUR' ou 'SOLDE DÉBITEUR'
- Les échéances de prêt apparaissent mensuellement""",
        specific_instructions="""CEPAC :
1. 'VE N°' est le numéro de virement entrant (le capturer comme référence)
2. 'CHQ N°' est le numéro de chèque (le capturer comme référence)
3. La colonne 'Désignation' contient le libellé complet
4. 'SOLDE CRÉDITEUR' ou 'SOLDE DÉBITEUR' marque la fin du relevé
5. Les montants des échéances de crédit sont en Débit
6. Les versements sur compte épargne sont en Crédit""",
    ),

    # =================================================================
    # ADVANS
    # =================================================================
    "ADVANS": BankConfig(
        nom="ADVANS",
        code="ADVANS",
        emoji="🏦",
        col_libelle=["Libellé de l'opération", "Libellé"],
        structure_description="""Relevé ADVANS Cameroun - Structure :
- En-tête : "ADVANS CAMEROUN", infos compte et période
- Tableau : Date | Libellé de l'opération | Débit | Crédit | Solde
- Le libellé est très détaillé avec descriptions complètes
- Beaucoup de retraits chèques avec bénéficiaires
- Les remboursements de prêts sont clairement identifiés
- Les frais de dossier et d'assurance apparaissent séparément""",
        specific_instructions="""ADVANS :
1. Les libellés sont TRÈS longs et détaillés - les fusionner complètement
2. Les retraits chèques incluent le numéro et le bénéficiaire
3. "REMBOURSEMENT PRET" ou "ECHEANCE PRET" en Débit
4. "VERSEMENT" ou "DEPOT" en Crédit
5. Les frais de tenue de compte sont en Débit
6. Ne PAS tronquer les libellés même s'ils semblent redondants""",
    ),

    # =================================================================
    # MUPECI
    # =================================================================
    "MUPECI": BankConfig(
        nom="MUPECI",
        code="MUPECI",
        emoji="🏦",
        col_libelle=["Libelle et Référence", "Opération", "Libellé opération"],
        structure_description="""Relevé MUPECI (Mutuelle Paysanne) - Structure :
- En-tête : "MUPECI", infos compte
- Tableau : Date | Libelle et Référence | Débit | Crédit | Solde
- La colonne 'Libelle et Référence' combine la description et la référence ensemble
- Contient des mentions comme 'Remettant :', 'VERST.', 'VAD', 'RETRAIT'
- Les opérations VAD = Virement Automatique à Distance
- Les VERST. = Versements
- Les RETRAIT = Retraits d'espèces""",
        specific_instructions="""MUPECI :
1. La colonne 'Libelle et Référence' contient TOUT (description + référence)
2. Nettoyer les mentions 'Remettant :' mais GARDER le nom du remettant
3. 'VERST.' signifie Versement (Crédit généralement)
4. 'VAD' = Virement (peut être Débit ou Crédit)
5. 'RETRAIT' = Retrait espèces (Débit)
6. Les numéros de chèques sont souvent dans le libellé
7. Fusionner les lignes de continuation si le libellé est incomplet""",
    ),

    # =================================================================
    # SCB CAMEROUN
    # =================================================================
    "SCB Cameroun": BankConfig(
        nom="SCB Cameroun",
        code="SCB",
        emoji="🏦",
        col_ref=["Référence", "Ref"],
        col_libelle=["Libellé", "Opération"],
        structure_description="""Relevé SCB Cameroun (Société Commerciale de Banque) - Structure :
- En-tête : "SCB CAMEROUN", infos compte
- Tableau : Date | Référence | Libellé | Date Valeur | Débit | Crédit | Solde
- Structure généralement propre et bien formatée
- Les libellés sont concis
- Les chèques sont référencés par leur numéro
- Format montant standard FCFA""",
        specific_instructions="""SCB Cameroun :
1. Structure standard - extraire toutes les lignes sans exception
2. Les numéros de chèque sont dans la colonne Référence
3. Les commissions et frais ont un libellé explicite
4. Le solde de clôture est marqué 'SOLDE CREDITEUR'
5. Les remises chèques ont 'REMISE' dans le libellé""",
    ),

    # =================================================================
    # BICEC
    # =================================================================
    "BICEC": BankConfig(
        nom="BICEC",
        code="BICEC",
        emoji="🏦",
        col_ref=["Référence", "N° Pièce"],
        col_libelle=["Libellé", "Désignation"],
        structure_description="""Relevé BICEC (Banque Internationale du Cameroun pour l'Épargne et le Crédit) - Structure :
- En-tête : "BICEC", infos compte
- Tableau : Date | Référence | Libellé | Date Valeur | Débit | Crédit | Solde
- Format de date standard JJ/MM/AAAA
- Montants en FCFA avec virgule décimale (ex: 1500,50)
- Les agios et frais sont identifiés dans le libellé""",
        specific_instructions="""BICEC :
1. Structure standard bien formatée
2. Les agios et intérêts débiteurs sont en Débit
3. Les virements entrants ont 'VIR' dans le libellé
4. Les chèques ont 'CHQ' ou 'CHEQUE' dans le libellé
5. Le solde de clôture est indiqué en fin de relevé
6. Bien distinguer Date d'opération et Date Valeur""",
    ),

    # =================================================================
    # UBA CAMEROUN
    # =================================================================
    "UBA Cameroun": BankConfig(
        nom="UBA Cameroun",
        code="UBA",
        emoji="🌐",
        col_ref=["Référence", "Tran Ref", "Ref"],
        col_libelle=["Particulars", "Narration", "Libellé"],
        structure_description="""Relevé UBA Cameroun (United Bank for Africa) - Structure :
- En-tête : "UBA CAMEROUN", infos compte
- Tableau : Date | Référence | Particulars (ou Narration) | Débit | Crédit | Solde
- La colonne 'Particulars' ou 'Narration' contient la description
- Les transactions internationales ont des libellés plus longs
- Les frais SMS et commissions apparaissent mensuellement
- Format montant FCFA classique""",
        specific_instructions="""UBA Cameroun :
1. 'Particulars' ou 'Narration' = la colonne libellé
2. Les transactions internationales contiennent des références SWIFT
3. Les commissions sur opérations sont en Débit
4. Les alertes SMS sont facturées mensuellement
5. Les dépôts cash ont 'CASH DEPOSIT' ou 'DEPOT ESPECES' dans le libellé
6. Extraire TOUTES les ligny de continuation""",
    ),

    # =================================================================
    # AUTRE BANQUE (Fallback)
    # =================================================================
    "Autre banque": BankConfig(
        nom="Autre banque",
        code="AUTRE",
        emoji="🏦",
        structure_description="""Relevé bancaire camerounais standard :
- Tableau avec dates, références, descriptions, montants
- Colonnes typiques : Date, Référence, Libellé, Date Valeur, Débit, Crédit, Solde
- Montants en FCFA avec séparateur virgule ou espace
- Les libellés peuvent être sur plusieurs lignes (sans date sur la ligne suivante)
- Solde d'ouverture et solde de clôture en début/fin de relevé""",
        specific_instructions="""Utilise la structure standard des relevés camerounais :
1. Identifie les colonnes Date, Référence, Libellé, Débit, Crédit, Solde
2. Fusionne les libellés multi-lignes en une seule ligne
3. Supprime les espaces dans les montants (séparateurs de milliers)
4. Remplace la virgule décimale par un point
5. Inclus le solde d'ouverture et de clôture si présents
6. Sois exhaustif - ne saute AUCUNE ligne contenant un montant""",
    ),
}


def get_bank_config(nom_banque: str) -> BankConfig:
    """Retourne la configuration de la banque ou la config par défaut."""
    for key, cfg in BANK_CONFIGS.items():
        if nom_banque.lower() in key.lower() or cfg.nom.lower() in nom_banque.lower():
            return cfg
    return BANK_CONFIGS["Autre banque"]


def get_bank_list() -> List[str]:
    """Retourne la liste des noms de banques supportées."""
    return [cfg.nom for cfg in BANK_CONFIGS.values()]


def get_bank_emoji(nom_banque: str) -> str:
    """Retourne l'emoji pour une banque donnée."""
    cfg = get_bank_config(nom_banque)
    for key, bc in BANK_CONFIGS.items():
        if bc.code == cfg.code:
            return bc.emoji
    return "🏦"