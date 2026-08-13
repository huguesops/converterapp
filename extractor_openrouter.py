"""
extractor_openrouter.py - Version 2.1
Extraction des relevés bancaires via OpenRouter API
Correction majeure : Ordre strict (numero_ligne trié par page), exclusion des en-têtes, pdfplumber layout=True
"""

import base64
import concurrent.futures
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

from bank_configs import get_bank_config, get_bank_list, BankConfig


# ====================== CONFIGURATION OPENROUTER ======================

OPENROUTER_API_BASE = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "google/gemini-3-flash-preview"

DEFAULT_FALLBACK_MODELS = [
    "qwen/qwen3-vl-235b-a22b-instruct",
    "anthropic/claude-sonnet-4.6",
]

VISION_MODELS = {
    "qwen/qwen3-vl-235b-a22b-instruct",
    "google/gemini-3-flash-preview",
    "anthropic/claude-sonnet-4.6",
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
        self.failed_pages: List[int] = []
        self.last_balance_hint: Optional[float] = None

    def _update_progress(self, step: int, msg: str):
        if self.progress_callback:
            self.progress_callback(step, msg)

    def _get_model_display_name(self, model_id: str) -> str:
        return model_id

    def _call_openrouter_vision(self, image_base64: str, prompt: str, page_num: int, model_id: Optional[str] = None) -> Optional[str]:
        model_id = model_id or self.model
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://skab-extractor.app",
            "X-Title": "SKAB Bank Statement Extractor",
        }

        payload = {
            "model": model_id,
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
            "max_tokens": 16000,
            "temperature": 0.0,
            "top_p": 1.0,
        }

        model_display = self._get_model_display_name(model_id)
        self.logger.api(f"Appel OpenRouter [{model_display}] - Page {page_num}")

        try:
            response = requests.post(
                f"{OPENROUTER_API_BASE}/chat/completions",
                headers=headers,
                json=payload,
                timeout=180,
            )

            if response.status_code == 200:
                data = response.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                return content
            elif response.status_code == 429:
                retry_after = response.headers.get("Retry-After")
                wait = float(retry_after) if retry_after else 5.0
                self.logger.warning(f"Rate limit (429) - Page {page_num}, attente {wait}s")
                time.sleep(min(wait, 15.0))
                return None
            else:
                self.logger.error(f"Erreur API {response.status_code}", f"Détail: {response.text[:500]}")
                return None
        except Exception as e:
            self.logger.error("Exception appel API", exc=e)
            return None

    def _call_openrouter_text(self, text_content: str, prompt: str, page_num: int, model_id: Optional[str] = None) -> Optional[str]:
        model_id = model_id or self.model
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://skab-extractor.app",
            "X-Title": "SKAB Bank Statement Extractor",
        }

        payload = {
            "model": model_id,
            "messages": [
                {"role": "system", "content": "Tu es un expert comptable spécialisé dans les relevés bancaires camerounais."},
                {"role": "user", "content": f"{prompt}\n\nTexte à analyser:\n{text_content}"},
            ],
            "max_tokens": 16000,
            "temperature": 0.0,
            "top_p": 1.0,
        }

        model_display = self._get_model_display_name(model_id)
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

            model_display = self._get_model_display_name(model_id)
            self.logger.warning(f"Fallback vers {model_display}")

            is_vision = model_id in VISION_MODELS

            if is_vision and page_image:
                result = self._call_openrouter_vision(page_image, prompt, page_num, model_id=model_id)
            elif page_text:
                result = self._call_openrouter_text(page_text, prompt, page_num, model_id=model_id)
            else:
                continue

            if result and len(result) > 50:
                self.logger.success(f"Fallback réussi avec {model_display}")
                return result

        return None

    def _build_prompt(self, is_vision: bool = True, previous_balance: Optional[float] = None) -> str:
        c = self.config

        json_example = '''
{
  "transactions": [
    {
      "numero_ligne": 1,
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
        continuity_hint = ""
        if previous_balance is not None:
            continuity_hint = f"""
**POINT DE CONTRÔLE (continuité avec la page précédente)** :
Le solde de la dernière transaction lue sur la page précédente était de {previous_balance:,.2f} FCFA. 
Utilise ce solde pour lever toute ambiguïté, mais N'INVENTE PAS de transaction.
"""

        prompt = f"""Tu es un expert comptable très rigoureux spécialisé dans les relevés bancaires camerounais.

**MISSION CRITIQUE** : Tu dois extraire **ABSOLUMENT TOUTES** les lignes de transaction visibles **UNIQUEMENT DANS LE TABLEAU PRINCIPAL** (la zone avec les colonnes Date, Libellé, Débit, Crédit, Solde).

**RÈGLES STRICTES ET IMPÉRATIVES** :
1. **IGNORE L'EN-TÊTE (TRÈS IMPORTANT)** : Ne lis JAMAIS le bloc de résumé général en haut de la page (qui mentionne par exemple "Total des débits", "Total des crédits", "Solde à l'ouverture" HORS du grand tableau, ou "Solde de clôture" HORS du tableau). Ton extraction doit commencer STRICTEMENT à la première ligne de données à l'intérieur du grand tableau des opérations.
2. **Ordre et Numérotation** : Tu dois OBLIGATOIREMENT assigner un `numero_ligne` séquentiel (1, 2, 3...) à chaque transaction extraite. La ligne TOUT EN HAUT du tableau doit être la numéro 1. La suivante juste en dessous est la 2, et ainsi de suite jusqu'à la dernière ligne tout en bas.
3. **Chronologie visuelle** : L'ordre des transactions dans ton JSON DOIT correspondre EXACTEMENT à la lecture de haut en bas du tableau. Ne mélange pas les lignes, ne les inverse jamais de bas en haut.
4. **Exhaustivité** : Ne JAMAIS sauter une ligne du tableau qui contient un montant en Débit, Crédit ou Solde. Si une description s'étale sur plusieurs lignes, fusionne-la COMPLÈTEMENT.
5. **Soldes d'ouverture/clôture du tableau** : Si le tableau des opérations commence ou se termine par une ligne "Report", "Solde d'ouverture" ou "Solde de clôture" insérée COMME UNE LIGNE DU TABLEAU, mets son montant UNIQUEMENT dans le champ "solde" (laisse "debit" et "credit" à null).
6. **Format des montants** : Retourne uniquement des chiffres sans séparateur de milliers (ex: 308000 au lieu de 308,000). Utilise le point comme séparateur décimal (ex: 308000.50).

**Structure du relevé {c.nom}** :
{c.structure_description}

**Instructions spécifiques pour {c.nom}** :
{c.specific_instructions}
{continuity_hint}
Retourne **uniquement** le JSON suivant, sans aucun commentaire :
{json_example}
"""
        return prompt

    def extract(self, pdf_bytes: bytes) -> pd.DataFrame:
        self.logger.step(f"Début extraction {self.banque_nom} - Mode {self.mode}")
        if self.mode == "hybrid":
            return self._extract_hybrid(pdf_bytes)
        return self._extract_vision(pdf_bytes)

    def get_total_pages(self, pdf_bytes: bytes) -> int:
        try:
            from pdf2image.pdf2image import pdfinfo_from_bytes
            info = pdfinfo_from_bytes(pdf_bytes)
            return int(info.get("Pages", 0))
        except Exception as e:
            self.logger.error("Échec lecture info PDF", exc=e)
            return 0

    def detect_bank(self, pdf_bytes: bytes) -> Optional[str]:
        if not PDF2IMAGE_AVAILABLE:
            return None
        bank_list = get_bank_list()
        try:
            page_images = convert_from_bytes(pdf_bytes, dpi=150, fmt="PNG", first_page=1, last_page=1)
            if not page_images:
                return None
            image = self._optimize_image(page_images[0])
            img_base64 = self._image_to_base64(image)
        except Exception:
            return None

        options_str = "\n".join(f"- {b}" for b in bank_list)
        prompt = f"Identifie la banque PARMI CETTE LISTE EXACTE :\n{options_str}\nRéponds UNIQUEMENT le nom, ou INCONNU."
        try:
            raw = self._call_openrouter_vision(img_base64, prompt, page_num=1)
        except Exception:
            return None

        if not raw or raw.strip().upper() == "INCONNU":
            return None

        for b in bank_list:
            if raw.strip().lower() == b.lower():
                return b
        for b in bank_list:
            if b.lower() in raw.lower():
                return b
        return None

    def _dpi_for(self, total_pages: int) -> int:
        return 250

    MAX_PARALLEL_PAGES = 4

    def _extract_pages_parallel(
        self, pdf_bytes: bytes, pages: List[int], total_pages: int,
        starting_balance: Optional[float], progress_label: str,
    ) -> List[Dict]:
        if not PDF2IMAGE_AVAILABLE:
            return []

        dpi = self._dpi_for(total_pages)
        results: Dict[int, List[Dict]] = {}

        def process_one(idx: int) -> tuple:
            self._update_progress(
                int(100 * idx / max(total_pages, 1)),
                f"{progress_label} page {idx}/{total_pages}",
            )
            try:
                page_images = convert_from_bytes(
                    pdf_bytes, dpi=dpi, fmt="PNG",
                    first_page=idx, last_page=idx,
                )
                if not page_images:
                    self.failed_pages.append(idx)
                    return idx, []
                image = page_images[0]
            except Exception as e:
                self.logger.error(f"Échec conversion page {idx}", exc=e)
                self.failed_pages.append(idx)
                return idx, []

            prompt = self._build_prompt(is_vision=True, previous_balance=starting_balance)
            transactions = self._process_page_vision(image, idx, total_pages, prompt)
            del image, page_images
            return idx, transactions

        with concurrent.futures.ThreadPoolExecutor(max_workers=self.MAX_PARALLEL_PAGES) as executor:
            futures = [executor.submit(process_one, idx) for idx in pages]
            for future in concurrent.futures.as_completed(futures):
                idx, transactions = future.result()
                results[idx] = transactions

        all_transactions: List[Dict] = []
        current_balance = starting_balance
        for idx in pages: 
            transactions = results.get(idx, [])
            all_transactions.extend(transactions)
            if transactions:
                last_solde = transactions[-1].get("solde")
                if isinstance(last_solde, (int, float)):
                    current_balance = last_solde

        self.last_balance_hint = current_balance
        return all_transactions

    def extract_transactions(
        self, pdf_bytes: bytes, first_page: int, last_page: int, total_pages: int,
        starting_balance: Optional[float] = None,
    ) -> List[Dict]:
        pages = list(range(first_page, last_page + 1))
        return self._extract_pages_parallel(pdf_bytes, pages, total_pages, starting_balance, "Analyse")

    def extract_specific_pages(
        self, pdf_bytes: bytes, pages: List[int], total_pages: int,
        starting_balance: Optional[float] = None,
    ) -> List[Dict]:
        return self._extract_pages_parallel(pdf_bytes, pages, total_pages, starting_balance, "Nouvel essai —")

    def extract_page_range(self, pdf_bytes: bytes, first_page: int, last_page: int, total_pages: int) -> pd.DataFrame:
        return self.build_dataframe(
            self.extract_transactions(pdf_bytes, first_page, last_page, total_pages)
        )

    def build_dataframe(self, transactions: List[Dict]) -> pd.DataFrame:
        return self._build_dataframe(transactions)

    def _extract_vision(self, pdf_bytes: bytes) -> pd.DataFrame:
        if not PDF2IMAGE_AVAILABLE:
            return self._empty_df()
        total_pages = self.get_total_pages(pdf_bytes)
        if total_pages <= 0:
            return self._empty_df()
        return self.extract_page_range(pdf_bytes, 1, total_pages, total_pages)

    def _process_page_vision(self, image: Image.Image, page_num: int, total_pages: int, prompt: str) -> List[Dict]:
        optimized = self._optimize_image(image)
        img_base64 = self._image_to_base64(optimized)

        for attempt in range(1, 4):
            self.logger.debug(f"Tentative {attempt}/3 - Page {page_num}")
            self._update_progress(
                15 + int(70 * page_num / total_pages),
                f"Analyse page {page_num}/{total_pages} (tentative {attempt}/3)",
            )
            raw = self._call_openrouter_vision(img_base64, prompt, page_num)
            if raw and len(raw) > 50:
                parsed = self._parse_response(raw, f"page {page_num}")
                if parsed:
                    # TRI STRICT DE LA PAGE : respecte l'ordre visuel 1, 2, 3.. donné par le LLM
                    parsed = sorted(parsed, key=lambda x: x.get("numero_ligne", 0))
                    return parsed
            time.sleep(2)

        raw = self._try_fallback(page_image=img_base64, prompt=prompt, page_num=page_num)
        if raw:
            parsed = self._parse_response(raw, f"page {page_num} (fallback)")
            if parsed:
                parsed = sorted(parsed, key=lambda x: x.get("numero_ligne", 0))
                return parsed

        self.failed_pages.append(page_num)
        return []

    def _extract_hybrid(self, pdf_bytes: bytes) -> pd.DataFrame:
        self.logger.step("Mode hybride activé")

        try:
            import pdfplumber
            import io
            text_content = ""
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                for i, page in enumerate(pdf.pages):
                    # layout=True : INDISPENSABLE pour que pdfplumber aligne visuellement 
                    # le texte au lieu de recracher les colonnes en désordre.
                    try:
                        text = page.extract_text(layout=True) or page.extract_text() or ""
                    except Exception:
                        text = page.extract_text() or ""
                    text_content += f"\n--- Page {i+1} ---\n{text}"
        except Exception:
            text_content = ""

        if text_content and len(text_content.strip()) > 100:
            return self._extract_text(text_content)

        return self._extract_vision(pdf_bytes)

    def _extract_text(self, text_content: str) -> pd.DataFrame:
        prompt = self._build_prompt(is_vision=False)
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
                if transactions:
                    transactions = sorted(transactions, key=lambda x: x.get("numero_ligne", 0))
                    all_transactions.extend(transactions)

        return self._build_dataframe(all_transactions)

    def _optimize_image(self, image: Image.Image) -> Image.Image:
        if image.mode != "RGB":
            image = image.convert("RGB")
        if image.width > 2400:
            ratio = 2400 / image.width
            image = image.resize((2400, int(image.height * ratio)), Image.LANCZOS)
        return image

    def _image_to_base64(self, image: Image.Image) -> str:
        buffered = BytesIO()
        image.save(buffered, format="PNG", optimize=True)
        return base64.b64encode(buffered.getvalue()).decode("utf-8")

    def _parse_response(self, raw: str, context: str) -> List[Dict]:
        if not raw:
            return []

        text = re.sub(r"```(?:json)?\s*|\s*```", "", raw, flags=re.IGNORECASE).strip()

        parsed = []
        try:
            data = json.loads(text)
            transactions = data.get("transactions", [])
            if isinstance(transactions, list):
                parsed = [t for t in (self._normalize(t) for t in transactions) if t]
        except json.JSONDecodeError:
            json_match = re.search(r'\{[\s\S]*"transactions"[\s\S]*\}', text)
            if json_match:
                try:
                    data = json.loads(json_match.group(0))
                    transactions = data.get("transactions", [])
                    if isinstance(transactions, list):
                        parsed = [t for t in (self._normalize(t) for t in transactions) if t]
                except json.JSONDecodeError:
                    pass

        if parsed:
            return parsed

        return []

    def _normalize(self, t: Dict) -> Optional[Dict]:
        if not isinstance(t, dict):
            return None

        libelle = str(t.get("libelle", "") or t.get("libellé", "") or t.get("description", "") or "").strip()
        if not libelle or libelle.lower() in ("none", "null", ""):
            return None

        debit = self._fmt_amount(t.get("debit") or t.get("débit"))
        credit = self._fmt_amount(t.get("credit") or t.get("crédit"))
        solde = self._fmt_amount(t.get("solde"))
        
        try:
            num = int(t.get("numero_ligne", 0) or 0)
        except:
            num = 0

        libelle_lower = libelle.lower()
        is_balance = any(
            kw in libelle_lower for kw in [
                "ouverture", "opening", "clôture", "cloture", "closing",
                "balance final", "début", "debut", "solde initial",
                "solde final", "solde antérieur", "solde anterieur",
            ]
        ) or bool(re.search(r"solde\s+au\s+\d", libelle_lower))

        if is_balance and solde is not None and debit is None and credit is None:
            if solde >= 0:
                credit = solde
            else:
                debit = abs(solde)

        return {
            "numero_ligne": num,
            "date": str(t.get("date", "")).strip()[:10],
            "reference": str(t.get("reference", "") or t.get("référence", "") or "").strip(),
            "libelle": libelle,
            "date_valeur": str(t.get("date_valeur", "") or t.get("date_valeur", "") or "").strip()[:10],
            "debit": debit,
            "credit": credit,
            "solde": solde,
        }

    def _fmt_amount(self, val) -> Optional[float]:
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

    def _build_dataframe(self, transactions: List[Dict]) -> pd.DataFrame:
        if not transactions:
            return self._empty_df()

        df = pd.DataFrame([{
            "Numero_Ligne": t.get("numero_ligne", 0),
            "Date": t["date"],
            "Référence": t["reference"],
            "Libellé": t["libelle"],
            "Date_Valeur": t["date_valeur"],
            "Débit": t["debit"],
            "Crédit": t["credit"],
            "Solde": t["solde"],
        } for t in transactions])

        return df

    def _empty_df(self) -> pd.DataFrame:
        return pd.DataFrame(columns=["Numero_Ligne", "Date", "Référence", "Libellé", "Date_Valeur", "Débit", "Crédit", "Solde"])

    def get_debug_logs(self) -> str:
        return self.logger.get_logs_as_text()

    def get_debug_summary(self) -> dict:
        return self.logger.get_summary()

    def get_debug_entries(self) -> list:
        return self.logger.get_entries()

    def get_current_model(self) -> str:
        return self._get_model_display_name(self._current_model)
