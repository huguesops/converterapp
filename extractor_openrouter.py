"""
extractor_openrouter.py - Version 2.0
Extraction des relevés bancaires via OpenRouter API
Correction : ouverture, clôture, toutes les lignes sans saut
"""

import base64
import json
import re
import time
import traceback
from io import BytesIO
from typing import List, Dict, Optional, Callable

import pandas as pd
import requests
from PIL import Image

try:
    from pdf2image import convert_from_bytes
    PDF2IMAGE_AVAILABLE = True
except ImportError:
    PDF2IMAGE_AVAILABLE = False

from bank_configs import get_bank_config, BankConfig


# ====================== CONFIGURATION OPENROUTER ======================

OPENROUTER_API_BASE = "https://openrouter.ai/api/v1"

# ═══════════════════════════════════════════════════════════════
# Modèle IA par défaut (modifiable ici DIRECTEMENT dans le code)
# ═══════════════════════════════════════════════════════════════
DEFAULT_MODEL = "qwen/qwen3-next-80b-a3b-instruct:free"

# Modèles de fallback en cas d'échec du modèle principal
DEFAULT_FALLBACK_MODELS = [
    "openai/gpt-4o-mini",
    "anthropic/claude-3.5-sonnet",
    "google/gemini-2.5-flash-preview-04-17",
]

# Modèles supportant la vision (analyse d'images)
VISION_MODELS = {
    "openai/gpt-4o",
    "openai/gpt-4o-mini",
    "anthropic/claude-3.5-sonnet",
    "anthropic/claude-3-opus",
    "google/gemini-2.0-flash-exp:free",
    "google/gemini-2.5-flash-preview-04-17",
    "deepseek/deepseek-chat",
    "poolside/laguna-xs-2.1:free",
    "meta-llama/llama-3.2-90b-vision",
    "nvidia/nemotron-3.5-content-safety:free",
}


# ====================== DEBUG LOGGER ======================

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


# ====================== EXTRACTEUR PRINCIPAL ======================

