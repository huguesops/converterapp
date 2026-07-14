"""
extractor_gemini.py - Version 4.2
Correction critique des montants + robustesse
"""

import google.generativeai as genai
import pandas as pd
import json
import re
import time
import traceback
from PIL import Image
from typing import List, Dict, Optional

try:
    from pdf2image import convert_from_bytes
    PDF2IMAGE_AVAILABLE = True
except ImportError:
    PDF2IMAGE_AVAILABLE = False

from bank_configs import get_bank_config, BankConfig


class DebugLogger:
    LEVELS = {
        "INFO": "ℹ️", "SUCCESS": "✅", "WARNING": "⚠️", "ERROR": "❌",
        "DEBUG": "🔍", "STEP": "▶️", "DATA": "📊", "API": "🤖",
    }

    def __init__(self, verbose: bool = True):
        self.verbose = verbose
        self.logs = []
        self.errors = []
        self.warnings = []
        self._step = 0

    def _log(self, level: str, msg: str, detail: str = ""):
        icon = self.LEVELS.get(level, "•")
        ts = time.strftime("%H:%M:%S")
        entry = {"level": level, "icon": icon, "message": str(msg), "detail": str(detail), "timestamp": ts}
        self.logs.append(entry)
        if self.verbose:
            print(f"[{ts}] {icon} {msg}")
            if detail:
                for line in str(detail).split("\n")[:5]:
                    if line.strip():
                        print(f"       {line}")

    def info(self, msg, detail=""): self._log("INFO", msg, detail)
    def success(self, msg, detail=""): self._log("SUCCESS", msg, detail)
    def warning(self, msg, detail=""):
        self._log("WARNING", msg, detail)
        self.warnings.append(msg)
    def error(self, msg, detail="", exc=None):
        if exc:
            detail += f"\n{type(exc).__name__}: {str(exc)}\n{traceback.format_exc()}"
        self._log("ERROR", msg, detail)
        self.errors.append({"msg": msg, "detail": detail})
    def debug(self, msg, detail=""): self._log("DEBUG", msg, detail)
    def step(self, msg):
        self._step += 1
        self._log("STEP", f"[Étape {self._step}] {msg}")
    def data(self, label, value):
        val_str = str(value)[:800] + ("..." if len(str(value)) > 800 else "")
        self._log("DATA", label, val_str)
    def api(self, msg, detail=""): self._log("API", msg, detail)

    def get_logs_as_text(self) -> str:
        lines = []
        for log in self.logs:
            line = f"[{log['timestamp']}] {log['icon']} {log['message']}"
            if log.get("detail"):
                for dl in log["detail"].split("\n")[:4]:
                    if dl.strip():
                        line += f"\n    └─ {dl.strip()}"
            lines.append(line)
        return "\n".join(lines)

    def get_summary(self) -> dict:
        return {
            "total_logs": len(self.logs),
            "errors": len(self.errors),
            "warnings": len(self.warnings),
            "steps": self._step,
        }

    def get_entries(self) -> list:
        return self.logs


