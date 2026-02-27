import hashlib
from datetime import datetime
from pydantic import BaseModel, Field, field_validator, computed_field

class ElectedOfficialMandate(BaseModel):
    nom: str = Field(exclude=True)
    prenom: str = Field(exclude=True)
    ville_ou_secteur: str = Field(exclude=True)
    fonction: str = Field(exclude=True)
    source_url: str = Field(exclude=True)
    date_extraction: datetime = Field(default_factory=datetime.utcnow, exclude=True)

    @field_validator("nom")
    def uppercase_nom(cls, v: str) -> str:
        return v.strip().upper()

    @field_validator("prenom")
    def titlecase_prenom(cls, v: str) -> str:
        return v.strip().title()

    @property
    def id_technique(self) -> str:
        unique_string = f"{self.nom}-{self.prenom}-{self.fonction}-{self.ville_ou_secteur}".lower()
        return hashlib.md5(unique_string.encode("utf-8")).hexdigest()

    # --- Salesforce Exact Mappings (Action 1) ---
    
    @computed_field(alias="Nom")
    def sf_nom(self) -> str:
        return f"MAIRIE DE {self.ville_ou_secteur.upper()}"

    @computed_field(alias="Nom abrégé de la collectivité")
    def sf_nom_abrege(self) -> str:
        return f"MAIRIE DE {self.ville_ou_secteur.upper()}"

    @computed_field(alias="Type de collectivité")
    def sf_type_collectivite(self) -> str:
        return "Commune"

    @computed_field(alias="Adresse 1")
    def sf_adresse_1(self) -> str:
        return ""

    @computed_field(alias="Adresse 2")
    def sf_adresse_2(self) -> str:
        return ""

    @computed_field(alias="BP/CS")
    def sf_bp_cs(self) -> str:
        return ""

    @computed_field(alias="Code")
    def sf_code(self) -> str:
        return ""

    @computed_field(alias="Code Postal")
    def sf_code_postal(self) -> str:
        return ""

    @computed_field(alias="Ville")
    def sf_ville(self) -> str:
        return self.ville_ou_secteur.upper()

    @computed_field(alias="Élu : Civilité")
    def sf_elu_civilite(self) -> str:
        f_lower = self.fonction.lower()
        if "adjointe" in f_lower or "conseillère" in f_lower or "la maire" in f_lower:
            return "Mme"
        
        prenoms_f = [
            "anne", "marie", "jeanne", "nathalie", "sophie", "isabelle", 
            "sylvie", "catherine", "martine", "francoise", "céline", 
            "véronique", "julie", "sandrine", "aurélie", "fanny", "camille", 
            "chloé", "hélène", "florence", "valérie"
        ]
        
        prenom_lower = self.prenom.lower()
        if prenom_lower in prenoms_f:
            return "Mme"
            
        if "-" in prenom_lower and prenom_lower.split("-")[0] in prenoms_f:
            return "Mme"
            
        return "M."

    @computed_field(alias="Élu : Nom")
    def sf_elu_nom(self) -> str:
        return f"{self.prenom} {self.nom}"

    @computed_field(alias="Fonction élective")
    def sf_fonction_elective(self) -> str:
        return self.fonction

    @computed_field(alias="Formule de politesse")
    def sf_formule_politesse(self) -> str:
        civ = self.sf_elu_civilite
        f_lower = self.fonction.lower()
        prefix = "le" if civ == "M." else "la"
        
        if "maire" in f_lower:
            return f"{prefix} Maire"
        elif "adjoint" in f_lower:
            return f"{prefix} {'Adjoint' if civ == 'M.' else 'Adjointe'}"
        elif "conseiller" in f_lower or "conseillère" in f_lower:
            return f"{prefix} {'Conseiller' if civ == 'M.' else 'Conseillère'}"
            
        return f"{prefix} Conseiller"

    @computed_field(alias="Élu : Adresse 1")
    def sf_elu_adresse_1(self) -> str:
        return ""

    @computed_field(alias="Élu : Adresse 2")
    def sf_elu_adresse_2(self) -> str:
        return ""

    @computed_field(alias="Élu : Code Postal")
    def sf_elu_code_postal(self) -> str:
        return ""

    @computed_field(alias="Élu : Ville")
    def sf_elu_ville(self) -> str:
        return self.ville_ou_secteur.upper()

    @computed_field(alias="Nom du chargé commercial")
    def sf_nom_charge_commercial(self) -> str:
        return ""

    @computed_field(alias="Mandat : Mandat Name")
    def sf_mandat_name(self) -> str:
        return ""

    @computed_field(alias="Mandat : Type d'enregistrement")
    def sf_mandat_type_enregistrement(self) -> str:
        return "MANDAT CONTRAT"
