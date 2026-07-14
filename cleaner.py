"""
cleaner.py - Version 4.6
Ultra-conservatrice : on ne supprime presque rien
"""

import pandas as pd
import numpy as np
import re
from typing import Optional

class DataCleaner:
    def clean(self, df: pd.DataFrame, banque_nom: str = "Autre banque") -> pd.DataFrame:
        if df.empty:
            return df

        df = df.copy()

        df = self._clean_dates(df)
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

    def _clean_amounts(self, df: pd.DataFrame) -> pd.DataFrame:
        for col in ['Débit', 'Crédit', 'Solde']:
            if col in df.columns:
                df[col] = df[col].apply(self._parse_amount)
        return df

    def _parse_amount(self, val) -> Optional[float]:
        if val is None or pd.isna(val):
            return None
        s = str(val).strip()
        if s.lower() in ('null', 'none', '', '0'):
            return None
        try:
            s = re.sub(r'[^\d.,-]', '', s)
            s = s.replace(',', '.')
            if s.count('.') > 1:
                s = s.replace('.', '')
            return float(s) if s else None
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
            # BGFI : extraire le numéro de pièce si présent dans une colonne dédiée
            pass
            
        elif "mupeci" in banque_lower:
            # MUPECI : nettoyer les mentions "Remettant :"
            if 'Libellé' in df.columns:
                df['Libellé'] = df['Libellé'].apply(
                    lambda x: re.sub(r'Remettant\s*:\s*', '', str(x)).strip() if pd.notna(x) else x
                )

        return df

    def get_statistics(self, df: pd.DataFrame) -> dict:
        stats = {
            'total_transactions': 0,
            'total_credit': 0.0,
            'total_debit': 0.0,
            'net': 0.0,
            'solde_ouverture': None,
            'solde_cloture': None,
            'periode_debut': '',
            'periode_fin': '',
        }

        if df.empty:
            return stats

        lib_lower = df.get('Libellé', pd.Series('')).astype(str).str.lower()
        mask_ouv = lib_lower.str.contains('ouverture|opening|report solde antérieur', na=False)
        mask_clo = lib_lower.str.contains('cl[ôo]ture|cloture|solde final|solde crediteur|total mouvements', na=False)

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

        dates = pd.to_datetime(df.get('Date'), format='%d/%m/%Y', errors='coerce').dropna()
        if not dates.empty:
            stats['periode_debut'] = dates.min().strftime('%d/%m/%Y')
            stats['periode_fin'] = dates.max().strftime('%d/%m/%Y')

        return stats
