"""
Parser auto_agent_v1 — Pipeline en cascade (HTML → Deep Fetch → PDF → LLM Mistral).

Ce parser tente d'extraire les élus municipaux d'une page web en 4 niveaux
de profondeur croissante. Le LLM n'est appelé qu'en DERNIER RECOURS.
"""

import io
import json
import logging
import os
import re
import urllib.parse
from typing import List, Optional, Tuple

import aiohttp
from bs4 import BeautifulSoup

from ..base import BaseParser
from ..factory import ParserFactory

logger = logging.getLogger(__name__)

# ───────────────────────────────────────────────────────────────────────
# Regex réutilisées depuis generic_html_v1 (source de vérité unique)
# ───────────────────────────────────────────────────────────────────────

_ANCHOR_RE = re.compile(r'\b(maire|adjoint|conseill)', re.IGNORECASE)

# Filtre prépositionnel : "maire" précédé de ces prépositions = complément, pas titre
_PREP_MAIRE_RE = re.compile(
    r'\b(?:du|au|de la|[aà] la|par le|par la|aupr[eè]s du|aupr[eè]s de la|'
    r'd[eé]l[eé]gation du|pr[eé]sence du|convocation du)\s+maire\b',
    re.IGNORECASE
)

_UP = "A-ZÉÈÊËÀÂÎÏÔÙÛÜÇÑ"
_LO = "a-zéèêëàâîïôùûüçñ"

# Prénom NOM (NOM tout en majuscules)
_NAME_PRENOM_NOM_RE = re.compile(
    rf'(?:(?:M\.|Mme|M|Monsieur|Madame)\s+)?'
    rf'([{_UP}][{_LO}]+(?:[\s-][{_UP}][{_LO}]+)*)'
    rf'\s+'
    rf'([{_UP}]{{2,}}(?:[\s-][{_UP}]{{2,}})*)',
    re.UNICODE,
)

# Prénom Nom (Title Case)
_NAME_TITLE_RE = re.compile(
    rf'(?:(?:M\.|Mme|M|Monsieur|Madame)\s+)?'
    rf'([{_UP}][{_LO}]+(?:[\s-][{_UP}][{_LO}]+)*)'
    rf'\s+'
    rf'([{_UP}][{_LO}]+(?:[\s-][{_UP}][{_LO}]+)*)',
    re.UNICODE,
)

# Anti faux-positifs
_NAME_BLACKLIST = frozenset({
    "MAIRE", "ADJOINT", "ADJOINTE", "CONSEILLER", "CONSEILLERE", "MUNICIPAL",
    "MUNICIPALE", "VILLE", "COMMUNE", "MAIRIE", "DELEGUE", "DELEGUEE",
    "BUDGET", "MARCHES", "PUBLICS", "INTERCOMMUNALITE", "RECRUTEMENT",
    "DELIBERATIONS", "NOUVELLE", "CONSEIL", "ACCUEIL",
    "URBANISME", "PATRIMOINE", "CULTURE", "EDUCATION", "JEUNESSE",
    "ENFANCE", "SPORTS", "SECURITE", "SERVICES", "COMMUNICATION",
    "HOTEL", "CEDEX", "PARIS", "FRANCE", "MONSIEUR", "MADAME",
    "TYPE", "MANDAT", "DELEGATION", "ARRONDISSEMENT", "SECTEUR",
    "CONTACT", "INFOS", "PRATIQUES", "MENU",
})

# Mots-clés pour détecter les sous-pages pertinentes
_DEEP_KEYWORDS = [
    "elu", "elus", "trombinoscope", "equipe",
    "conseil-municipal", "adjoints", "organigramme",
]

_MIN_BLOCK_LENGTH = 10


