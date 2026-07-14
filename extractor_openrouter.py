"""
extractor_openrouter.py - Version 1.0
Extraction des relevés bancaires via OpenRouter API
Support multi-modèles : GPT-4o, Claude 3.5 Sonnet, Gemini 2.0 Flash, DeepSeek V3
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
# Exemples de modèles disponibles :
#   "openai/gpt-4o"                    → OpenAI (payant)
#   "openai/gpt-4o-mini"               → OpenAI mini (peu coûteux)
#   "anthropic/claude-3.5-sonnet"      → Claude (payant)
#   "google/gemini-2.0-flash-exp:free" → Gemini gratuit
#   "deepseek/deepseek-chat"           → DeepSeek (peu coûteux)
#   "poolside/laguna-xs-2.1:free"      → Poolside gratuit
#   "meta-llama/llama-3.2-90b-vision"  → Llama gratuit
# ═══════════════════════════════════════════════════════════════
DEFAULT_MODEL = "tencent/hy3:free"

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
    "tencent/hy3:free",
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
        """
        Args:
            api_key: Clé API OpenRouter
            mode: "vision" ou "hybrid"
            banque_nom: Nom de la banque pour les instructions spécifiques
            model: Modèle OpenRouter à utiliser (ex: "openai/gpt-4o").
                   Si None, utilise DEFAULT_MODEL défini dans la config.
            fallback_models: Liste de modèles de fallback en cas d'échec.
                           Si None, utilise DEFAULT_FALLBACK_MODELS.
            progress_callback: Fonction de callback pour la progression
            verbose_debug: Activer les logs détaillés
        """
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
        """Retourne le nom d'affichage pour un model_id OpenRouter."""
        return model_id

    # ----------------------------------------------------------------
    # APPELS API OPENROUTER
    # ----------------------------------------------------------------

    def _call_openrouter_vision(self, image_base64: str, prompt: str, page_num: int) -> Optional[str]:
        """
        Appelle OpenRouter en mode vision avec une image encodée en base64.
        """
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
                self.logger.error(
                    f"Erreur API {response.status_code}",
                    f"Détail: {error_detail}",
                )
                return None

        except requests.exceptions.Timeout:
            self.logger.error("Timeout API OpenRouter (120s)")
            return None
        except Exception as e:
            self.logger.error("Exception appel API", exc=e)
            return None

    def _call_openrouter_text(self, text_content: str, prompt: str, page_num: int) -> Optional[str]:
        """
        Appelle OpenRouter en mode texte.
        """
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
                self.logger.error(
                    f"Erreur API {response.status_code}",
                    f"Détail: {response.text[:500]}",
                )
                return None

        except Exception as e:
            self.logger.error("Exception appel API texte", exc=e)
            return None

    def _try_fallback(self, page_image=None, page_text=None, prompt: str = "", page_num: int = 1) -> Optional[str]:
        """
        Essaie les modèles de fallback si le modèle principal échoue.
        """
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

        self._current_model = self.model  # Restaure le modèle initial
        return None

    # ----------------------------------------------------------------
    # CONSTRUCTION DU PROMPT
    # ----------------------------------------------------------------

    def _build_prompt(self, is_vision: bool = True) -> str:
        """Construit le prompt adapté à la banque sélectionnée."""
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

**MISSION CRITIQUE** : Extraire **TOUTES** les lignes de transaction visibles, **sans en sauter aucune**.

**Structure du relevé {c.nom}** :
{c.structure_description}

**Colonnes à extraire** :
1. Date (JJ/MM/AAAA)
2. Référence / N° de chèque
3. Libellé / Description de l'opération (peut être sur plusieurs lignes)
4. Date Valeur (si présente)
5. Débit (montant sortant)
6. Crédit (montant entrant)
7. Solde (balance après opération)

**Instructions spécifiques pour {c.nom}** :
{c.specific_instructions}

**RÈGLES NON NÉGOCIABLES** :
1. Liste chaque ligne de transaction une par une, du haut vers le bas
2. Ne JAMAIS sauter une ligne qui contient un montant
3. Si une description est sur plusieurs lignes, tu dois la fusionner en une seule
4. Montants : retourne uniquement des chiffres sans séparateur (ex: 308000 au lieu de 308,000)
5. Solde : inclus toujours le solde après chaque opération si présent
6. Retourne **uniquement** le JSON suivant, sans aucun commentaire :

