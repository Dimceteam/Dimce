# Déployer DimCE sur Debian + CasaOS

## 1. Copier le dossier sur le serveur
    scp -r dimce-web  utilisateur@IP_SERVEUR:~/dimce-web
(Optionnel : ajoutez `dimce.ico` dans le dossier, sinon l'app fonctionne sans icône.)

## 2. Lancer
    cd ~/dimce-web && docker compose up -d --build
L'app est sur http://IP_SERVEUR:8501 (réseau local).
Dans CasaOS : App Store > Installation personnalisée > importer docker-compose.yml.

## 3. Mettre en ligne (au choix)
- Cloudflare Tunnel : service HTTP -> http://localhost:8501 (activer les WebSockets, actif par défaut).
- Nginx Proxy Manager : proxy host -> dimce:8501, cocher « Websockets Support » + SSL Let's Encrypt.

## Mise à jour
    docker compose up -d --build

## Réglages (docker-compose.yml)
DIMCE_MAX_CONSO : consommateurs max par simulation (défaut 100)
DIMCE_MAX_SIMUL : optimisations simultanées sur le serveur (défaut 2)
