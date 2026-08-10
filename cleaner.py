"""
cleaner.py - Version 4.6
Ultra-conservatrice : on ne supprime presque rien
"""

import pandas as pd
import numpy as np
import re
from typing import Optional

from bank_configs import get_bank_config

class DataCleaner:
    def clean(self, df: pd.DataFrame, banque_nom: str = "Autre banque") -> pd.DataFrame:
        if df.empty:
            return df

        df = df.copy()

        df = self._clean_dates(df)
        df = self._apply_date_valeur_rule(df, banque_nom)  # ex: BGFI
        df = self._clean_amounts(df)
        df = self._merge_libelles_minimal(df)          # Fusion minimale
        df = self._clean_libelle(df)
        df = self._remove_duplicates_minimal(df)       # Presque aucune suppression
        df = self._sort_by_date(df)
        df = self._post_process_by_bank(df, banque_nom)

        return df.reset_index(drop=True)

    def _clean_dates(self, df: pd.DataFrame) -> pd.DataFrame:
        for col in ['Date', 'Date_Valeur']:
            if col in df.columns:
                df[col] = df[col].apply(self._normalize_date)
        return df

    def _normalize_date(self, val) -> str:
        if not val or pd.isna(val):
            return ''
        s = str(val).strip()
        if re.match(r'\d{2}/\d{2}/\d{4}', s):
            return s[:10]
        return s

    def _apply_date_valeur_rule(self, df: pd.DataFrame, banque_nom: str) -> pd.DataFrame:
        """Pour les banques dont la config a `date_valeur_is_date=True`
        (spécificité BGFI), la 'Date Valeur' du relevé doit être utilisée
        comme date d'opération dans tout l'export (colonne 'Date'), à la
        place de la date d'opération habituelle.

        On ne substitue que lorsque la Date Valeur est effectivement
        renseignée sur la ligne, pour ne jamais effacer une date connue
        (ex : lignes de solde d'ouverture/clôture qui n'ont parfois pas
        de date de valeur).
        """
        config = get_bank_config(banque_nom)
        if not config.date_valeur_is_date:
            return df
        if 'Date_Valeur' not in df.columns or 'Date' not in df.columns:
            return df

        df = df.copy()
        date_valeur = df['Date_Valeur'].astype(str).str.strip()
        has_date_valeur = date_valeur.ne('') & date_valeur.str.lower().ne('none') & date_valeur.str.lower().ne('nan')
        df.loc[has_date_valeur, 'Date'] = df.loc[has_date_valeur, 'Date_Valeur']
        return df

    def _clean_amounts(self, df: pd.DataFrame) -> pd.DataFrame:
        for col in ['Débit', 'Crédit', 'Solde']:
            if col in df.columns:
                df[col] = df[col].apply(self._parse_amount)
        return df

    def _parse_amount(self, val) -> Optional[float]:
        if val is None or pd.isna(val):
            return None
        s = str(val).strip()
        if s.lower() in ('null', 'none', ''):
            return None
        # Ne pas convertir "0" en None (le solde peut être 0)
        try:
            s = re.sub(r'[^\d.,-]', '', s)
            s = s.replace(',', '.')
            if s.count('.') > 1:
                s = s.replace('.', '')
            f = float(s) if s else None
            return f  # Retourner 0.0 si le montant est 0 (ne pas transformer en None)
        except:
            return None

    # Fusion très minimale
    def _merge_libelles_minimal(self, df: pd.DataFrame) -> pd.DataFrame:
        if 'Libellé' not in df.columns or df.empty:
            return df

        df = df.reset_index(drop=True)
        result = []
        i = 0
        while i < len(df):
            row = df.iloc[i].copy()
            libelle = str(row.get('Libellé', '')).strip()

            # On fusionne seulement si la ligne suivante est vide de date et montant
            if i + 1 < len(df):
                next_row = df.iloc[i + 1]
                next_lib = str(next_row.get('Libellé', '')).strip()
                has_date = bool(str(next_row.get('Date', '')).strip())
                has_amount = pd.notna(next_row.get('Débit')) or pd.notna(next_row.get('Crédit'))

                if not has_date and not has_amount and next_lib:
                    libelle = f"{libelle} {next_lib}".strip()
                    i += 1   # saute la ligne de continuation

            row['Libellé'] = libelle
            result.append(row)
            i += 1

        return pd.DataFrame(result)

    def _clean_libelle(self, df: pd.DataFrame) -> pd.DataFrame:
        if 'Libellé' in df.columns:
            df['Libellé'] = df['Libellé'].astype(str).str.replace(r'\s+', ' ', regex=True).str.strip()
        return df

    def _remove_duplicates_minimal(self, df: pd.DataFrame) -> pd.DataFrame:
        """Supprime uniquement les lignes complètement identiques"""
        if df.empty:
            return df
        return df.drop_duplicates(keep='first')

    def _sort_by_date(self, df: pd.DataFrame) -> pd.DataFrame:
        if 'Date' not in df.columns:
            return df
        try:
            df['_date_sort'] = pd.to_datetime(df['Date'], format='%d/%m/%Y', errors='coerce')
            df = df.sort_values('_date_sort', na_position='first')
            df = df.drop(columns=['_date_sort'])
        except:
            pass
        return df.reset_index(drop=True)

    def _post_process_by_bank(self, df: pd.DataFrame, banque_nom: str) -> pd.DataFrame:
        """Post-traitement spécifique selon la banque."""
        # Normalisation des noms de colonnes
        column_mapping = {
            'Particulars': 'Libellé',
            'Particularités': 'Libellé',
            'Particulars': 'Libellé',
            'Désignation': 'Libellé',
            'Libellé de l\'opération': 'Libellé',
            'Libelle et Référence': 'Libellé',
            'Narration': 'Libellé',
            'Batch/Ref': 'Référence',
            'Cheq#': 'Référence',
            'N° Pièce': 'Référence',
            'VE N°': 'Référence',
            'CHQ N°': 'Référence',
            'Pièce N°': 'Référence',
            'Tran Ref': 'Référence',
        }
        
        # Appliquer le renommage des colonnes si nécessaire
        for col in df.columns:
            if col in column_mapping and column_mapping[col] not in df.columns:
                df = df.rename(columns={col: column_mapping[col]})

        # Post-traitement spécifique par banque
        banque_lower = banque_nom.lower()
        
        if "unics" in banque_lower:
            # UNICS : nettoyer les libellés de chèques
            if 'Libellé' in df.columns:
                df['Libellé'] = df['Libellé'].apply(
                    lambda x: re.sub(r'\s+', ' ', str(x)).strip() if pd.notna(x) else x
                )
                
        elif "financial house" in banque_lower:
            # Financial House : s'assurer que Batch/Ref est bien dans Référence
            pass
            
        elif "bgfi" in banque_lower:
            # BGFI : la substitution Date <- Date Valeur est déjà faite
            # plus tôt dans clean() par _apply_date_valeur_rule().
            pass
            
        elif "mupeci" in banque_lower:
            # MUPECI : nettoyer les mentions "Remettant :"
            if 'Libellé' in df.columns:
                df['Libellé'] = df['Libellé'].apply(
                    lambda x: re.sub(r'Remettant\s*:\s*', '', str(x)).strip() if pd.notna(x) else x
                )

        return df

    def check_consistency(self, df: pd.DataFrame, tolerance: float = 1.0) -> pd.DataFrame:
        """Ajoute une colonne 'Écart' : différence entre le solde extrait de
        chaque ligne et le solde attendu (solde de la ligne précédente +
        crédit - débit de la ligne courante).

        Un écart proche de 0 = ligne cohérente. Un écart important signale
        une anomalie locale : montant tronqué/mal lu, ligne manquante juste
        avant, ou ligne dans le mauvais ordre — c'est le point d'entrée pour
        détecter les erreurs d'extraction sans devoir tout recomparer au PDF
        à la main.

        NB : ce contrôle est local (il repart du solde extrait de la ligne
        précédente, pas d'un solde recalculé en cascade) pour qu'une seule
        ligne fausse ne fasse pas apparaître TOUT ce qui suit comme faux.
        Une rupture de période (ouverture d'un nouveau mois) est normale et
        n'est pas comptée comme anomalie.
        """
        if df.empty or 'Solde' not in df.columns:
            df['Écart'] = None
            return df

        df = df.reset_index(drop=True)
        lib_lower = df.get('Libellé', pd.Series('', index=df.index)).astype(str).str.lower()
        is_opening = lib_lower.str.contains('ouverture|opening', na=False)

        ecarts = [None] * len(df)
        for i in range(1, len(df)):
            if is_opening.iloc[i]:
                continue  # nouvelle période : pas de continuité avec la ligne précédente
            prev_solde = df.at[i - 1, 'Solde']
            credit = df.at[i, 'Crédit']
            debit = df.at[i, 'Débit']
            credit = 0 if pd.isna(credit) else credit
            debit = 0 if pd.isna(debit) else debit
            solde = df.at[i, 'Solde']
            if pd.isna(prev_solde) or pd.isna(solde):
                continue
            attendu = prev_solde + credit - debit
            ecarts[i] = round(solde - attendu, 2)

        df['Écart'] = ecarts
        return df

    def get_statistics(self, df: pd.DataFrame, banque_nom: str = "Autre banque") -> dict:
        """Calcule les indicateurs du relevé, dont le solde d'ouverture et le
        solde de clôture EXACTS tels qu'affichés sur le relevé (extraits
        directement de la ligne "Ouverture"/"Clôture" du document, jamais
        recalculés), afin de permettre un contrôle rapide de la cohérence
        des données extraites (voir 'solde_cloture_calcule' / 'ecart_cloture'
        / 'coherent' ci-dessous).
        """
        stats = {
            'total_transactions': 0,
            'total_credit': 0.0,
            'total_debit': 0.0,
            'net': 0.0,
            'solde_ouverture': None,
            'solde_cloture': None,
            'solde_cloture_calcule': None,
            'ecart_cloture': None,
            'coherent': None,
            'periode_debut': '',
            'periode_fin': '',
        }

        if df.empty:
            return stats

        # Motifs de détection des lignes de solde d'ouverture/clôture :
        # on combine les motifs génériques historiques avec ceux, propres
        # à chaque banque, déjà définis dans bank_configs.py (jusqu'ici
        # non exploités ici), pour repérer fiablement la ligne quelle que
        # soit la formulation utilisée par le relevé ("Solde d'ouverture",
        # "Report solde antérieur", "Solde debut", "Solde final", etc.).
        config = get_bank_config(banque_nom)
        ouv_patterns = set(config.solde_ouverture_patterns) | {
            'ouverture', 'opening', 'report solde antérieur'
        }
        clo_patterns = set(config.solde_cloture_patterns) | {
            'cl[ôo]ture', 'cloture', 'solde final', 'solde crediteur', 'total mouvements'
        }
        regex_ouv = '|'.join(ouv_patterns)
        regex_clo = '|'.join(clo_patterns)

        lib_lower = df.get('Libellé', pd.Series('')).astype(str).str.lower()
        mask_ouv = lib_lower.str.contains(regex_ouv, na=False, regex=True)
        mask_clo = lib_lower.str.contains(regex_clo, na=False, regex=True)

        normal_df = df[~(mask_ouv | mask_clo)]

        stats['total_transactions'] = len(normal_df)
        stats['total_credit'] = float(normal_df.get('Crédit', pd.Series(0)).sum(skipna=True) or 0)
        stats['total_debit'] = float(normal_df.get('Débit', pd.Series(0)).sum(skipna=True) or 0)
        stats['net'] = stats['total_credit'] - stats['total_debit']

        if mask_ouv.any():
            val = df.loc[mask_ouv, 'Solde'].dropna()
            if not val.empty:
                stats['solde_ouverture'] = float(val.iloc[0])

        if mask_clo.any():
            val = df.loc[mask_clo, 'Solde'].dropna()
            if not val.empty:
                stats['solde_cloture'] = float(val.iloc[-1])

        # --- CONTRÔLE DE COHÉRENCE GLOBAL ---
        # Compare le solde de clôture EXACT (lu sur le relevé) au solde de
        # clôture qu'on obtiendrait en partant du solde d'ouverture EXACT
        # et en y appliquant le flux net des transactions extraites. Un
        # écart proche de 0 confirme que rien n'a été omis/mal lu entre les
        # deux ; un écart significatif signale un problème d'extraction
        # (ligne manquante, montant mal lu) à vérifier contre le PDF.
        if stats['solde_ouverture'] is not None:
            stats['solde_cloture_calcule'] = round(stats['solde_ouverture'] + stats['net'], 2)
            if stats['solde_cloture'] is not None:
                stats['ecart_cloture'] = round(stats['solde_cloture'] - stats['solde_cloture_calcule'], 2)
                stats['coherent'] = abs(stats['ecart_cloture']) <= 1.0

        dates = pd.to_datetime(df.get('Date'), format='%d/%m/%Y', errors='coerce').dropna()
        if not dates.empty:
            stats['periode_debut'] = dates.min().strftime('%d/%m/%Y')
            stats['periode_fin'] = dates.max().strftime('%d/%m/%Y')

        return stats
