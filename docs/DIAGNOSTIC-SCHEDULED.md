# Diagnostic réseau planifié (Windows)

Mesure du chemin réel entre le poste et Aura, **sans navigateur ouvert** :
RTT, gigue, descente et montée, toutes les 15 minutes, écrites dans un CSV.
Aucune installation : PowerShell 5.1 est présent sur Windows 10 et 11.

Équivalent navigateur : page `/diagnostic`. La différence est qu'ici les mesures
continuent onglet fermé, ce qui permet de couvrir une journée entière.

## 1. Créer un jeton d'identité de service

Dans Aura : **Administration → Identités de service → Créer**.
Scopes nécessaires : `objects:read` et `objects:write` (les routes de diagnostic
exigent seulement une authentification valide).

Le jeton `aura_<uuid>_<secret>` n'est affiché **qu'une fois**.

## 2. Enregistrer le jeton, chiffré, sur le poste

```powershell
powershell -ExecutionPolicy Bypass -File scripts\aura-diag.ps1 -SaveToken
```

Collez le jeton quand il est demandé. Il est chiffré avec DPAPI (portée
utilisateur) dans `%LOCALAPPDATA%\Aura\diag-token.clixml` et l'ACL est réduite à
votre compte. Il n'apparaît jamais dans la ligne de commande de la tâche.

## 3. Vérifier une mesure à la main

```powershell
powershell -ExecutionPolicy Bypass -File scripts\aura-diag.ps1
```

Sortie : RTT min/moy/max, gigue, descente, montée navigateur et montée serveur
(en octets/s et Mbit/s). Le résultat est ajouté à
`%LOCALAPPDATA%\Aura\diag.csv` (ouvrable dans Excel).

Coût d'un passage : ~3 Mo (2 Mo lus, 1 Mo envoyé).

## 4. Planifier

```powershell
powershell -ExecutionPolicy Bypass -File scripts\aura-diag.ps1 -Install -IntervalMinutes 15
```

- Tâche nommée **AuraDiag**, au niveau utilisateur (aucune élévation en général ;
  en cas de refus, le script retombe sur `schtasks`).
- `-StartWhenAvailable` : une mesure manquée pendant une veille est rattrapée au
  réveil.
- Pour supprimer : `-Remove`.
- Changer l'intervalle : relancer `-Install -IntervalMinutes 30`.

## 5. Lire les résultats

`%LOCALAPPDATA%\Aura\diag.csv` :

| Colonne | Sens |
|---|---|
| `Timestamp` | Heure locale ISO 8601 |
| `RttMinMs` / `RttAvgMs` / `RttMaxMs` | Aller-retour vers l'API |
| `JitterMs` | Écart moyen entre deux RTT consécutifs |
| `DownBps` / `DownMbps` | Débit descendant mesuré |
| `UpBps` / `UpMbps` | Débit montant vu par le poste |
| `UpServerBps` / `UpServerMbps` | Débit montant vu par le serveur |

Lecture :

- **`UpMbps` ≈ `UpServerMbps` et bas** → le lien est lent, rien ne se perd.
- **`UpServerMbps` nettement inférieur** → des octets se perdent en route
  (transit, proxy) : c'est le cas où Cloudflare ou un serveur plus proche change
  réellement les choses.
- **Chute marquée le soir** → saturation opérateur aux heures pleines.
- **`JitterMs` élevé (> 80 ms)** → liaison instable ; les coupures d'envoi
  viennent de là.

Les erreurs sont journalisées dans `%LOCALAPPDATA%\Aura\diag-errors.log` et
n'interrompent pas la tâche suivante.

## Limites connues

- Le PC doit être allumé : une tâche planifiée ne réveille pas une machine
  éteinte.
- Le script PowerShell fourni n'a **pas pu être exécuté sur un poste Windows**
  lors de sa mise en place (l'hôte de développement est Linux) : validez
  l'étape 3 avant l'étape 4.
- Chaque passage consomme ~3 Mo de montée : à 15 minutes, ~12 Mo/heure, soit
  ~290 Mo par jour au pire. Augmentez l'intervalle si votre forfait est compté.
