## Contexte
Il n'existe que des healthchecks Docker et l'endpoint `/admin/health`. Personne n'est prévenu si le disque se remplit, si la sauvegarde ne tourne plus, si le certificat expire ou si le taux d'erreur monte.

## Proposition (sur le même VPS, réseau interne, rien d'exposé)
- `prometheus` + `alertmanager` + `node-exporter` ; métriques Traefik (`--metrics.prometheus`) ; métriques SeaweedFS (`-metricsPort`) ; métriques API (`prometheus-client` : requêtes, latence, commits, échecs).
- Alertes minimales : disque > 80 %, aucune sauvegarde réussie depuis 26 h (ping de `scripts/backup.sh`), certificat < 14 jours, 5xx > 1 %, conteneur redémarré en boucle.
- Canal d'alerte : e-mail ou Telegram.
- Grafana optionnel (accès VPN uniquement).

## Critères
- [ ] Chaque alerte déclenchée volontairement une fois en test.
- [ ] Aucun nom de fichier, URL présignée ou secret dans les métriques.

## Liens
Reprend la partie « observabilité » restante de #40.
