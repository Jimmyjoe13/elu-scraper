# 🏛️ Projet Carel : API Intermédiaire de Synchronisation & Scraping IA 📊

Cette API locale développée avec FastAPI est la brique métier vitale pour synchroniser les données des élus français depuis le RNE (Data.gouv) tout en offrant un système avancé de Scraping Web par IA, le tout couplé à un processus d'automatisation N8N vers Salesforce.

## 🎯 Problème Métier Résolu

L'envoi brut des données vers Salesforce via N8N entraîne des coûts et des lenteurs considérables. De plus, les élections partielles ou démissions rendent le RNE souvent obsolète de plusieurs mois.
Ce projet résout ces problématiques avec une architecture **SQLite ultra-légère** (Upsert local) et agit comme un **entonnoir intelligent** anti-dette. En cas de donnée manquante, le moteur intègre un Scraper IA 100% autonome pour collecter l'information en temps réel sur le web, avant la mise à jour de l'État.

---

## 🚀 Fonctionnalités Principales

### 🔄 Endpoints (Sécurisés par `X-API-Key`)

1. **`GET /api/v1/commune/{insee}/cibles`** (Filtrage de Haute Précision)
   - Retourne **exclusivement** les exécutifs (Maire, Adjoint, Président, Vice-Président, Délégué). Élimine les simples conseillers pour cibler les décideurs.

2. **`POST /api/v1/scrape/url`** (Scraping Universel & Spidering IA)
   - L'innovation du projet : À partir d'un simple nom de domaine (ex: `montpellier.fr`), l'API trouve de façon autonome la sous-page web des élus (Spidering Hybride).
   - Utilise **Mistral-small** (IA LLM) pour analyser la page web, comprendre la structure (peu importe le CMS de la commune), extraire le nom/prénom/poste de l'élu et l'injecter immédiatement en base SQLite `rne_data.db`.
   - Résistance Anti-Bot (TLS Spoofing) avec `curl_cffi` impitoyable face à Cloudflare.

3. **`POST /api/v1/compare/salesforce`** (Algorithme "Anti-Dette")
   - Reçoit l'état matériel d'un lot d'élus dans Salesforce et le compare au cache SQLite.
   - Expose en retour **strictement** les élus qui nécessitent un `CREATE` ou un `UPDATE`, neutralisant les appels N8N redondants.

### 🧠 Structure et Sécurité

- **Base de données SQLite (`rne_data.db`)** : Utilisée comme cache local rapide avec mode WAL pour la concurrence. Ne dépend plus de l'ancien `rne_state.json`.
- **Mémoire cache persistante Spidering** : Les URL web d'élus découvertes sont mémorisées dans la table `communes_urls` pour éviter de balayer deux fois le site d'une même commune.
- **Pydantic Models** : Assurent que toute requête envoyée par N8N qui serait imparfaitement formatée sera gracieusement rejetée et logguée.

---

## 🛠️ Installation et Démarrage

1. **Cloner / Décompresser** le projet dans votre répertoire.
2. **Créer l'environnement virtuel** :
   ```bash
   python -m venv venv
   # Sous Windows :
   .\\venv\\Scripts\\activate
   ```
3. **Installer les dépendances** :
   ```bash
   pip install -r requirements.txt
   ```
4. **Fichier `.env` requis** :
   Créer un fichier contenant impérativement la clé API du LLM :
   `MISTRAL_API_KEY=votre_cle_ici`
5. **Lancement du serveur** :
   ```bash
   python api.py
   # Ou
   uvicorn api:app --host 127.0.0.1 --port 8000 --reload
   ```

## 🧹 Architecture Globale

- `api.py` : Entrées/sorties logiques, routing (endpoints), modèles de validation (Pydantic), et sécurisation.
- `database.py` : Gestion du Singleton de connexion SQLite et intégrité des tables.
- `scraper.py` : Moteur IA de scraping universel (Mistral), Auto-Spidering (Fallback DOM/URL Soft 404/Sitemap), et module Anti-Bot (Spoofing TLS impersonate "Chrome").
- `sync_rne.py` / `rne_parser.py` : Utilitaires pour télécharger et ingérer le référentiel d'État complet.
- `render.yaml` : Fichier de configuration d'Infrastructure-as-code pour un déploiement cloud fluide sur Render (limite stricte 512 Mo RAM respectée par stream sitemap et absence de Selenium).
