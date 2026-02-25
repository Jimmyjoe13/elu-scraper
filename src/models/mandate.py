import hashlib
from datetime import datetime
from pydantic import BaseModel, Field, field_validator, computed_field

class ElectedOfficialMandate(BaseModel):
    nom: str
    prenom: str
    ville_ou_secteur: str
    fonction: str
    source_url: str
    date_extraction: datetime = Field(default_factory=datetime.utcnow)

    @field_validator("nom")
    def uppercase_nom(cls, v: str) -> str:
        return v.strip().upper()

    @field_validator("prenom")
    def titlecase_prenom(cls, v: str) -> str:
        return v.strip().title()

    @computed_field
    def id_technique(self) -> str:
        unique_string = f"{self.nom}-{self.prenom}-{self.fonction}-{self.ville_ou_secteur}".lower()
        return hashlib.md5(unique_string.encode("utf-8")).hexdigest()
