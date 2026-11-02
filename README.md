# Le Brief

Application iPhone/PWA, gratuite, sans chatbot ni API IA.

## Actualisation
GitHub Actions collecte les flux publics Le Monde, Le Figaro et BFM Bourse chaque heure à la minute 17. La cadence est indicative et peut subir des retards. Un dépôt inactif pendant 60 jours peut voir sa planification désactivée. Les nouvelles collectes réussies sont enregistrées automatiquement. En cas de panne, le dernier lot est conservé.

Le tri et la classification sont déterministes, avec limites par rubrique et dédoublonnage prudent. Ils ne remplacent pas une sélection humaine. Les titres et courts extraits proviennent des médias ; ils ne sont pas des synthèses GPT. Les articles payants ne sont pas contournés. M&A : seuls les montants vérifiés à partir de 100 M€ sont retenus dans les lots relus manuellement.

Le site vérifie news.json toutes les cinq minutes lorsqu’il est visible et au retour dans l’application. Tirer vers le bas recharge le lot publié, sans lancer de génération.

## Coût et confidentialité
Dépôt public, GitHub Pages et runner standard Ubuntu gratuit ; aucune API payante, aucune carte bancaire ajoutée, aucune clé OpenAI, aucun modèle tiers. Les lectures, favoris et thèmes restent sur l’appareil. Pas de publicité ni analytics. Artefact Pages de petite taille, conservé un jour.

## Installation
Dans Safari : Partager > Sur l’écran d’accueil. La dernière édition est consultable hors connexion après une première ouverture en ligne.

## Fichiers
update_feed.py utilise uniquement la bibliothèque standard Python. news.json contient le dernier lot. policy.json laisse l’IA automatique désactivée. Le workflow .github/workflows/publish.yml actualise, valide, conserve le lot et déploie Pages.
