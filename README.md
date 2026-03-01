# Elu-Scraper (Projet Carel)

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![N8N](https://img.shields.io/badge/N8N-Automation-orange)
![GitLab Fonderie](https://img.shields.io/badge/GitLab-Fonderie-fc6d26)

Moteur de scraping asynchrone conçu pour l'extraction, la qualification et la mise à jour des fonctions électives de plus de 450 000 élus municipaux français post-élections 2026. Ce système alimente directement le CRM Salesforce de La Carel via des pipelines de données automatisées.

## 📋 Prérequis

Pour exécuter ce script en local, l'environnement nécessite l'installation des éléments suivants :

- **Python 3.10 ou supérieur**
- Connectivité aux sites web gouvernementaux / municipaux
- Accès au webhook de validation N8N

### Dépendances Python

Les packages requis se retrouvent dans `requirements.txt` :

- `fastapi`, `uvicorn` (Moteur d'API éventuel)
- `aiohttp`, `requests`, `curl_cffi` (Requêtes asynchrones et synchrones)
- `beautifulsoup4` (Parsing HTML)
- `python-dotenv` (Variables d'environnement)
- `aiosqlite` (Base de données asynchrone des URLs sources)

## 🛠️ Installation & Configuration

Récupérez le projet depuis le dépôt GitLab interne Fonderie et installez l'environnement :

```bash
# 1. Cloner le répertoire
git clone https://fonderie.apps.forgeron3.fr/rnd/elu-scraper.git
cd elu-scraper

# 2. Créer et activer l'environnement virtuel
python -m venv venv
# Sur Windows:
venv\Scripts\activate
# Sur Linux/Mac:
source venv/bin/activate

# 3. Installer les dépendances
pip install -r requirements.txt
```

_(Assurez-vous également que la base de données SQLite locale `elus_sources.db` ainsi que le fichier de référence CSV prospect/contrat sont à la racine du projet)._

## 🔄 Architecture & Flux (Workflow)

Ce projet implémente un système de synchronisation asymétrique _"One-to-Many"_ pour pallier aux cumuls des mandats et aux mutations politiques (Photo A vs Photo B) :

1. **Extraction de Référence (Photo A) :** Le code utilise un `SalesforceProvider` pour ingérer la base de données actuelle (Export CSV Salesforce) incluant tous les mandats, partis politiques, et indications EPCI affiliés aux élus.
2. **Scraping Dynamique (Photo B) :** L'outil découvre dynamiquement l'URL des mairies (s'ils n'existent pas en base) puis exécute des parsers spécialisés ou génériques pour en extraire la situation actuelle de l'élu via les pages web administratives.
3. **Filtre Asymétrique & Alertes :** Une comparaison différentielle stricte a lieu. Si une déviation de rôle (ou statut) est détectée, un payload JSON "obèse" enrichi du contexte Salesforce est envoyé vers un **webhook N8N**.
4. **Validation (N8N vers Salesforce) :** L'orchestrateur N8N hébergé sur Forgeron3 réceptionne le payload, le destine à une interface de validation humaine (via Airtable ou interface N8N), pour finalement réaliser un Push SOQL vers le **CRM Salesforce**.

## 🚀 Usage

### Lancer le scraping complet

Le point d'entrée central du parser comparateur se trouve dans `src/main.py`. L'exécution asynchrone complète (parsing + envoi vers le webhook) s'effectue via :

```bash
python src/main.py
```

_Note : Le script traite le fichier en Micro-Batchings conditionnés sur l'empreinte MD5, les pages non-modifiées n'occasionneront donc pas de scrapping et l'API N8N recevra les données par lots différés pour protéger le webhook des surcharges._

## 📁 Structure du projet

```text
elu-scraper/
├── Fichier forgeron3 test mandat prospect.csv  # Base de données Salesforce "Photo A" (Contextes)
├── elus_sources.db                             # Base SQLite locale asynchrone contenant les points d'entrées
├── requirements.txt                            # Dépendances Python
├── scraper.py                                  # Moteur de scraping HTML direct
└── src/
    ├── main.py                                 # 🚀 Point d'entrée principal (Provider, Comparatif et Webhook N8N)
    ├── models/
    │   └── mandate.py                          # Structure Pydantic des élus et de leurs mandats
    ├── parsers/
    │   ├── base.py                             # Classe abstraite asynchrone de parsing
    │   ├── factory.py                          # Factory de sélection du parser adéquat
    │   └── plugins/
    │       ├── generic_html_v1.py              # Parsing des structures classiques
    │       ├── lyon_drupal_v1.py               # Cas spécifique : Ville de Lyon
    │       ├── marseille_html_v1.py            # Cas spécifique : Ville de Marseille
    │       └── paris_lutece_v1.py              # Cas spécifique : Ville de Paris
    └── utils/
        ├── cache.py                            # Gestionnaire de cache MD5 (Diffing)
        └── url_finder.py                       # Découverte heuristique des sites web des mairies
```
