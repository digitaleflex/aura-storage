# Règles de classification audio (déterministes)

Ce fichier décrit le format de `api/audio_rules.json`, utilisé par `api/audio_ai.py` pour classer les audios sans IA externe.

## Format

```json
{
  "version": 1,
  "description": "Optionnel",
  "categories": [
    {
      "category": "meditation",
      "keywords": ["meditation", "pleine conscience", "respiration"]
    }
  ]
}
```

## Règles
- `categories` : liste d'objets.
- `category` : string non vide, identifiant stable (`snake_case` recommandé).
- `keywords` : liste de strings non vides. Les mots-clés sont normalisés (minuscules, accents retirés) avant matching.
- Catégories connues par défaut : `meditation`, `developpement_personnel`, `formation`, `business`, `podcast`, `litterature`, `spiritualite`, `musique`, `sante_bien_etre`, `histoire_societe`, `autre`.

## Validation

```bash
python3 -m api.validate_audio_rules
# ou
python3 -m api.validate_audio_rules api/audio_rules.json
```

En cas d'erreur, la commande retourne code 1 et liste les problèmes. Au runtime, un JSON invalide déclenche un warning et le moteur utilise les règles intégrées (fallback sûr).

## Mise à jour en production

Le fichier est lu à chaque classification (`classify_with_rules`), donc :
- **Dev/local bind-mount** : modification prise en compte au prochain job.
- **Prod image Docker** : modifier `api/audio_rules.json`, puis :

```bash
docker compose build api && docker compose up -d api
```

## Bonnes pratiques
- Ajouter des mots-clés à partir des cas rejetés / faible confiance (`GET /api/v1/audio-classifications/feedback`).
- Préférer des mots-clés spécifiques avant d'élargir trop.
- Garder les corrections humaines : elles servent à proposer de nouvelles règles.
