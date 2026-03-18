"""Tests unitaires pour les corrections de faux positifs 'Maire' en Photo B."""
import csv
import os
import tempfile
import pytest
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.parsers.plugins.generic_html_v1 import GenericHtmlV1Parser
from src.main import generate_validation_alerts, normalize_fonction, get_fonction_weight
from src.models.mandate import ElectedOfficialMandate


# ──────────────────────────────────────────────────────────────────
# Bug 1 : _extract_fonction() — filtre des prépositions
# ──────────────────────────────────────────────────────────────────

class TestExtractFonction:
    """Tests pour _extract_fonction() dans generic_html_v1.py."""

    @pytest.fixture
    def parser(self):
        return GenericHtmlV1Parser(url="http://test.fr", ville_ou_secteur="TestVille")

    def test_adjoint_au_maire(self, parser):
        result = parser._extract_fonction("Adjoint au Maire")
        assert result == "Adjoint au Maire"

    def test_maire_simple(self, parser):
        result = parser._extract_fonction("Maire")
        assert result == "Maire"

    def test_maire_de_la_commune(self, parser):
        result = parser._extract_fonction("Maire de la commune")
        assert result is not None
        assert result.lower().startswith("maire")

    def test_delegation_du_maire_returns_none(self, parser):
        result = parser._extract_fonction("délégation du Maire pour l'urbanisme")
        assert result is None

    def test_aupres_du_maire_returns_none(self, parser):
        result = parser._extract_fonction("auprès du Maire de la commune")
        assert result is None

    def test_convocation_du_maire_returns_none(self, parser):
        result = parser._extract_fonction("convocation du Maire")
        assert result is None

    def test_long_descriptive_text_returns_none(self, parser):
        text = (
            "les aulnaisiennes et les aulnaysiens ont renouvelé l'équipe "
            "municipale lors des élections du maire de la commune en 2026"
        )
        result = parser._extract_fonction(text)
        assert result is None

    def test_conseiller_aupres_du_maire(self, parser):
        result = parser._extract_fonction("Conseiller municipal délégué auprès du Maire")
        assert result is not None
        assert result.lower().startswith("conseiller")

    def test_par_le_maire_returns_none(self, parser):
        result = parser._extract_fonction("par le Maire de la ville")
        assert result is None

    def test_presence_du_maire_returns_none(self, parser):
        result = parser._extract_fonction("présence du Maire et des adjoints")
        assert result is None


# ──────────────────────────────────────────────────────────────────
# Bug 2 : generate_validation_alerts() — confiance promotions
# ──────────────────────────────────────────────────────────────────

def _build_photo_a(ville, nom, fonction, sf_id="SF001"):
    """Helper pour construire un dict photo_a minimal."""
    from src.main import normalize_string, normalize_ville
    v = normalize_ville(ville)
    n = normalize_string(nom)
    key = f"{v}---{n}"
    return {
        key: [{
            "fonction": fonction,
            "id_salesforce": sf_id,
            "raw_nom": nom,
            "raw_ville": ville,
            "mandat_name": "Mandat Test",
            "parti_politique": "",
            "indicateur_epci": "",
            "type_mandat": "COMMUNE",
            "etat_contrat": "en_cours",
        }]
    }


def _build_mandate(ville, prenom, nom, fonction, url="http://test.fr/elus"):
    return ElectedOfficialMandate(
        nom=nom,
        prenom=prenom,
        ville_ou_secteur=ville,
        fonction=fonction,
        source_url=url,
    )