{json_example}
"""
        return prompt

    # ----------------------------------------------------------------
    # EXTRACTION PRINCIPALE
    # ----------------------------------------------------------------

    def extract(self, pdf_bytes: bytes) -> pd.DataFrame:
        """Point d'entrée principal pour l'extraction."""
        self.logger.step(f"Début extraction {self.banque_nom} - Mode {self.mode}")

        if self.mode == "hybrid":
            return self._extract_hybrid(pdf_bytes)
        return self._extract_vision(pdf_bytes)

    def _extract_vision(self, pdf_bytes: bytes) -> pd.DataFrame:
        """Extraction via Vision API (analyse d'images)."""
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
                f"Analyse page {idx}/{len(images)} avec {self._get_model_display_name(self.model)}",
            )
            transactions = self._process_page_vision(image, idx, prompt)
            all_transactions.extend(transactions)

        return self._build_dataframe(all_transactions)

    def _process_page_vision(self, image: Image.Image, page_num: int, prompt: str) -> List[Dict]:
        """Traite une page en mode vision avec fallback."""
        optimized = self._optimize_image(image)
        img_base64 = self._image_to_base64(optimized)

        # Essai modèle principal
        for attempt in range(1, 4):
            self.logger.debug(f"Tentative {attempt}/3 - Page {page_num}")
            raw = self._call_openrouter_vision(img_base64, prompt, page_num)
            if raw and len(raw) > 50:
                return self._parse_response(raw, f"page {page_num}")
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
        """Mode hybride : essaie d'abord l'extraction texte, puis vision si nécessaire."""
        self.logger.step("Mode hybride activé")

        # Tentative extraction texte via pdfplumber
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
        """Extraction via analyse de texte."""
        prompt = self._build_prompt(is_vision=False)
        prompt += "\n\n**Format texte extrait du PDF :**\n"
        prompt += text_content

        self.logger.step("Analyse du texte par l'IA")

        # Diviser en chunks si trop long
        max_chars = 30000
        chunks = [text_content[i:i+max_chars] for i in range(0, len(text_content), max_chars)]

        all_transactions = []
        for i, chunk in enumerate(chunks):
            self._update_progress(30 + int(50 * i / len(chunks)), f"Analyse chunk {i+1}/{len(chunks)}")
            prompt_chunk = self._build_prompt(is_vision=False) + f"\n\n**Texte (partie {i+1}/{len(chunks)}) :**\n{chunk}"

            raw = None
            for attempt in range(1, 4):
                raw = self._call_openrouter_text(chunk, self._build_prompt(is_vision=False) + f"\n\n**Texte (partie {i+1}/{len(chunks)}) :**\n", i+1)
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
        """Optimise l'image pour l'analyse IA."""
        if image.mode != "RGB":
            image = image.convert("RGB")
        # Redimensionner si trop large (max 2000px)
        if image.width > 2000:
            ratio = 2000 / image.width
            image = image.resize((2000, int(image.height * ratio)), Image.LANCZOS)
        return image

    def _image_to_base64(self, image: Image.Image) -> str:
        """Convertit une image PIL en base64."""
        buffered = BytesIO()
        image.save(buffered, format="PNG", optimize=True)
        return base64.b64encode(buffered.getvalue()).decode("utf-8")

    # ----------------------------------------------------------------
    # PARSING DE LA RÉPONSE
    # ----------------------------------------------------------------

    def _parse_response(self, raw: str, context: str) -> List[Dict]:
        """Parse la réponse JSON de l'IA."""
        if not raw:
            return []

        # Nettoyer le markdown JSON
        text = re.sub(r"```(?:json)?\s*|\s*```", "", raw, flags=re.IGNORECASE).strip()

        # Essayer d'extraire un objet JSON valide
        try:
            data = json.loads(text)
            transactions = data.get("transactions", [])
            if not isinstance(transactions, list):
                self.logger.warning(f"Format inattendu ({context}) : transactions n'est pas une liste")
                return []
            parsed = [self._normalize(t) for t in transactions if self._normalize(t)]
            self.logger.success(f"{len(parsed)} transactions extraites ({context})")
            return parsed
        except json.JSONDecodeError:
            # Tentative de récupération : chercher un bloc JSON dans le texte
            json_match = re.search(r'\{[\s\S]*"transactions"[\s\S]*\}', text)
            if json_match:
                try:
                    data = json.loads(json_match.group(0))
                    transactions = data.get("transactions", [])
                    parsed = [self._normalize(t) for t in transactions if self._normalize(t)]
                    self.logger.success(f"{len(parsed)} transactions extraites après correction ({context})")
                    return parsed
                except json.JSONDecodeError:
                    pass

            self.logger.error(f"Échec parsing JSON ({context})", f"Réponse: {raw[:300]}")
            return []

    def _normalize(self, t: Dict) -> Optional[Dict]:
        """Normalise une transaction."""
        if not isinstance(t, dict):
            return None

        libelle = str(t.get("libelle", "") or t.get("libellé", "") or t.get("description", "") or "").strip()
        if not libelle or libelle.lower() in ("none", "null", ""):
            return None

        return {
            "date": str(t.get("date", "")).strip()[:10],
            "reference": str(t.get("reference", "") or t.get("référence", "") or "").strip(),
            "libelle": libelle,
            "date_valeur": str(t.get("date_valeur", "") or t.get("date_valeur", "") or "").strip()[:10],
            "debit": self._fmt_amount(t.get("debit") or t.get("débit")),
            "credit": self._fmt_amount(t.get("credit") or t.get("crédit")),
            "solde": self._fmt_amount(t.get("solde")),
        }

    def _fmt_amount(self, val) -> Optional[float]:
        """Formate un montant (format camerounais avec virgules)."""
        if val is None or str(val).lower() in ("null", "none", "", "0"):
            return None
        try:
            s = str(val).strip()
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
        """Construit le DataFrame final."""
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
