# soutenance-app

Application Python / Flask / PostgreSQL de démonstration : le jury note la soutenance,
mais les notes trop basses sont impossibles à attraper. Les notes hautes sont cliquables
et enregistrées dans PostgreSQL.

Plus la note est haute, plus elle est accessible : le 20 est le plus gros bouton et ne bouge
pas. Le 19 esquive une fois, le 18 deux fois et plus loin, etc. (6 fois au maximum), puis la
note se fatigue et se laisse attraper. Les esquives sont réinitialisées quand la souris quitte
la zone. Parmi les notes basses, les plus faibles sont les plus petites et fuient de plus loin
(`FLEE_RADIUS` est la distance de référence, ajustée de ×1,35 à ×0,8).

## Lancer en local

```sh
docker compose up --build
```

Puis ouvrir http://localhost:8080 (`HOST_PORT=8090` pour changer de port).
Pour changer les variables : copier `.env.example` en `.env`, le modifier, relancer
`docker compose up -d`.

Sans Compose : `pip install -r requirements.txt`, définir `DB_HOST`, `DB_PORT`
(5432 par défaut), `DB_NAME`, `DB_USER`, `DB_PASSWORD`, puis `python app.py`.

## Variables d'environnement de l'application

Toutes sont facultatives. Une valeur invalide est remplacée par la valeur par défaut
(un nombre hors limites est ramené à la limite).

| Variable | Défaut | Effet |
|---|---|---|
| `APP_TITLE` | `Soutenance SIGL` | Titre de la page |
| `TEAM_NAME` | `Notre équipe` | Nom de l'équipe notée |
| `GRADE_THRESHOLD` | `16` | Les notes inférieures fuient et sont refusées par le serveur (0 à 20) |
| `FLEE_MODE` | `flee` | `flee` (s'éloigne), `vanish` (disparaît), `shrink` (rétrécit), `chaos` (mélange) |
| `FLEE_RADIUS` | `130` | Distance de réaction à la souris, en pixels (60 à 300) |
| `ACCENT_COLOR` | `#6d5efc` | Couleur principale, format `#rrggbb` |
| `JURY_CODE` | vide | **Secret.** S'il est défini, il est demandé pour enregistrer une note |

Sur le portail CNP, les saisir dans les variables du formulaire de déploiement (ou importer
un fichier `.env`). Les noms `PORT`, `APP_PORT`, `DB_*`, `DD_*` et `CNP_*` sont réservés
à la plateforme.

## Ce que stocke PostgreSQL

| Table | Contenu |
|---|---|
| `grades` | Notes attribuées : note, nom, commentaire, instance, date |
| `escapes` | Nombre d'esquives par note basse |
| `visits` | Une ligne par visite |

Les tables sont créées au premier accès.

## Scénario de démonstration

1. Essayer d'attraper un 3, puis enregistrer un 18 avec un commentaire.
2. Redémarrer l'application : `docker compose restart web` (ou redéployer). La note est
   toujours là, et le panneau « Preuve de persistance » la compte comme antérieure au
   démarrage. `docker compose down` puis `up` la conserve aussi ; `down -v` efface tout.
3. Tenter de tricher, le serveur répond 403 :

   ```sh
   curl -i http://localhost:8080/api/grades -H 'Content-Type: application/json' \
     -d '{"grade":2,"juror":"Tricheur"}'
   ```

4. Changer `GRADE_THRESHOLD` ou `FLEE_MODE`, redéployer : le comportement change sans
   modifier le code.

## Exploitation

Chaque note enregistrée écrit `LOG/ note inscrite : 18/20` dans les logs
(`docker compose logs -f web`).

`/healthz` vérifie le processus web ; `/health` renvoie 200 seulement si PostgreSQL est
joignable et inscriptible (sonde de disponibilité du cloud privé). Le conteneur tourne sans
root (UID/GID 10001). L'état est entièrement en base : plusieurs réplicas sont possibles.
Ne jamais versionner d'identifiants.

Le compteur d'esquives est déclaré par le navigateur : il est ludique, pas fiable.
Sans `JURY_CODE`, toute personne ayant accès à la page peut enregistrer une note haute.

Pour le déploiement, choisir une base PostgreSQL dans le formulaire du portail (GCP Cloud
SQL, Azure PostgreSQL ou cloud privé k3s). Créer ce dépôt ne provisionne rien.
