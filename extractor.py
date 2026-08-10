import pdfplumber
import pandas as pd
import re
import io
import os
from PIL import Image

try:
    import pytesseract
    from pdf2image import convert_from_bytes
    import cv2
    import numpy as np
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False


class BankStatementExtractor:
    """
    Extracteur de relevés bancaires PDF.
    Supporte les PDF natifs et les PDF scannés (OCR).
    Compatible Financial House S.A et autres formats.
    """

    MONTH_MAP = {
        'jan': '01', 'feb': '02', 'mar': '03', 'apr': '04',
        'may': '05', 'jun': '06', 'jul': '07', 'aug': '08',
        'sep': '09', 'oct': '10', 'nov': '11', 'dec': '12',
        'janvier': '01', 'février': '02', 'mars': '03',
        'avril': '04', 'mai': '05', 'juin': '06',
        'juillet': '07', 'août': '08', 'septembre': '09',
        'octobre': '10', 'novembre': '11', 'décembre': '12'
    }

    IGNORE_PATTERNS = [
        r'financial house', r'fh sa', r'historique compte',
        r'branch id', r'account id', r'periode du',
        r'print date', r'page num', r'printed by',
        r'working date', r'br\.net', r'^totaux',
        r'ibantio', r'bdjoko', r'gtakeu', r'ideynou',
        r'mmodjo', r'ndjiemoum'
    ]

    def __init__(self, progress_callback=None):
        """
        Args:
            progress_callback: fonction(step: int, message: str)
                               pour mettre à jour la progression
        """
        self.progress_callback = progress_callback

    def _update_progress(self, step: int, message: str):
        if self.progress_callback:
            self.progress_callback(step, message)

    # ------------------------------------------------------------------
    # POINT D'ENTRÉE PRINCIPAL
    # ------------------------------------------------------------------

    def extract(self, pdf_bytes: bytes) -> pd.DataFrame:
        """
        Extrait les données d'un PDF bancaire.

        Args:
            pdf_bytes: contenu du fichier PDF en bytes

        Returns:
            DataFrame structuré avec les colonnes :
            Date, Référence, Libellé, Date_Valeur, Débit, Crédit, Solde
        """
        self._update_progress(10, "🔍 Analyse du PDF...")

        # Tentative 1 : extraction native (PDF texte)
        df = self._extract_native(pdf_bytes)

        if df is not None and len(df) >= 3:
            self._update_progress(80, "✅ Extraction native réussie")
            return self._finalize(df)

        # Tentative 2 : OCR (PDF scanné)
        if OCR_AVAILABLE:
            self._update_progress(40, "🔍 PDF scanné — lancement OCR...")
            df = self._extract_ocr(pdf_bytes)
            if df is not None and not df.empty:
                self._update_progress(80, "✅ Extraction OCR réussie")
                return self._finalize(df)

        self._update_progress(80, "⚠️ Données partielles extraites")
        return pd.DataFrame(columns=[
            'Date', 'Référence', 'Libellé',
            'Date_Valeur', 'Débit', 'Crédit', 'Solde'
        ])

    # ------------------------------------------------------------------
    # EXTRACTION NATIVE (pdfplumber)
    # ------------------------------------------------------------------

    def _extract_native(self, pdf_bytes: bytes):
        rows = []
        try:
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                total_pages = len(pdf.pages)
                for page_num, page in enumerate(pdf.pages):
                    progress = 10 + int((page_num / total_pages) * 50)
                    self._update_progress(
                        progress,
                        f"📃 Extraction page {page_num+1}/{total_pages}"
                    )

                    # Essai tableaux structurés
                    tables = page.extract_tables({
                        "vertical_strategy": "lines",
                        "horizontal_strategy": "lines",
                        "snap_tolerance": 3,
                        "join_tolerance": 3,
                        "edge_min_length": 3,
                    })

                    if tables:
                        for table in tables:
                            rows.extend(self._process_table(table))
                    else:
                        # Fallback : extraction par mots + position
                        rows.extend(self._extract_by_words(page))

            return pd.DataFrame(rows) if rows else None

        except Exception as e:
            print(f"Erreur extraction native: {e}")
            return None

    def _process_table(self, table: list) -> list:
        """Traite un tableau pdfplumber en liste de dicts."""
        rows = []
        pending_libelle_append = None  # pour les libellés multi-lignes

        for raw_row in table:
            if not raw_row:
                continue

            cells = [str(c).strip() if c else '' for c in raw_row]

            # Ligne totalement vide
            if all(c == '' or c == 'None' for c in cells):
                continue

            # En-tête de tableau
            if self._is_header(cells):
                continue

            # Ligne à ignorer (en-têtes de page, etc.)
            joined = ' '.join(cells).lower()
            if any(re.search(p, joined) for p in self.IGNORE_PATTERNS):
                continue

            # Ligne de continuation (libellé multi-ligne)
            # → pas de date, pas de référence, mais du texte
            if (not cells[0] or not re.search(r'\d', cells[0])) and \
               (len(cells) < 2 or not cells[1]):
                text = ' '.join(c for c in cells if c)
                if text and rows:
                    rows[-1]['Libellé'] = (
                        rows[-1].get('Libellé', '') + ' ' + text
                    ).strip()
                continue

            row_dict = self._cells_to_dict(cells)
            if row_dict:
                rows.append(row_dict)

        return rows

    def _cells_to_dict(self, cells: list) -> dict:
        """Convertit une liste de cellules en dict structuré."""
        joined = ' '.join(cells).strip()
        joined_lower = joined.lower()

        # Solde d'ouverture
        if re.search(r"solde\s+d['\"']?\s*ouverture", joined_lower):
            amounts = [self._clean_amount(c) for c in cells
                       if re.search(r'[\d\s]{4,}', c)]
            solde = amounts[-1] if amounts else ''
            return self._make_row('', '', "Solde d'ouverture",
                                  '', '', '', solde)

        # Solde de clôture
        if re.search(r"solde\s+de\s+cl[oô]ture", joined_lower):
            amounts = [self._clean_amount(c) for c in cells
                       if re.search(r'[\d\s]{4,}', c)]
            solde = amounts[-1] if amounts else ''
            return self._make_row('', '', "Solde de clôture",
                                  '', '', '', solde)

        # Frais / lignes spéciales à 2 lignes dans le PDF
        # → on les capture si la date est présente
        date_str = self._find_date(cells[0]) if cells else ''
        if not date_str:
            # Chercher la date dans toute la ligne
            for c in cells:
                date_str = self._find_date(c)
                if date_str:
                    break

        if not date_str:
            return None

        # Référence
        ref = ''
        for c in cells:
            m = re.search(r'(\d{3,6}/)', c)
            if m:
                ref = m.group(1)
                break

        # Libellé : cellule après référence (index 2 souvent)
        libelle = cells[2] if len(cells) > 2 else ''
        if not libelle:
            # Reconstruire depuis toutes les cellules non-numériques
            libelle = ' '.join(
                c for c in cells
                if c and not re.match(r'^[\d\s/]+$', c)
                and c != date_str and c != ref
            )

        # Date valeur
        date_valeur = ''
        for c in cells[3:]:
            dv = self._find_date(c)
            if dv and dv != date_str:
                date_valeur = dv
                break

        # Montants (débit, crédit, solde)
        amounts = [
            self._clean_amount(c) for c in cells
            if self._is_amount(c)
        ]

        debit, credit, solde = '', '', ''
        if len(amounts) == 1:
            solde = amounts[0]
        elif len(amounts) == 2:
            credit = amounts[0]
            solde = amounts[1]
        elif len(amounts) >= 3:
            debit = amounts[-3] if amounts[-3] else ''
            credit = amounts[-2] if amounts[-2] else ''
            solde = amounts[-1]

        return self._make_row(date_str, ref, libelle.strip(),
                              date_valeur, debit, credit, solde)

    def _extract_by_words(self, page) -> list:
        """Fallback : regrouper les mots par position Y."""
        words = page.extract_words(
            x_tolerance=4, y_tolerance=4,
            keep_blank_chars=False
        )
        if not words:
            return []

        # Grouper par ligne
        lines = {}
        for w in words:
            y = round(float(w['top']) / 5) * 5
            lines.setdefault(y, []).append(w)

        rows = []
        for y in sorted(lines):
            line_words = sorted(lines[y], key=lambda w: w['x0'])
            text = ' '.join(w['text'] for w in line_words)

            # Ignorer
            text_lower = text.lower()
            if any(re.search(p, text_lower) for p in self.IGNORE_PATTERNS):
                continue

            # Construire les cellules virtuelles par zone X
            cells = self._words_to_cells(line_words, page.width)
            row_dict = self._cells_to_dict(cells)
            if row_dict:
                rows.append(row_dict)

        return rows

    def _words_to_cells(self, words: list, page_width: float) -> list:
        """Assigne chaque mot à une colonne selon sa position X."""
        # Zones : date(0-15%), ref(15-28%), libelle(28-52%),
        #         dvaleur(52-65%), debit(65-75%), credit(75-87%), solde(87-100%)
        zones = [
            (0.00, 0.15),   # Date
            (0.15, 0.28),   # Référence
            (0.28, 0.52),   # Libellé
            (0.52, 0.65),   # D. Valeur
            (0.65, 0.75),   # Débit
            (0.75, 0.87),   # Crédit
            (0.87, 1.00),   # Solde
        ]
        cells = [''] * len(zones)
        for w in words:
            ratio = w['x0'] / page_width
            for i, (lo, hi) in enumerate(zones):
                if lo <= ratio < hi:
                    cells[i] = (cells[i] + ' ' + w['text']).strip()
                    break
        return cells

    # ------------------------------------------------------------------
    # EXTRACTION OCR
    # ------------------------------------------------------------------

    def _extract_ocr(self, pdf_bytes: bytes):
        if not OCR_AVAILABLE:
            return None

        rows = []
        try:
            images = convert_from_bytes(pdf_bytes, dpi=300)
            total = len(images)

            for i, img in enumerate(images):
                progress = 40 + int((i / total) * 35)
                self._update_progress(
                    progress,
                    f"🔍 OCR page {i+1}/{total}"
                )

                processed = self._preprocess_image(img)
                text = pytesseract.image_to_string(
                    processed,
                    config=r'--oem 3 --psm 6 -l fra+eng'
                )

                for line in text.split('\n'):
                    line = line.strip()
                    if not line:
                        continue
                    row = self._parse_text_line(line)
                    if row:
                        rows.append(row)

            return pd.DataFrame(rows) if rows else None

        except Exception as e:
            print(f"Erreur OCR: {e}")
            return None

    def _preprocess_image(self, img: Image.Image) -> Image.Image:
        """Améliore l'image pour l'OCR."""
        if not OCR_AVAILABLE:
            return img
        try:
            arr = np.array(img.convert('RGB'))
            gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            enhanced = clahe.apply(gray)
            denoised = cv2.fastNlMeansDenoising(enhanced, h=10)
            binary = cv2.adaptiveThreshold(
                denoised, 255,
                cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY, 11, 2
            )
            return Image.fromarray(binary)
        except Exception:
            return img

    def _parse_text_line(self, line: str) -> dict:
        """Parse une ligne de texte OCR."""
        line_lower = line.lower()

        if any(re.search(p, line_lower) for p in self.IGNORE_PATTERNS):
            return None

        if re.search(r"solde\s+d['\"']?\s*ouverture", line_lower):
            amounts = re.findall(r'\d[\d\s]{3,}\d', line)
            solde = self._clean_amount(amounts[-1]) if amounts else ''
            return self._make_row('', '', "Solde d'ouverture",
                                  '', '', '', solde)

        if re.search(r"solde\s+de\s+cl[oô]ture", line_lower):
            amounts = re.findall(r'\d[\d\s]{3,}\d', line)
            solde = self._clean_amount(amounts[-1]) if amounts else ''
            return self._make_row('', '', "Solde de clôture",
                                  '', '', '', solde)

        date_str = self._find_date(line)
        if not date_str:
            return None

        ref_match = re.search(r'(\d{3,6}/)', line)
        ref = ref_match.group(1) if ref_match else ''

        # Libellé = texte entre référence et montants
        libelle = re.sub(
            r'\d{2}[/\-]\w+[/\-]\d{4}|\d{2}/\d{2}/\d{4}|'
            r'\d{3,6}/|\d{5,}', '', line
        ).strip()
        libelle = re.sub(r'\s+', ' ', libelle).strip()

        numbers = re.findall(r'\d[\d\s]{3,}\d', line)
        cleaned = [self._clean_amount(n) for n in numbers]
        valid = [n for n in cleaned if n and len(n) >= 3]

        debit, credit, solde = '', '', ''
        if valid:
            solde = valid[-1]
            if len(valid) >= 2:
                credit = valid[-2]

        return self._make_row(date_str, ref, libelle, '', debit, credit, solde)

    # ------------------------------------------------------------------
    # POST-TRAITEMENT
    # ------------------------------------------------------------------

    def _finalize(self, df: pd.DataFrame) -> pd.DataFrame:
        """Nettoyage final du DataFrame."""
        self._update_progress(90, "🧹 Nettoyage des données...")

        expected = ['Date', 'Référence', 'Libellé',
                    'Date_Valeur', 'Débit', 'Crédit', 'Solde']

        for col in expected:
            if col not in df.columns:
                df[col] = ''

        df = df[expected].copy()

        # Nettoyage des montants
        for col in ['Débit', 'Crédit', 'Solde']:
            df[col] = df[col].apply(self._clean_amount)
            df[col] = pd.to_numeric(df[col], errors='coerce')

        # Supprimer les lignes inutiles
        df = df[df['Libellé'].notna() & (df['Libellé'] != '')]
        df = df[df['Libellé'].str.lower().apply(
            lambda x: not any(re.search(p, x) for p in self.IGNORE_PATTERNS)
        )]

        # Nettoyer les libellés
        df['Libellé'] = df['Libellé'].str.replace(r'\s+', ' ', regex=True).str.strip()

        df = df.reset_index(drop=True)
        self._update_progress(100, "✅ Terminé !")
        return df

    # ------------------------------------------------------------------
    # UTILITAIRES
    # ------------------------------------------------------------------

    def _find_date(self, text: str) -> str:
        """Cherche et normalise une date dans un texte."""
        if not text:
            return ''

        # Format 02/Jan/2025 ou 02-Jan-2025
        m = re.search(
            r'(\d{2})[/\-](\w{3,})[/\-](\d{4})',
            text, re.IGNORECASE
        )
        if m:
            day, month, year = m.groups()
            month_num = self.MONTH_MAP.get(month.lower()[:3], '')
            if month_num:
                return f"{day}/{month_num}/{year}"

        # Format 02/01/2025
        m = re.search(r'(\d{2}/\d{2}/\d{4})', text)
        if m:
            return m.group(1)

        return ''

    def _clean_amount(self, val) -> str:
        """Supprime les espaces et caractères non numériques."""
        if val is None:
            return ''
        s = str(val).strip()
        s = re.sub(r'[\s\xa0\u202f]', '', s)
        s = re.sub(r'[^\d]', '', s)
        return s if s else ''

    def _is_amount(self, text: str) -> bool:
        """Vérifie si un texte ressemble à un montant."""
        if not text:
            return False
        cleaned = re.sub(r'[\s\xa0]', '', str(text))
        return bool(re.match(r'^\d{3,}$', cleaned))

    def _is_header(self, cells: list) -> bool:
        """Détecte une ligne d'en-tête de tableau."""
        text = ' '.join(cells).lower()
        keywords = ['date', 'batch', 'libelle', 'libellé',
                    'valeur', 'debit', 'débit', 'credit',
                    'crédit', 'solde', 'ref']
        return sum(1 for k in keywords if k in text) >= 3

    def _make_row(self, date, ref, libelle, date_valeur,
                  debit, credit, solde) -> dict:
        return {
            'Date': date,
            'Référence': ref,
            'Libellé': libelle,
            'Date_Valeur': date_valeur,
            'Débit': debit,
            'Crédit': credit,
            'Solde': solde,
        }
