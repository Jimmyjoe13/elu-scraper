# 🏛️ Projet Carel : API Intermédiaire de Synchronisation RNE 📊

Cette API locale développée avec FastAPI est une brique métier essentielle pour synchroniser les données des élus français depuis le RNE (Répertoire National des Élus) ainsi que depuis des scrapers dynamiques, vers un processus d'automatisation N8N et finalement un CRM Salesforce.

## 🎯 Problème Métier Résolu

L'envoi brut des données du RNE via N8N vers Salesforce entraînait des coûts par action considérables.
Ce projet résout cette problématique en agissant comme un **entonnoir intelligent** (filtres par cibles, algorithmes de 'Diff', comparaison anti-dette avec l'état Salesforce existant), ce qui réduit la taille des payloads de >80% et optimise drastiquement le coût d'intégration.

---

## 🚀 Fonctionnalités Principales

### 🔄 Endpoints (Sécurisés par `X-API-Key`)

1. **`GET /api/v1/commune/{insee}/cibles`** (Filtrage)
   - Retourne **exclusivement** les élus considérés comme "Cibles" (ex: "Maire", "Adjoint"). Élimine les conseillers simples pour limiter les volumes N8N.
2. **`POST /api/v1/sync/batch`** (Traitement par Lot Périodique)
   - Permet d'envoyer un tableau (batch) de codes INSEE. Lance la synchronisation correspondante en arrière-plan sans bloquer N8N (asynchrone), idéal pour un lissage complet.

3. **`POST /api/v1/compare/salesforce`** (Algorithme "Anti-Dette")
   - Reçoit l'état d'un lot d'élus dans le CRM (Salesforce) et le compare à l'état local du RNE.
   - Expose en retour **exclusivement** les élus qui nécessitent un ajout (CREATE) ou une modification (UPDATE). Le reste est ignoré.

4. **`POST /api/v1/scrape/url`** (Scraping Dynamique à J+1)
   - Permet de scanner l'URL renseignée (ex: Mairie de Toulouse, Lyon, etc.), de récupérer le personnel élu mis à jour post-élection, et d'injecter cette donnée en RAM/Disque directement, avant que le Datalake étatique ne soit mis à jour.

### 🧠 Structure et Sécurité

- **Swagger/Docs automatique** sur : `http://127.0.0.1:8000/docs`.
- **Mémoire cache persistante** : Toutes les modifications (scrape, batch, download complet RNE) sont gardées dans un verrou protégé par un Thème de Thread (`Thread.Lock`), et persistées en Json local (`rne_state.json`) pour préserver les requêtes serveur et garantir l'idempotence.
- **Pydantic Models** : Assurent que n'importe quelle requête envoyée par N8N qui serait imparfaitement formatée sera gracieusement rejetée et clairement logguée (Code 422 standard HTTP).

---

## 🛠️ Installation et Démarrage Rapide

1. **Cloner / Décompresser** le projet dans votre répertoire.
2. **Créer l'environnement virtuel** :
   ```bash
   python -m venv venv
   # Sous Mac/Linux :
   source venv/bin/activate
   # Sous Windows :
   .\\venv\\Scripts\\activate
   ```
3. **Installer les dépendances** :
   ```bash
   pip install -r requirements.txt
   ```
4. **Lancement du serveur** :
   ```bash
   python api.py
   # Ou
   uvicorn api:app --host 127.0.0.1 --port 8000 --reload
   ```

_(Par défaut la clé API d'accès exigée via le Header `X-API-Key` est : `super-secret-key-carel-2026`, sauf si la variable d'environnement `RNE_API_KEY` est spécifiée)._

## 🧹 Architecture Globale

Le projet s'appuie sur une architecture logicielle modulaire :

- `api.py` : Entrées/sorties logiques, routing (endpoints), modèles de validation (Pydantic) et sécurisation.
- `rne_differ.py` : Logique de comparaison des listes d'élus, et interface de chargement/sauvegarde de la data en cache local (le composant clé du 'diff').
- `sync_rne.py` : Script global gérant les transferts massifs RNE vers le Webhook N8N.
- `scraper.py` : Web scrapers spécifiques à des villes appelées dynamiquement.
- `rne_parser` & `rne_downloader` : Utilitaires pour télécharger et ingérer les CSV du DataGouv.