@ParserFactory.register("auto_agent_v1")
class AutoAgentV1Parser(BaseParser):
    """Parser intelligent en cascade : HTML → Deep Fetch → PDF → LLM Mistral."""

    def __init__(self, url: str, ville_ou_secteur: str):
        super().__init__(url, ville_ou_secteur)
        self._extracted_results: List[dict] = []

    # ─────────────────────────────────────────────────────
    # Point d'entrée — fetch() pipeline en 4 niveaux
    # ─────────────────────────────────────────────────────

    async def fetch(self, session: aiohttp.ClientSession) -> Optional[str]:
        """Pipeline en cascade. Passe au niveau suivant seulement si le précédent échoue."""

        # ── Niveau 1 — HTML Direct ──
        try:
            html = await super().fetch(session)
            if html:
                results = self._try_extract_html(html)
                if results:
                    logger.info(
                        f"✅ Niveau 1 (HTML direct) : {len(results)} élus pour {self.ville_ou_secteur}"
                    )
                    self._extracted_results = results
                    return html
        except Exception as e:
            logger.warning(f"⚠️ Niveau 1 échoué pour {self.url}: {e}")

        # ── Niveau 2 — Deep Fetch sous-page ──
        try:
            deep_html = await self._deep_fetch_subpage(session)
            if deep_html:
                return deep_html
        except Exception as e:
            logger.warning(f"⚠️ Niveau 2 échoué pour {self.url}: {e}")

        # ── Niveau 3 — PDF ──
        try:
            pdf_text = await self._try_pdf_extraction(session)
            if pdf_text:
                return self.html_content  # on retourne le HTML d'origine (ou sous-page)
        except Exception as e:
            logger.warning(f"⚠️ Niveau 3 (PDF) échoué pour {self.url}: {e}")

        # ── Niveau 4 — LLM Mistral (dernier recours) ──
        try:
            llm_results = await self._try_llm_extraction()
            if llm_results:
                return self.html_content
        except Exception as e:
            logger.warning(f"⚠️ Niveau 4 (LLM) échoué pour {self.url}: {e}")

        logger.error(f"❌ Aucun niveau n'a produit de résultats pour {self.ville_ou_secteur} ({self.url})")
        return self.html_content

    # ─────────────────────────────────────────────────────
    # extract() — méthode abstraite de BaseParser
    # ─────────────────────────────────────────────────────

    def extract(self) -> List[dict]:
        """Retourne les résultats déjà extraits par fetch()."""
        return self._extracted_results if self._extracted_results else []

    # ─────────────────────────────────────────────────────
    # Niveau 2 — Deep Fetch sous-page
    # ─────────────────────────────────────────────────────

    async def _deep_fetch_subpage(self, session: aiohttp.ClientSession) -> Optional[str]:
        """Scanne les liens de la page à la recherche de sous-pages d'élus."""
        if not self.html_content:
            return None

        candidates = self._find_subpage_links(self.html_content)
        logger.info(
            f"🔍 Niveau 2 : {len(candidates)} lien(s) candidat(s) pour {self.ville_ou_secteur}"
        )

        for link_url in candidates[:3]:
            try:
                async with session.get(
                    link_url, ssl=False, timeout=aiohttp.ClientTimeout(total=15)
                ) as resp:
                    if resp.status != 200:
                        continue
                    sub_html = await resp.text()

                results = self._try_extract_html(sub_html)
                if results:
                    logger.info(
                        f"✅ Niveau 2 : {len(results)} élus trouvés sur {link_url}"
                    )
                    self._extracted_results = results
                    self.url = link_url
                    self.html_content = sub_html
                    return sub_html
            except Exception as e:
                logger.warning(f"  ❌ Erreur deep fetch sur {link_url}: {e}")

        return None

    def _find_subpage_links(self, html: str) -> List[str]:
        """Retourne les URLs de sous-pages pertinentes triées par score."""
        soup = BeautifulSoup(html, "html.parser")
        scored: List[Tuple[str, int]] = []

        for a_tag in soup.find_all("a", href=True):
            href = a_tag.get("href", "").strip()
            text = a_tag.get_text(strip=True)

            if not href or href.startswith("#") or href.startswith("mailto:") or href.startswith("tel:"):
                continue

            combined = (href + " " + text).lower()

            if any(kw in combined for kw in _DEEP_KEYWORDS):
                full_url = self._resolve_url(href)
                if full_url and full_url.rstrip("/") != self.url.rstrip("/"):
                    score = sum(2 for kw in _DEEP_KEYWORDS if kw in combined)
                    scored.append((full_url, score))

        # Tri décroissant par score
        scored.sort(key=lambda x: -x[1])
        # Dédoublonnage
        seen = set()
        unique = []
        for url, _ in scored:
            if url not in seen:
                seen.add(url)
                unique.append(url)
        return unique

    def _resolve_url(self, href: str) -> Optional[str]:
        """Convertit un href relatif en URL absolue."""
        if href.startswith("http"):
            return href
        parsed_base = urllib.parse.urlparse(self.url)
        base = f"{parsed_base.scheme}://{parsed_base.netloc}"
        if href.startswith("/"):
            return base + href
        base_path = parsed_base.path.rstrip("/")
        return base + base_path + "/" + href

    # ─────────────────────────────────────────────────────
    # Niveau 3 — Extraction PDF
    # ─────────────────────────────────────────────────────

    async def _try_pdf_extraction(self, session: aiohttp.ClientSession) -> Optional[str]:
        """Cherche et parse les PDFs liés depuis la page courante."""
        if not self.html_content:
            return None

        pdf_urls = self._find_pdf_links(self.html_content)
        if not pdf_urls:
            return None

        logger.info(f"📄 Niveau 3 : {len(pdf_urls)} PDF(s) trouvé(s) pour {self.ville_ou_secteur}")

        for pdf_url in pdf_urls[:3]:
            try:
                async with session.get(
                    pdf_url, ssl=False, timeout=aiohttp.ClientTimeout(total=30)
                ) as resp:
                    if resp.status != 200:
                        continue
                    pdf_bytes = await resp.read()

                text = self._extract_text_from_pdf(pdf_bytes)
                if not text:
                    continue

                results = self._try_extract_from_text(text)
                if results:
                    logger.info(
                        f"✅ Niveau 3 (PDF) : {len(results)} élus extraits de {pdf_url}"
                    )
                    self._extracted_results = results
                    return text
            except Exception as e:
                logger.warning(f"  ❌ Erreur PDF sur {pdf_url}: {e}")

        return None

    def _find_pdf_links(self, html: str) -> List[str]:
        """Scanne les liens <a href="...pdf"> de la page."""
        soup = BeautifulSoup(html, "html.parser")
        pdf_urls = []

        for a_tag in soup.find_all("a", href=True):
            href = a_tag.get("href", "").strip().lower()
            if href.endswith(".pdf"):
                full_url = self._resolve_url(a_tag.get("href", "").strip())
                if full_url:
                    pdf_urls.append(full_url)

        return pdf_urls

    @staticmethod
    def _extract_text_from_pdf(pdf_bytes: bytes) -> Optional[str]:
        """Extrait le texte complet d'un PDF en mémoire via pdfplumber."""
        try:
            import pdfplumber

            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                pages_text = []
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        pages_text.append(page_text)
                return "\n".join(pages_text) if pages_text else None
        except Exception as e:
            logger.warning(f"Erreur extraction PDF: {e}")
            return None

    # ─────────────────────────────────────────────────────
    # Niveau 4 — LLM Mistral (dernier recours)
    # ─────────────────────────────────────────────────────

    async def _try_llm_extraction(self) -> Optional[List[dict]]:
        """Appelle Mistral comme dernier recours si tous les autres niveaux ont échoué."""
        api_key = os.environ.get("MISTRAL_API_KEY")
        if not api_key:
            logger.warning("⚠️ MISTRAL_API_KEY non définie, Niveau 4 ignoré.")
            return None

        if not self.html_content:
            return None

        logger.info(f"🤖 LLM Mistral activé pour {self.url}")

        # Nettoyage du HTML pour réduire les tokens
        cleaned_text = self._clean_html_for_llm(self.html_content)
        if not cleaned_text or len(cleaned_text.strip()) < 50:
            logger.warning("Contenu trop court après nettoyage pour le LLM.")
            return None

        try:
            from mistralai import Mistral

            client = Mistral(api_key=api_key)

            system_prompt = (
                "Tu es un extracteur de données JSON. "
                "Réponds UNIQUEMENT avec un tableau JSON valide, sans markdown, sans explication."
            )
            user_prompt = (
                "Voici le contenu d'une page web d'une mairie française. "
                "Extrais la liste des élus municipaux au format JSON strict : "
                '[{"nom": "DUPONT", "prenom": "Jean", "fonction": "Adjoint au maire"}]. '
                f"Contenu : {cleaned_text}"
            )

            response = client.chat.complete(
                model="mistral-small-latest",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )

            raw_response = response.choices[0].message.content.strip()

            # Nettoyage de la réponse (certains modèles ajoutent ```json ... ```)
            if raw_response.startswith("```"):
                raw_response = re.sub(r'^```(?:json)?\s*', '', raw_response)
                raw_response = re.sub(r'\s*```$', '', raw_response)

            results = json.loads(raw_response)

            if isinstance(results, list) and len(results) > 0:
                # Validation minimale de la structure
                validated = []
                for item in results:
                    if isinstance(item, dict) and ("nom" in item or "prenom" in item):
                        validated.append({
                            "nom": str(item.get("nom", "")).strip(),
                            "prenom": str(item.get("prenom", "")).strip(),
                            "fonction": str(item.get("fonction", "")).strip(),
                        })
                if validated:
                    logger.info(
                        f"✅ Niveau 4 (LLM) : {len(validated)} élus extraits pour {self.ville_ou_secteur}"
                    )
                    self._extracted_results = validated
                    return validated

        except json.JSONDecodeError as e:
            logger.error(f"❌ Erreur parsing JSON de la réponse LLM pour {self.url}: {e}")
        except Exception as e:
            logger.error(f"❌ Erreur LLM Mistral pour {self.url}: {e}")

        return None

    @staticmethod
    def _clean_html_for_llm(html: str) -> str:
        """Nettoie le HTML et tronque à 12 000 caractères pour limiter les tokens."""
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        text = soup.get_text(separator=" ", strip=True)
        # Collapse des espaces multiples
        text = re.sub(r'\s+', ' ', text)
        return text[:12_000]

    # ─────────────────────────────────────────────────────
    # Méthodes d'extraction réutilisables
    # ─────────────────────────────────────────────────────

    def _try_extract_html(self, html: str) -> List[dict]:
        """Extraction HTML via BeautifulSoup + regex sémantiques (même logique que generic_html_v1)."""
        if not html:
            return []

        soup = BeautifulSoup(html, "html.parser")

        # Nettoyage du bruit
        for el in soup(["script", "style", "nav", "footer", "header", "menu",
                         "aside", "iframe", "noscript", "svg"]):
            el.extract()

        results: List[dict] = []
        seen: set = set()

        # Stratégie 1 : Conteneurs structurels
        containers = soup.select(
            'tr, li, [class*="item"], [class*="elu"], [class*="member"], '
            '[class*="person"], [class*="team"], article'
        )
        for container in containers:
            try:
                text = self._clean_text(container.get_text(separator=" ", strip=True))
                if (not text or len(text) < _MIN_BLOCK_LENGTH
                        or len(text) > 500 or not _ANCHOR_RE.search(text)):
                    continue
                pairs = self._extract_pairs_from_text(text)
                for prenom, nom, fonction in pairs:
                    self._add_result(results, seen, prenom, nom, fonction)
            except Exception:
                continue

        # Stratégie 2 : Blocs de texte individuels
        if soup.body:
            for tag in soup.body.descendants:
                try:
                    if not tag.name or tag.name in ("html", "body", "head"):
                        continue
                    text = self._clean_text(tag.get_text(separator=" ", strip=True))
                    if (not text or len(text) < _MIN_BLOCK_LENGTH
                            or len(text) > 500 or not _ANCHOR_RE.search(text)):
                        continue
                    pairs = self._extract_pairs_from_text(text)
                    for prenom, nom, fonction in pairs:
                        self._add_result(results, seen, prenom, nom, fonction)
                except Exception:
                    continue

        return results

    def _try_extract_from_text(self, text: str) -> List[dict]:
        """Extraction depuis du texte brut (PDF, etc.) via les mêmes regex."""
        if not text:
            return []

        results: List[dict] = []
        seen: set = set()

        # Découpe en lignes pour un scan plus fin
        lines = text.split("\n")
        for line in lines:
            line = line.strip()
            if len(line) < _MIN_BLOCK_LENGTH or not _ANCHOR_RE.search(line):
                continue
            pairs = self._extract_pairs_from_text(line)
            for prenom, nom, fonction in pairs:
                self._add_result(results, seen, prenom, nom, fonction)

        # Si le scan ligne par ligne ne donne rien, tenter sur le texte complet
        if not results and _ANCHOR_RE.search(text):
            # Découpe en paragraphes (doubles sauts de ligne)
            paragraphs = re.split(r'\n{2,}', text)
            for para in paragraphs:
                para = para.strip()
                if len(para) < _MIN_BLOCK_LENGTH or not _ANCHOR_RE.search(para):
                    continue
                pairs = self._extract_pairs_from_text(para)
                for prenom, nom, fonction in pairs:
                    self._add_result(results, seen, prenom, nom, fonction)

        return results

    # ─────────────────────────────────────────────────────
    # Utilitaires d'extraction (miroir de generic_html_v1)
    # ─────────────────────────────────────────────────────

    def _extract_pairs_from_text(self, text: str) -> List[Tuple[str, str, str]]:
        """Extrait les triplets (prenom, nom, fonction) d'un bloc de texte."""
        pairs = []
        fonction = self._extract_fonction(text)
        if not fonction:
            return pairs

        names = self._extract_names(text)
        if names:
            for prenom, nom in names:
                pairs.append((prenom, nom, fonction))
        else:
            # Fallback : on garde le texte brut tronqué
            pairs.append(("", text.strip()[:100], fonction))
        return pairs

    @staticmethod
    def _extract_fonction(text: str) -> Optional[str]:
        """Extrait la fonction en ciblant le titre fonctionnel, pas la description.

        Aligné sur generic_html_v1._extract_fonction() (source de vérité).
        """
        # 1. Nettoyage du bruit : adresses e-mail
        text_clean = re.sub(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b.*$', '', text).strip()

        # 2. Tronquer au premier chiffre long (téléphone, etc.)
        text_clean = re.sub(r'\s+\d[\d\s\.]{5,}.*$', '', text_clean).strip()

        # 3. Tronquer à la première virgule ou point-virgule
        text_clean = re.split(r'[,;]', text_clean)[0].strip()

        # 4. Nettoyage final des résidus de ponctuation
        text_clean = text_clean.rstrip(".-: ")

        # 5. Limiter à 60 caractères max avec ancre sémantique
        if len(text_clean) > 60:
            pattern = re.compile(
                r'(.{0,30}\b(?:maire|adjoint|conseill)\w*(?:\s+\w+){0,6})',
                re.IGNORECASE
            )
            match = pattern.search(text_clean)
            if match:
                candidate = match.group(1).strip()
            else:
                return None
        else:
            if not _ANCHOR_RE.search(text_clean):
                return None
            candidate = text_clean

        # 6. Filtre prépositionnel : "maire" précédé de du/au/auprès du = complément
        if candidate and _PREP_MAIRE_RE.search(candidate):
            other_match = re.search(r'\b(?:adjoint|conseill)', candidate, re.IGNORECASE)
            maire_match = re.search(r'\bmaire\b', candidate, re.IGNORECASE)
            if not other_match or (maire_match and other_match.start() > maire_match.start()):
                return None

        return candidate if candidate else None

    @staticmethod
    def _extract_names(text: str) -> List[Tuple[str, str]]:
        """Extrait les noms par pattern matching multi-stratégie."""
        names: List[Tuple[str, str]] = []

        # Stratégie 1 : Prénom NOM (majuscules)
        for match in _NAME_PRENOM_NOM_RE.finditer(text):
            prenom = match.group(1).strip()
            nom = match.group(2).strip()
            if AutoAgentV1Parser._is_valid_name(prenom, nom):
                names.append((prenom, nom))
        if names:
            return names

        # Stratégie 2 : Prénom Nom (Title Case)
        for match in _NAME_TITLE_RE.finditer(text):
            prenom = match.group(1).strip()
            nom = match.group(2).strip()
            if AutoAgentV1Parser._is_valid_name(prenom, nom):
                names.append((prenom, nom))
        if names:
            return names

        # Stratégie 3 : Suite de majuscules brutes
        caps = re.findall(rf'\b([{_UP}]{{3,}}(?:[\s-][{_UP}]{{3,}})*)\b', text, re.UNICODE)
        for c in caps:
            if c not in _NAME_BLACKLIST:
                names.append(("", c.strip()))

        return names

    @staticmethod
    def _is_valid_name(prenom: str, nom: str) -> bool:
        """Vérifie qu'un nom n'est pas un mot du dictionnaire ou de navigation."""
        if not nom or len(nom) < 2:
            return False
        if prenom and (len(prenom) > 30 or len(prenom.split()) > 3):
            return False
        if len(nom) > 60:
            return False
        # Substring check : mots-clés de fonction qui fuient dans le prénom
        # Ex: "Adjoint Christine" MARTINELLI → rejeté car "adjoint" dans prénom
        if prenom:
            prenom_lower = prenom.lower()
            if any(kw in prenom_lower for kw in ['maire', 'adjoint', 'conseill', 'municipal', 'delegue', 'ville']):
                return False
        if prenom and prenom.upper() in _NAME_BLACKLIST:
            return False
        if nom.upper() in _NAME_BLACKLIST:
            return False
        nom_lower = nom.lower()
        if any(kw in nom_lower for kw in ["maire", "adjoint", "conseill", "municipal", "delegue"]):
            return False
        return True

    @staticmethod
    def _add_result(results: list, seen: set, prenom: str, nom: str, fonction: str):
        """Ajoute un résultat dédoublonné."""
        unique_key = f"{prenom.lower()}-{nom.lower()}-{fonction.lower()}"
        if unique_key not in seen:
            seen.add(unique_key)
            results.append({
                "nom": nom.strip(),
                "prenom": prenom.strip(),
                "fonction": fonction.strip(),
            })

    @staticmethod
    def _clean_text(text: str) -> str:
        """Nettoyage du bruit textuel."""
        if not text:
            return ""
        text = re.sub(r'[\n\r\t]+', ' ', text)
        text = re.sub(r'\s+', ' ', text)
        return text.strip()
