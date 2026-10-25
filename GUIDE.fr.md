# Guide rapide

`kanban-followup` produit un état manuel des cartes bloquées/en triage. Il ne relance, ne débloque, ne termine et ne planifie rien.

```sh
hermes kanban-followup --db /chemin/kanban.db --coordinator coordinateur --session-id session-exacte --json
```

L'installation et l'activation dans un profil restent une opération séparée de l'opérateur. Les trois paramètres de périmètre sont obligatoires. Les cartes créées par le coordinateur sont incluses toutes sessions confondues dans **cette** base ; les autres doivent posséder l'abonnement TUI correspondant exactement à la session et au coordinateur.

Une trace est un commentaire natif commençant par `BLOCK_FOLLOWUP_V1 ` et contenant un objet JSON avec `version: 1`, `event_id` courant, `owner`, `next_action`, `condition`, `review_at` ISO 8601 avec fuseau et `state` (`waiting` ou `resolved`). Le plugin ne crée pas ces commentaires. Le curseur d'abonnement ne prouve jamais la réception d'une notification.

Lecture seule : ouverture SQLite `mode=ro`, `query_only=ON`, transaction de lecture ; aucune migration. Base absente : non créée. Schéma incompatible : erreur JSON structurée sur stderr, code retour 2. Le contrat de schéma minimal et les limites WAL/symlinks sont décrits dans README.md.

Les dates à venir ne déclenchent aucun réveil. Relancez le rapport manuellement. `administrative_close` est un conseil, pas une clôture ni une autorisation.

## Vérifier sans profil réel

```sh
HERMES_SOURCE=/chemin/hermes-agent /chemin/hermes-agent/.venv/bin/python -m unittest discover -s tests -v
```

Les tests utilisent des bases synthétiques et un HOME jetable sans identifiants. La découverte native et les callbacks CLI sont réellement exécutés ; le bootstrap complet Hermes/PM n'est pas lancé par le harnais final. Aucun réseau fournisseur ni inférence n'est nécessaire.
