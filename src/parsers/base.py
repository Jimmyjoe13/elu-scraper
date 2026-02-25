from abc import ABC, abstractmethod
from typing import List, Optional
import aiohttp
import asyncio
import hashlib
import logging

from src.models.mandate import ElectedOfficialMandate

logger = logging.getLogger(__name__)

class BaseParser(ABC):
    def __init__(self, url: str, ville_ou_secteur: str):
        self.url = url
        self.ville_ou_secteur = ville_ou_secteur
        self.html_content: Optional[str] = None

    async def fetch(self, session: aiohttp.ClientSession) -> Optional[str]:
        max_retries = 3
        base_delay = 2

        for attempt in range(max_retries):
            try:
                # SSL verification is disabled for municipal sites as per previous context
                async with session.get(self.url, ssl=False) as response:
                    # Retry on 429 and 50x errors
                    if response.status in (429, 500, 502, 503, 504):
                        logger.warning(f"Status {response.status} for {self.url} (att {attempt+1})")
                        await asyncio.sleep(base_delay ** attempt)
                        continue
                    
                    response.raise_for_status()
                    self.html_content = await response.text()
                    return self.html_content
                    
            except aiohttp.ClientError as e:
                logger.warning(f"Client error for {self.url} (att {attempt+1}): {e}")
                await asyncio.sleep(base_delay ** attempt)
        
        logger.error(f"Echec du téléchargement {self.url} après {max_retries} tentatives.")
        return None

    def get_content_hash(self) -> Optional[str]:
        if not self.html_content:
            return None
        return hashlib.md5(self.html_content.encode("utf-8")).hexdigest()

    @abstractmethod
    def extract(self) -> List[dict]:
        """Extrait les données brutes (1 dict = 1 fonction) à partir de self.html_content."""
        pass

    def normalize(self) -> List[ElectedOfficialMandate]:
        raw_data = self.extract()
        mandates = []
        for item in raw_data:
            try:
                # La contrainte: 1 ligne = 1 mandat/fonction.
                mandate = ElectedOfficialMandate(
                    nom=item.get("nom", ""),
                    prenom=item.get("prenom", ""),
                    ville_ou_secteur=self.ville_ou_secteur,
                    fonction=item.get("fonction", ""),
                    source_url=self.url
                )
                mandates.append(mandate)
            except Exception as e:
                logger.error(f"Erreur de validation pour {item}: {e}")
        return mandates
