# Le Brief

Application iPhone/PWA, gratuite, sans chatbot ni API IA.

## Actualisation
GitHub Actions collecte les flux publics Franceinfo, Le Monde, Le Figaro et BFM Bourse chaque heure à la minute 17. La cadence est indicative et peut subir des retards. Un dépôt inactif pendant 60 jours peut voir sa planification désactivée. Les nouvelles collectes réussies sont enregistrées automatiquement. En cas de panne, le dernier lot est conservé.

Le tri et la classification sont déterministes, avec limites par rubrique et dédoublonnage prudent. Ils ne remplacent pas une sélection humaine. Les fiches sélectionnent jusqu’à trois phrases complémentaires dans le corps des articles accessibles, en favorisant les chiffres, décisions et conséquences. Elles conservent les chiffres et les comparaisons d’origine. Si le contenu est inaccessible ou réservé aux abonnés, seul l’aperçu public est utilisé. Ce procédé extrait des passages ; il ne comprend pas le texte comme un humain. Aucun texte complet n’est stocké. Un même article déjà enrichi est réutilisé pendant douze heures si son titre et son aperçu sont inchangés. Les articles payants ne sont pas contournés. Quatre rubriques : économie, marchés, international et France. En France : politique, société, santé, éducation, justice, faits divers, culture, environnement et personnalités, selon les nouvelles disponibles.

Le site vérifie news.json toutes les cinq minutes lorsqu’il est visible et au retour dans l’application. Tirer vers le bas recharge le lot publié, sans lancer de génération.

## Coût et confidentialité
Dépôt public, GitHub Pages et runner standard Ubuntu gratuit ; aucune API payante, aucune carte bancaire ajoutée, aucune clé OpenAI, aucun modèle tiers. Les lectures, favoris et thèmes restent sur l’appareil. Pas de publicité ni analytics. Artefact Pages de petite taille, conservé un jour.

## Installation
Dans Safari : Partager > Sur l’écran d’accueil. La dernière édition est consultable hors connexion après une première ouverture en ligne.

## Fichiers
update_feed.py utilise uniquement la bibliothèque standard Python. news.json contient le dernier lot. policy.json laisse l’IA automatique désactivée. Le workflow .github/workflows/publish.yml actualise, valide, conserve le lot et déploie Pages.