class GeminiExtractor:
    def __init__(
        self,
        api_key: str,
        mode: str = "vision",
        banque_nom: str = "Autre banque",
        progress_callback=None,
        verbose_debug: bool = True,
    ):
        self.api_key = api_key
        self.mode = mode
        self.banque_nom = banque_nom
        self.config = get_bank_config(banque_nom)
        self.progress_callback = progress_callback
        self.logger = DebugLogger(verbose=verbose_debug)

        self._configure_gemini()

    def _configure_gemini(self):
        self.logger.step("Configuration API Gemini")
        try:
            genai.configure(api_key=self.api_key)
            self.model = genai.GenerativeModel(
                model_name="gemini-2.5-flash",
                generation_config=genai.GenerationConfig(
                    temperature=0, top_p=1, top_k=1, max_output_tokens=8192,
                ),
                safety_settings=[
                    {"category": cat, "threshold": "BLOCK_NONE"}
                    for cat in ["HARM_CATEGORY_HARASSMENT", "HARM_CATEGORY_HATE_SPEECH",
                                "HARM_CATEGORY_SEXUALLY_EXPLICIT", "HARM_CATEGORY_DANGEROUS_CONTENT"]
                ],
            )
            self.logger.success("Gemini configuré", f"Banque: {self.banque_nom} | Mode: {self.mode}")
        except Exception as e:
            self.logger.error("Échec configuration Gemini", exc=e)
            raise

    def _update_progress(self, step: int, msg: str):
        if self.progress_callback:
            self.progress_callback(step, msg)

    def _build_prompt(self, is_vision: bool = True) -> str:
        c = self.config

        json_example = '''
{
  "transactions": [
    {
      "date": "JJ/MM/AAAA",
      "reference": "",
      "libelle": "description complète",
      "date_valeur": "JJ/MM/AAAA",
      "debit": null,
      "credit": null,
      "solde": 0
    }
  ]
}
'''

        prompt = f"""Tu es un expert comptable très rigoureux spécialisé dans les relevés UNICS et autres banques camerounaises.

**MISSION CRITIQUE** : Extraire **TOUTES** les lignes du tableau visibles sur l'image, **sans en sauter aucune**, même si elles sont similaires ou longues.

**Colonnes** :
- Date
- Référence / Cheq#
- Libellé / Particulars (peut être sur plusieurs lignes)
- Date Valeur
- Débit
- Crédit
- Solde

**Instructions pour {c.nom}** :
{c.specific_instructions}

**Règles NON NÉGOCIABLES** :
1. Tu dois lister **chaque ligne de transaction** une par une, du haut vers le bas.
2. Ne jamais sauter une ligne qui contient un montant en Débit ou Crédit.
3. Si une ligne a un libellé long commençant par "WDL chq no." ou "CASH CREDIT BY", tu dois l'inclure intégralement.
4. Montants : retourne uniquement des chiffres sans virgule ni espace (ex: 308000, 903413).
5. Retourne **uniquement** le JSON suivant, sans aucun commentaire :

{json_example}
"""

        if not is_vision:
            prompt += "\nLe texte est extrait via pdfplumber. Sois exhaustif et ne saute aucune ligne du tableau."

        return prompt

    def extract(self, pdf_bytes: bytes) -> pd.DataFrame:
        self.logger.step(f"Début extraction {self.banque_nom} - Mode {self.mode}")
        if self.mode == "hybrid":
            return self._extract_hybrid(pdf_bytes)
        return self._extract_vision(pdf_bytes)

    def _extract_vision(self, pdf_bytes: bytes) -> pd.DataFrame:
        if not PDF2IMAGE_AVAILABLE:
            self.logger.error("pdf2image non disponible")
            return self._empty_df()

        self._update_progress(10, "Conversion PDF en images...")
        try:
            images = convert_from_bytes(pdf_bytes, dpi=250, fmt="PNG")
            self.logger.success(f"{len(images)} images générées")
        except Exception as e:
            self.logger.error("Échec conversion PDF", exc=e)
            return self._empty_df()

        prompt = self._build_prompt(is_vision=True)
        all_transactions = []

        for idx, image in enumerate(images, 1):
            self._update_progress(15 + int(70 * idx / len(images)), f"Analyse page {idx}/{len(images)}")
            transactions = self._call_vision_single_page(image, idx, prompt)
            all_transactions.extend(transactions)

        return self._build_dataframe(all_transactions)

    def _call_vision_single_page(self, image: Image.Image, page_num: int, prompt: str) -> List[Dict]:
        optimized = self._optimize_image(image)
        for attempt in range(1, 4):
            try:
                response = self.model.generate_content([prompt, optimized], request_options={"timeout": 90})
                raw_text = response.text if hasattr(response, "text") and response.text else ""
                if not raw_text and hasattr(response, "candidates"):
                    raw_text = response.candidates[0].content.parts[0].text
                return self._parse_response(raw_text, f"page {page_num}")
            except Exception as e:
                if attempt == 3:
                    self.logger.error(f"Échec page {page_num}", exc=e)
                time.sleep(2)
        return []

    def _optimize_image(self, image: Image.Image) -> Image.Image:
        if image.mode != "RGB":
            image = image.convert("RGB")
        if image.width > 2000:
            ratio = 2000 / image.width
            image = image.resize((2000, int(image.height * ratio)), Image.LANCZOS)
        return image

    def _extract_hybrid(self, pdf_bytes: bytes) -> pd.DataFrame:
        self.logger.warning("Mode Hybride → basculement vers Vision")
        return self._extract_vision(pdf_bytes)

    def _parse_response(self, raw: str, context: str) -> List[Dict]:
        if not raw:
            return []
        text = re.sub(r"```(?:json)?\s*|\s*```", "", raw, flags=re.IGNORECASE).strip()
        try:
            data = json.loads(text)
            transactions = data.get("transactions", [])
            return [self._normalize(t) for t in transactions if self._normalize(t)]
        except:
            return []

    def _normalize(self, t: Dict) -> Optional[Dict]:
        if not isinstance(t, dict):
            return None
        libelle = str(t.get("libelle", "")).strip()
        if not libelle or libelle.lower() in ("none", "null"):
            return None
        return {
            "date": str(t.get("date", "")).strip()[:10],
            "reference": str(t.get("reference", "")).strip(),
            "libelle": libelle,
            "date_valeur": str(t.get("date_valeur", "")).strip()[:10],
            "debit": self._fmt_amount(t.get("debit")),
            "credit": self._fmt_amount(t.get("credit")),
            "solde": self._fmt_amount(t.get("solde")),
        }

    def _fmt_amount(self, val) -> Optional[float]:
        """Version robuste pour gérer les montants avec virgules (format camerounais)"""
        if val is None or str(val).lower() in ("null", "none", "", "0"):
            return None
        try:
            s = str(val).strip()
            # Supprime tout sauf chiffres, point et virgule
            s = re.sub(r"[^\d.,-]", "", s)
            # Remplace virgule par point
            s = s.replace(",", ".")
            # Si plusieurs points → c'est un séparateur de milliers → on le supprime
            if s.count('.') > 1:
                s = s.replace(".", "")
            return float(s) if s else None
        except Exception:
            return None

    def _build_dataframe(self, transactions: List[Dict]) -> pd.DataFrame:
        if not transactions:
            return self._empty_df()

        return pd.DataFrame([{
            "Date": t["date"],
            "Référence": t["reference"],
            "Libellé": t["libelle"],
            "Date_Valeur": t["date_valeur"],
            "Débit": t["debit"],
            "Crédit": t["credit"],
            "Solde": t["solde"],
        } for t in transactions])

    def _empty_df(self) -> pd.DataFrame:
        return pd.DataFrame(columns=["Date", "Référence", "Libellé", "Date_Valeur", "Débit", "Crédit", "Solde"])

    # Méthodes publiques appelées par app.py
    def get_debug_logs(self) -> str:
        return self.logger.get_logs_as_text()

    def get_debug_summary(self) -> dict:
        return self.logger.get_summary()

    def get_debug_entries(self) -> list:
        return self.logger.get_entries()