class TestConfidencePromotions:
    """Tests pour le niveau de confiance des promotions suspectes."""

    def test_adjoint_to_maire_is_high(self):
        """Gap de 1 niveau (3→4) : confiance HIGH."""
        photo_a = _build_photo_a("TestVille", "Jean DUPONT", "Adjoint au Maire")
        mandates = [_build_mandate("TestVille", "Jean", "DUPONT", "Maire")]
        alerts = generate_validation_alerts(photo_a, mandates)
        assert len(alerts) == 1
        assert alerts[0]["niveau_confiance"] == "HIGH"

    def test_conseiller_to_maire_is_medium(self):
        """Gap de 3 niveaux (1→4) : confiance MEDIUM."""
        photo_a = _build_photo_a("TestVille", "Jean DUPONT", "Conseiller Municipal")
        mandates = [_build_mandate("TestVille", "Jean", "DUPONT", "Maire")]
        alerts = generate_validation_alerts(photo_a, mandates)
        assert len(alerts) == 1
        assert alerts[0]["niveau_confiance"] == "MEDIUM"

    def test_conseiller_to_adjoint_is_medium(self):
        """Gap de 2 niveaux (1→3) : confiance MEDIUM."""
        photo_a = _build_photo_a("TestVille", "Jean DUPONT", "Conseiller Municipal")
        mandates = [_build_mandate("TestVille", "Jean", "DUPONT", "Adjoint au Maire")]
        alerts = generate_validation_alerts(photo_a, mandates)
        assert len(alerts) == 1
        assert alerts[0]["niveau_confiance"] == "MEDIUM"

    def test_alert_keys_unchanged(self):
        """Vérifie que les clés JSON du webhook restent identiques."""
        expected_keys = {
            "alerte_type", "elu", "commune", "strate_priorite",
            "statut_salesforce_actuel", "statut_trouve_web",
            "source_url_trouvee", "niveau_confiance", "mandat_name",
            "parti_politique", "indicateur_epci", "type_mandat",
            "etat_contrat", "date_detection",
        }
        photo_a = _build_photo_a("TestVille", "Jean DUPONT", "Conseiller Municipal")
        mandates = [_build_mandate("TestVille", "Jean", "DUPONT", "Maire")]
        alerts = generate_validation_alerts(photo_a, mandates)
        assert len(alerts) == 1
        assert set(alerts[0].keys()) == expected_keys


# ──────────────────────────────────────────────────────────────────
# Bug 3 : Encodage CSV — latin-1 / cp1252
# ──────────────────────────────────────────────────────────────────

class TestCSVEncoding:
    """Tests pour la lecture correcte des CSV Salesforce encodés en latin-1."""

    def test_latin1_csv_no_replacement_chars(self):
        """Un CSV encodé en latin-1 ne doit pas produire de caractères de remplacement."""
        from src.main import SalesforceProvider

        # Créer un CSV temporaire en latin-1 avec des accents français
        with tempfile.NamedTemporaryFile(
            mode="wb", suffix=".csv", delete=False, prefix="test_sf_"
        ) as f:
            # Header + 1 ligne avec accents (latin-1)
            # Colonnes : 0-8 padding, 9=ville, 10=padding, 11=nom, 12=fonction,
            #            13-18 padding, 19=mandat, 20=type, 21=etat
            header = ";".join([
                "c0", "c1", "c2", "c3", "c4", "c5", "c6", "c7", "c8",
                "Ville", "c10", "Elu:Nom", "Fonction",
                "c13", "c14", "c15", "c16", "c17", "c18",
                "Mandat", "Type", "Etat"
            ]) + "\n"
            row = ";".join([
                "", "", "", "", "", "", "", "", "",
                "Aix-en-Provence", "", "Marie HÉLOÏSE", "Conseillère Municipale",
                "", "", "", "", "", "",
                "Mandat 2026", "COMMUNE", "En cours"
            ]) + "\n"
            f.write(header.encode("latin-1"))
            f.write(row.encode("latin-1"))
            tmp_path = f.name

        try:
            provider = SalesforceProvider.__new__(SalesforceProvider)
            provider.root_dir = os.path.dirname(tmp_path)
            provider.csv_files = [os.path.basename(tmp_path)]

            import asyncio
            photo_a = asyncio.new_event_loop().run_until_complete(provider.get_photo_a())

            # Vérifier qu'aucune valeur ne contient le caractère de remplacement
            for key, records in photo_a.items():
                for record in records:
                    fonction = record.get("fonction", "")
                    assert "\ufffd" not in fonction, (
                        f"Caractère de remplacement trouvé dans fonction: {fonction}"
                    )
                    assert "Conseillère" in fonction or "conseillere" in fonction.lower(), (
                        f"Accent perdu dans fonction: {fonction}"
                    )
        finally:
            os.unlink(tmp_path)