class OpenRouterExtractor:
    """
    Extracteur de relevés bancaires utilisant l'API OpenRouter.
    Supporte le mode vision (analyse d'images) et le mode texte.
    Avec fallback automatique entre modèles.
    """

    def __init__(
        self,
        api_key: str,
        mode: str = "vision",
        banque_nom: str = "Autre banque",
        model: Optional[str] = None,
        fallback_models: Optional[List[str]] = None,
        progress_callback: Optional[Callable] = None,
        verbose_debug: bool = True,
    ):
        self.api_key = api_key
        self.mode = mode
        self.banque_nom = banque_nom
        self.config = get_bank_config(banque_nom)
        self.model = model or DEFAULT_MODEL
        self.fallback_models = fallback_models or DEFAULT_FALLBACK_MODELS
        self.progress_callback = progress_callback
        self.logger = DebugLogger(verbose=verbose_debug)
        self._current_model = self.model

    def _update_progress(self, step: int, msg: str):
        if self.progress_callback:
            self.progress_callback(step, msg)

    def _get_model_display_name(self, model_id: str) -> str:
        return model_id

    # ----------------------------------------------------------------
    # APPELS API OPENROUTER
    # ----------------------------------------------------------------

    def _call_openrouter_vision(self, image_base64: str, prompt: str, page_num: int) -> Optional[str]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://skab-extractor.app",
            "X-Title": "SKAB Bank Statement Extractor",
        }

        payload = {
            "model": self._current_model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{image_base64}",
                                "detail": "high",
                            },
                        },
                    ],
                }
            ],
            "max_tokens": 8192,
            "temperature": 0.0,
            "top_p": 1.0,
        }

        model_display = self._get_model_display_name(self._current_model)
        self.logger.api(f"Appel OpenRouter [{model_display}] - Page {page_num}")

        try:
            response = requests.post(
                f"{OPENROUTER_API_BASE}/chat/completions",
                headers=headers,
                json=payload,
                timeout=120,
            )

            if response.status_code == 200:
                data = response.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                usage = data.get("usage", {})
                if usage:
                    self.logger.debug(
                        f"Tokens: {usage.get('prompt_tokens', '?')} prompt / {usage.get('completion_tokens', '?')} completion"
                    )
                return content
            else:
                error_detail = response.text[:500]
                self.logger.error(f"Erreur API {response.status_code}", f"Détail: {error_detail}")
                return None

        except requests.exceptions.Timeout:
            self.logger.error("Timeout API OpenRouter (120s)")
            return None
        except Exception as e:
            self.logger.error("Exception appel API", exc=e)
            return None

    def _call_openrouter_text(self, text_content: str, prompt: str, page_num: int) -> Optional[str]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://skab-extractor.app",
            "X-Title": "SKAB Bank Statement Extractor",
        }

        payload = {
            "model": self._current_model,
            "messages": [
                {"role": "system", "content": "Tu es un expert comptable spécialisé dans les relevés bancaires camerounais."},
                {"role": "user", "content": f"{prompt}\n\nTexte à analyser:\n{text_content}"},
            ],
            "max_tokens": 8192,
            "temperature": 0.0,
            "top_p": 1.0,
        }

        model_display = self._get_model_display_name(self._current_model)
        self.logger.api(f"Appel OpenRouter texte [{model_display}] - Page {page_num}")

        try:
            response = requests.post(
                f"{OPENROUTER_API_BASE}/chat/completions",
                headers=headers,
                json=payload,
                timeout=120,
            )

            if response.status_code == 200:
                data = response.json()
                return data.get("choices", [{}])[0].get("message", {}).get("content", "")
            else:
                self.logger.error(f"Erreur API {response.status_code}", f"Détail: {response.text[:500]}")
                return None

        except Exception as e:
            self.logger.error("Exception appel API texte", exc=e)
            return None

    def _try_fallback(self, page_image=None, page_text=None, prompt: str = "", page_num: int = 1) -> Optional[str]:
        all_models = [self.model] + (self.fallback_models or [])
        tried_models = set()

        for model_id in all_models:
            if model_id in tried_models:
                continue
            tried_models.add(model_id)

            self._current_model = model_id
            model_display = self._get_model_display_name(model_id)
            self.logger.warning(f"Fallback vers {model_display}")

            is_vision = model_id in VISION_MODELS

            if is_vision and page_image:
                result = self._call_openrouter_vision(page_image, prompt, page_num)
            elif page_text:
                result = self._call_openrouter_text(page_text, prompt, page_num)
            else:
                self.logger.warning(f"Modèle {model_display} non applicable (pas d'image)")
                continue

            if result and len(result) > 50:
                self.logger.success(f"Fallback réussi avec {model_display}")
                return result

        self._current_model = self.model
        return None

    # ----------------------------------------------------------------
    # CONSTRUCTION DU PROMPT — VERSION TRÈS STRICTE
    # ----------------------------------------------------------------

    def _build_prompt(self, is_vision: bool = True) -> str:
        """Construit un prompt très strict pour capturer TOUTES les lignes."""
        c = self.config

        json_example = '''
{
  "transactions": [
    {
      "date": "JJ/MM/AAAA",
      "reference": "",
      "libelle": "description complète de l'opération",
      "date_valeur": "JJ/MM/AAAA",
      "debit": null,
      "credit": null,
      "solde": 0
    }
  ]
}
'''
        prompt = f"""Tu es un expert comptable très rigoureux spécialisé dans les relevés bancaires camerounais.

**MISSION CRITIQUE** : Tu dois extraire **ABSOLUMENT TOUTES** les lignes de transaction visibles sur l'image, y compris :
- La ligne d'ouverture (Opening Balance / Solde d'ouverture)
- Chaque ligne de transaction individuelle  
- La ligne de clôture (Closing Balance / Solde de clôture)

**Structure du relevé {c.nom}** :
{c.structure_description}

**Instructions spécifiques pour {c.nom}** :
{c.specific_instructions}

**RÈGLES STRICTES** :
1. La première ligne (Opening Balance / Solde d'ouverture) DOIT être extraite avec son solde
2. La dernière ligne (Closing Balance / Solde de clôture) DOIT être extraite avec son solde
3. Entre les deux, liste **CHAQUE** ligne une par une, du haut vers le bas
4. Ne JAMAIS sauter une ligne qui contient un montant en Débit, Crédit ou Solde
5. Si une description est sur plusieurs lignes, tu dois la fusionner COMPLÈTEMENT en une seule
6. Montants : retourne uniquement des chiffres sans séparateur (ex: 308000 au lieu de 308,000)
7. Le solde d'ouverture : mets le montant dans "credit" (c'est un solde créditeur) ou "debit" (si débiteur)
8. Retourne **uniquement** le JSON suivant, sans aucun commentaire :

{json_example}
"""
        return prompt

    # ----------------------------------------------------------------
    # EXTRACTION PRINCIPALE
    # ----------------------------------------------------------------

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
            self.logger.success(f"{len(images)} image(s) générée(s)")
        except Exception as e:
            self.logger.error("Échec conversion PDF", exc=e)
            return self._empty_df()

        prompt = self._build_prompt(is_vision=True)
        all_transactions = []

        for idx, image in enumerate(images, 1):
            self._update_progress(
                15 + int(70 * idx / len(images)),
                f"Analyse page {idx}/{len(images)}",
            )
            transactions = self._process_page_vision(image, idx, prompt)
            all_transactions.extend(transactions)

        return self._build_dataframe(all_transactions)

    def _process_page_vision(self, image: Image.Image, page_num: int, prompt: str) -> List[Dict]:
        optimized = self._optimize_image(image)
        img_base64 = self._image_to_base64(optimized)

        # Essai modèle principal avec retry
        for attempt in range(1, 4):
            self.logger.debug(f"Tentative {attempt}/3 - Page {page_num}")
            raw = self._call_openrouter_vision(img_base64, prompt, page_num)
            if raw and len(raw) > 50:
                parsed = self._parse_response(raw, f"page {page_num}")
                if parsed:
                    return parsed
            time.sleep(2)

        # Fallback
        self.logger.warning(f"Échec modèle principal page {page_num}, tentative fallback...")
        raw = self._try_fallback(
            page_image=img_base64,
            prompt=prompt,
            page_num=page_num,
        )
        if raw:
            return self._parse_response(raw, f"page {page_num} (fallback)")

        return []

    def _extract_hybrid(self, pdf_bytes: bytes) -> pd.DataFrame:
        self.logger.step("Mode hybride activé")

        try:
            import pdfplumber
            import io
            text_content = ""
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                for i, page in enumerate(pdf.pages):
                    text = page.extract_text() or ""
                    text_content += f"\n--- Page {i+1} ---\n{text}"
        except Exception:
            text_content = ""

        if text_content and len(text_content.strip()) > 100:
            self.logger.info("Texte extrait via pdfplumber, analyse IA...")
            return self._extract_text(text_content)

        self.logger.warning("Texte insuffisant, basculement vers mode vision")
        return self._extract_vision(pdf_bytes)

    def _extract_text(self, text_content: str) -> pd.DataFrame:
        prompt = self._build_prompt(is_vision=False)
        self.logger.step("Analyse du texte par l'IA")

        max_chars = 30000
        chunks = [text_content[i:i+max_chars] for i in range(0, len(text_content), max_chars)]

        all_transactions = []
        for i, chunk in enumerate(chunks):
            self._update_progress(30 + int(50 * i / len(chunks)), f"Analyse chunk {i+1}/{len(chunks)}")
            prompt_chunk = self._build_prompt(is_vision=False) + f"\n\n**Texte (partie {i+1}/{len(chunks)}) :**\n{chunk}"

            raw = None
            for attempt in range(1, 4):
                raw = self._call_openrouter_text(chunk, prompt_chunk, i+1)
                if raw and len(raw) > 50:
                    break
                time.sleep(2)

            if not raw:
                raw = self._try_fallback(page_text=chunk, prompt=prompt_chunk, page_num=i+1)

            if raw:
                transactions = self._parse_response(raw, f"chunk {i+1}")
                all_transactions.extend(transactions)

        return self._build_dataframe(all_transactions)

    # ----------------------------------------------------------------
    # TRAITEMENT D'IMAGE
    # ----------------------------------------------------------------

    def _optimize_image(self, image: Image.Image) -> Image.Image:
        if image.mode != "RGB":
            image = image.convert("RGB")
        if image.width > 2000:
            ratio = 2000 / image.width
            image = image.resize((2000, int(image.height * ratio)), Image.LANCZOS)
        return image

    def _image_to_base64(self, image: Image.Image) -> str:
        buffered = BytesIO()
        image.save(buffered, format="PNG", optimize=True)
        return base64.b64encode(buffered.getvalue()).decode("utf-8")

    # ----------------------------------------------------------------
    # PARSING DE LA RÉPONSE
    # ----------------------------------------------------------------

    def _parse_response(self, raw: str, context: str) -> List[Dict]:
        if not raw:
            return []

        text = re.sub(r"```(?:json)?\s*|\s*```", "", raw, flags=re.IGNORECASE).strip()

        # Essai 1 : JSON direct
        try:
            data = json.loads(text)
            transactions = data.get("transactions", [])
            if isinstance(transactions, list):
                parsed = [self._normalize(t) for t in transactions if self._normalize(t)]
                self.logger.success(f"{len(parsed)} transactions extraites ({context})")
                return parsed
        except json.JSONDecodeError:
            pass

        # Essai 2 : chercher un bloc JSON dans le texte
        json_match = re.search(r'\{[\s\S]*"transactions"[\s\S]*\}', text)
        if json_match:
            try:
                data = json.loads(json_match.group(0))
                transactions = data.get("transactions", [])
                if isinstance(transactions, list):
                    parsed = [self._normalize(t) for t in transactions if self._normalize(t)]
                    self.logger.success(f"{len(parsed)} transactions extraites après correction ({context})")
                    return parsed
            except json.JSONDecodeError:
                pass

        self.logger.error(f"Échec parsing JSON ({context})", f"Réponse: {raw[:300]}")
        return []

    def _normalize(self, t: Dict) -> Optional[Dict]:
        if not isinstance(t, dict):
            return None

        libelle = str(t.get("libelle", "") or t.get("libellé", "") or t.get("description", "") or "").strip()
        if not libelle or libelle.lower() in ("none", "null", ""):
            return None

        # Traitement spécial : "Opening Balance" ou "Solde d'ouverture"
        # → le montant du solde doit être mis dans 'credit' ou 'debit'
        debit = self._fmt_amount(t.get("debit") or t.get("débit"))
        credit = self._fmt_amount(t.get("credit") or t.get("crédit"))
        solde = self._fmt_amount(t.get("solde"))

        libelle_lower = libelle.lower()
        is_balance = any(kw in libelle_lower for kw in ["ouverture", "opening", "clôture", "cloture", "closing", "balance final"])

        # Si c'est une ligne de solde avec un solde mais sans débit/crédit
        if is_balance and solde is not None and debit is None and credit is None:
            if solde >= 0:
                credit = solde
            else:
                debit = abs(solde)

        return {
            "date": str(t.get("date", "")).strip()[:10],
            "reference": str(t.get("reference", "") or t.get("référence", "") or "").strip(),
            "libelle": libelle,
            "date_valeur": str(t.get("date_valeur", "") or t.get("date_valeur", "") or "").strip()[:10],
            "debit": debit,
            "credit": credit,
            "solde": solde,
        }

    def _fmt_amount(self, val) -> Optional[float]:
        """Convertit un montant en float. '0' est un montant valide, pas None."""
        if val is None:
            return None
        s = str(val).strip()
        if s.lower() in ("null", "none", ""):
            return None
        try:
            s = re.sub(r"[^\d.,-]", "", s)
            s = s.replace(",", ".")
            if s.count(".") > 1:
                s = s.replace(".", "")
            return float(s) if s else None
        except Exception:
            return None

    # ----------------------------------------------------------------
    # CONSTRUCTION DU DATAFRAME
    # ----------------------------------------------------------------

    def _build_dataframe(self, transactions: List[Dict]) -> pd.DataFrame:
        if not transactions:
            self.logger.warning("Aucune transaction extraite")
            return self._empty_df()

        df = pd.DataFrame([{
            "Date": t["date"],
            "Référence": t["reference"],
            "Libellé": t["libelle"],
            "Date_Valeur": t["date_valeur"],
            "Débit": t["debit"],
            "Crédit": t["credit"],
            "Solde": t["solde"],
        } for t in transactions])

        self.logger.success(f"DataFrame final: {len(df)} lignes")
        return df

    def _empty_df(self) -> pd.DataFrame:
        return pd.DataFrame(columns=["Date", "Référence", "Libellé", "Date_Valeur", "Débit", "Crédit", "Solde"])

    # ----------------------------------------------------------------
    # MÉTHODES PUBLIQUES
    # ----------------------------------------------------------------

    def get_debug_logs(self) -> str:
        return self.logger.get_logs_as_text()

    def get_debug_summary(self) -> dict:
        return self.logger.get_summary()

    def get_debug_entries(self) -> list:
        return self.logger.get_entries()

    def get_current_model(self) -> str:
        return self._get_model_display_name(self._current_model)
