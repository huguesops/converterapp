"""
cleaner.py - Version 6.2 (Mise à jour Finale)
Nettoyage des données, élimination des filigranes PDF (ex: UBA) 
et verrouillage chronologique absolu des soldes d'ouverture/clôture.
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
        df = self._apply_date_valeur_rule(df, banque_nom)
        df = self._clean_amounts(df)
        df = self._merge_libelles_minimal(df)
        df = self._clean_libelle(df)
        
        # Déduplication intelligente pour gérer les overlaps d'OpenRouter
        df = self._remove_duplicates_minimal(df)
        
        # Nettoyage et tri
        df = self._remove_fake_balances(df)
        df = self._sort_by_page_line(df)
        
        # NOUVEAU : Verrouillage chronologique des soldes
        df = self._force_balance_positions(df)
        
        df = self._post_process_by_bank(df, banque_nom)

        return df.reset_index(drop=True)

    def _clean_dates(self, df: pd.DataFrame) -> pd.DataFrame:
        for col in ['Date', 'Date_Valeur']:
            if col in df.columns:
                df[col] = df[col].apply(self._normalize_date)
                
        if 'Date' in df.columns:
            df = self._fix_years(df)
            
        return df

    def _normalize_date(self, val) -> str:
        if not val or pd.isna(val):
            return ''
        s = str(val).strip()
        if re.match(r'\d{2}/\d{2}/\d{4}', s):
            return s[:10]
        return s

    def _fix_years(self, df: pd.DataFrame) -> pd.DataFrame:
        def extract_year(s):
            s = str(s)
            match = re.search(r'\b(20\d{2})\b', s)
            if match:
                return int(match.group(1))
            return None
            
        years = df['Date'].apply(extract_year).dropna()
        if not years.empty:
            mode_year = int(years.mode().iloc[0])
            
            def fix_date_str(d_str):
                d_str = str(d_str).strip()
                if not d_str:
                    return d_str
                    
                def replace_bad_year(m):
                    y = int(m.group(0))
                    if y < 2000 or y > 2100:
                        return str(mode_year)
                    return m.group(0)
                    
                return re.sub(r'\b\d{4}\b', replace_bad_year, d_str)
                
            df['Date'] = df['Date'].apply(fix_date_str)
            if 'Date_Valeur' in df.columns:
                df['Date_Valeur'] = df['Date_Valeur'].apply(fix_date_str)
        return df

    def _apply_date_valeur_rule(self, df: pd.DataFrame, banque_nom: str) -> pd.DataFrame:
        is_bgfi = "bgfi" in banque_nom.lower()
        config = get_bank_config(banque_nom)
        
        if not config.date_valeur_is_date and not is_bgfi:
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
        
        s = s.replace(" ", "").replace("\xa0", "")
        s = re.sub(r'[^\d.,-]', '', s)
        if not s: return None
        
        last_sep_idx = max(s.rfind('.'), s.rfind(','))
        
        if last_sep_idx != -1:
            chars_after_sep = len(s) - last_sep_idx - 1
            if chars_after_sep == 3:
                s = s.replace(".", "").replace(",", "")
            elif chars_after_sep in (1, 2):
                s = s[:last_sep_idx].replace(".", "").replace(",", "") + "." + s[last_sep_idx+1:]
            else:
                s = s.replace(".", "").replace(",", "")
                
        try:
            return float(s)
        except:
            return None

    def _merge_libelles_minimal(self, df: pd.DataFrame) -> pd.DataFrame:
        if 'Libellé' not in df.columns or df.empty:
            return df

        df = df.reset_index(drop=True)
        result = []
        i = 0
        while i < len(df):
            row = df.iloc[i].copy()
            libelle = str(row.get('Libellé', '')).strip()

            if i + 1 < len(df):
                next_row = df.iloc[i + 1]
                next_lib = str(next_row.get('Libellé', '')).strip()
                has_date = bool(str(next_row.get('Date', '')).strip())
                has_amount = pd.notna(next_row.get('Débit')) or pd.notna(next_row.get('Crédit'))

                if not has_date and not has_amount and next_lib:
                    libelle = f"{libelle} {next_lib}".strip()
                    i += 1

            row['Libellé'] = libelle
            result.append(row)
            i += 1

        return pd.DataFrame(result)

    def _clean_libelle(self, df: pd.DataFrame) -> pd.DataFrame:
        if 'Libellé' in df.columns:
            # Nettoyage des espaces
            df['Libellé'] = df['Libellé'].astype(str).str.replace(r'\s+', ' ', regex=True).str.strip()
            
            # SUPPRESSION DU FILIGRANE UBA ("The zone serial is [ 6].")
            df['Libellé'] = df['Libellé'].str.replace(r'(?i)The zone serial is\s*\[\s*\d+\s*\]\.?', '', regex=True).str.strip()
            
            # Nettoyage des textes répétés par l'IA dans les colonnes serrées
            df['Libellé'] = df['Libellé'].str.replace(r'(COMM ON DRAFT)\s+\1', r'\1', regex=True)
            df['Libellé'] = df['Libellé'].str.replace(r'(VAT ON DD CHRG)\s+\1', r'\1', regex=True)
            
        return df

    def _remove_duplicates_minimal(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df
            
        df = df.drop_duplicates(keep='first').reset_index(drop=True)
        
        to_drop = []
        for i in range(1, len(df)):
            prev = df.iloc[i-1]
            curr = df.iloc[i]
            
            same_date = curr.get('Date') == prev.get('Date')
            same_debit = (pd.isna(curr.get('Débit')) and pd.isna(prev.get('Débit'))) or (curr.get('Débit') == prev.get('Débit'))
            same_credit = (pd.isna(curr.get('Crédit')) and pd.isna(prev.get('Crédit'))) or (curr.get('Crédit') == prev.get('Crédit'))
            same_solde = pd.notna(curr.get('Solde')) and (curr.get('Solde') == prev.get('Solde'))
            
            if same_date and same_debit and same_credit and same_solde:
                to_drop.append(i)
                
        return df.drop(index=to_drop).reset_index(drop=True)

    def _remove_fake_balances(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty or 'Libellé' not in df.columns:
            return df
            
        df = df.reset_index(drop=True)
        to_drop = []
        opening_indices = []
        closing_indices = []
        
        for i, row in df.iterrows():
            lib = str(row.get('Libellé', '')).lower()
            debit = row.get('Débit')
            credit = row.get('Crédit')
            
            no_mvt = pd.isna(debit) and pd.isna(credit)
            zero_mvt = (debit == 0 or pd.isna(debit)) and (credit == 0 or pd.isna(credit))
            
            if no_mvt or zero_mvt:
                if re.search(r'opening|ouverture|solde\s*(au|de)\s*d[ée]but|report|solde\s*ant[ée]rieur|solde\s*pr[ée]c[ée]dent', lib):
                    opening_indices.append(i)
                elif re.search(r'closing|cl[ôo]ture|balance\s*final|nouveau\s*solde|solde\s*final', lib):
                    closing_indices.append(i)
                elif re.search(r'solde\s*au\s*\d', lib):
                    if i < len(df) / 2:
                        opening_indices.append(i)
                    else:
                        closing_indices.append(i)
                    
        if len(opening_indices) > 1:
            to_drop.extend(opening_indices[1:])
            
        if len(closing_indices) > 1:
            to_drop.extend(closing_indices[:-1])
            
        return df.drop(index=to_drop).reset_index(drop=True)

    def _sort_by_page_line(self, df: pd.DataFrame) -> pd.DataFrame:
        sort_cols = []
        if 'Page_Num' in df.columns:
            sort_cols.append('Page_Num')
        if 'Numero_Ligne' in df.columns:
            sort_cols.append('Numero_Ligne')
            
        if sort_cols:
            df = df.sort_values(by=sort_cols, kind='mergesort', na_position='first')
        return df.reset_index(drop=True)

    def _force_balance_positions(self, df: pd.DataFrame) -> pd.DataFrame:
        """ 
        Force le solde d'ouverture à l'index 0 et le solde de clôture au dernier index.
        Ceci empêche les soldes imprimés dans l'en-tête d'une page (ex: UBA) 
        de se mélanger avec la chronologie des transactions.
        """
        if df.empty or 'Libellé' not in df.columns:
            return df
            
        lib_lower = df['Libellé'].astype(str).str.lower()
        
        is_opening = lib_lower.str.contains(r'ouverture|opening|solde\s*(au|de)\s*d[ée]but|report|solde\s*ant[ée]rieur|solde\s*pr[ée]c[ée]dent', regex=True)
        is_closing = lib_lower.str.contains(r'cl[ôo]ture|cloture|balance\s*final|nouveau\s*solde|solde\s*final', regex=True)
        
        # Pour les libellés génériques
        is_solde_au = lib_lower.str.contains(r'solde\s*au\s*\d', regex=True)
        mid_point = len(df) / 2
        
        mask_opening = is_opening | (is_solde_au & (df.index < mid_point))
        mask_closing = is_closing | (is_solde_au & (df.index >= mid_point))
        
        mask_opening = mask_opening & ~is_closing
        mask_closing = mask_closing & ~is_opening
        
        df_opening = df[mask_opening]
        df_closing = df[mask_closing]
        df_trans = df[~(mask_opening | mask_closing)]
        
        final_parts = []
        if not df_opening.empty:
            final_parts.append(df_opening)
            
        final_parts.append(df_trans.sort_index())
        
        if not df_closing.empty:
            final_parts.append(df_closing)
            
        return pd.concat(final_parts, ignore_index=True) if final_parts else df

    def _post_process_by_bank(self, df: pd.DataFrame, banque_nom: str) -> pd.DataFrame:
        column_mapping = {
            'Particulars': 'Libellé', 'Particularités': 'Libellé', 'Désignation': 'Libellé',
            'Libellé de l\'opération': 'Libellé', 'Libelle et Référence': 'Libellé', 'Narration': 'Libellé',
            'Batch/Ref': 'Référence', 'Cheq#': 'Référence', 'N° Pièce': 'Référence',
            'VE N°': 'Référence', 'CHQ N°': 'Référence', 'Pièce N°': 'Référence', 'Tran Ref': 'Référence',
        }
        
        for col in df.columns:
            if col in column_mapping and column_mapping[col] not in df.columns:
                df = df.rename(columns={col: column_mapping[col]})

        banque_lower = banque_nom.lower()
        if "unics" in banque_lower:
            if 'Libellé' in df.columns:
                df['Libellé'] = df['Libellé'].apply(
                    lambda x: re.sub(r'\s+', ' ', str(x)).strip() if pd.notna(x) else x
                )
        elif "mupeci" in banque_lower:
            if 'Libellé' in df.columns:
                df['Libellé'] = df['Libellé'].apply(
                    lambda x: re.sub(r'Remettant\s*:\s*', '', str(x)).strip() if pd.notna(x) else x
                )

        return df

    def check_consistency(self, df: pd.DataFrame, tolerance: float = 1.0) -> pd.DataFrame:
        if df.empty or 'Solde' not in df.columns:
            df['Écart'] = None
            return df

        df = df.reset_index(drop=True)
        lib_lower = df.get('Libellé', pd.Series('', index=df.index)).astype(str).str.lower()
        is_opening = lib_lower.str.contains(r'ouverture|opening|solde\s*(au|de)\s*d[ée]but|report|solde\s*ant[ée]rieur|solde\s*pr[ée]c[ée]dent|solde\s*au\s*\d', na=False, regex=True)

        ecarts = [None] * len(df)
        for i in range(1, len(df)):
            if is_opening.iloc[i]:
                continue
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
        stats = {
            'total_transactions': 0, 'total_credit': 0.0, 'total_debit': 0.0, 'net': 0.0,
            'solde_ouverture': None, 'solde_cloture': None, 'ecart_ouverture_cloture': None,
            'periode_debut': '', 'periode_fin': '',
        }

        if df.empty:
            return stats

        config = get_bank_config(banque_nom)
        pattern_ouv = "|".join(config.solde_ouverture_patterns) or r"ouverture|opening|solde\s*(au|de)\s*d[ée]but|report|solde\s*ant[ée]rieur|solde\s*pr[ée]c[ée]dent|solde\s*au\s*\d"
        pattern_clo = "|".join(config.solde_cloture_patterns) or r"cl[ôo]ture|cloture|balance\s*final|nouveau\s*solde|solde\s*final|solde\s*au\s*\d"

        lib_lower = df.get('Libellé', pd.Series('')).astype(str).str.lower()
        mask_ouv = lib_lower.str.contains(pattern_ouv, na=False, regex=True)
        mask_clo = lib_lower.str.contains(pattern_clo, na=False, regex=True)

        normal_df = df[~(mask_ouv | mask_clo)]

        stats['total_transactions'] = len(normal_df)
        stats['total_credit'] = float(normal_df.get('Crédit', pd.Series(0)).sum(skipna=True) or 0)
        stats['total_debit'] = float(normal_df.get('Débit', pd.Series(0)).sum(skipna=True) or 0)
        stats['net'] = stats['total_credit'] - stats['total_debit']

        if 'Solde' in df.columns:
            solde_col = pd.to_numeric(df['Solde'], errors='coerce')
            solde_non_na = solde_col.dropna()
            if not solde_non_na.empty:
                stats['solde_ouverture'] = float(solde_non_na.iloc[0])
                stats['solde_cloture'] = float(solde_non_na.iloc[-1])

        if stats['solde_ouverture'] is not None and stats['solde_cloture'] is not None:
            attendu = stats['solde_ouverture'] + stats['net']
            stats['ecart_ouverture_cloture'] = round(stats['solde_cloture'] - attendu, 2)

        dates = pd.to_datetime(df.get('Date'), format='%d/%m/%Y', errors='coerce').dropna()
        if not dates.empty:
            stats['periode_debut'] = dates.min().strftime('%d/%m/%Y')
            stats['periode_fin'] = dates.max().strftime('%d/%m/%Y')

        return stats
