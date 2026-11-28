# Évaluation classification audio

## Gold set
- Fichier: `tests/fixtures/audio_gold_set.json`
- Ajouter des cas réels annotés manuellement (nom fichier, tags optionnels, durée, catégorie attendue, thèmes).

## Lancer l'évaluation

```bash
python3 -m api.eval_audio_classification
python3 -m api.eval_audio_classification --gold tests/fixtures/audio_gold_set.json --json
```

## Métriques
- Accuracy globale
- Précision / Rappel / F1 par catégorie
- Cas en échec (MISS) avec raison

## Procédure d'ajout de cas
1. Prendre un cas réel du bac à sable (surtout rejeté/faible confiance).
2. Annoter la catégorie attendue.
3. Ajouter l'entrée dans le gold set.
4. Relancer l'éval avant/après changement de règles.
