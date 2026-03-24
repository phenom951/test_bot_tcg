# One Piece TCG — Stock Alert Bot

Bot de surveillance de stock qui envoie une alerte Discord dès qu'un produit One Piece TCG est disponible sur Fnac, Cultura ou Carrefour.

## Sites surveillés
- Fnac.com
- Cultura.com
- Carrefour.fr

## Produits ciblés
Tout produit contenant "one piece", "op-", "op0", "op1", "prb-", "eb-" dans le nom.

---

## Déploiement sur Railway (recommandé)

1. Push ce dossier sur un repo GitHub (privé)
2. Va sur [railway.app](https://railway.app) → New Project → Deploy from GitHub
3. Sélectionne ton repo
4. Railway détecte automatiquement le `Procfile` et lance `python onepiece_alert.py`
5. C'est tout — ça tourne 24/7 gratuitement

---

## Lancer en local

```bash
pip install -r requirements.txt
python onepiece_alert.py
```

---

## Personnalisation

Dans `onepiece_alert.py` :
- `CHECK_INTERVAL` : délai entre chaque scan (défaut 60s)
- `KEYWORDS` : mots-clés pour filtrer les produits
- `SITES` : ajouter/supprimer des sites

## Ajouter un site

```python
{
    "name": "NomDuSite",
    "url": "https://www.exemple.com/one-piece",
    "parser": "generic",  # ou créer une fonction parse_exemple()
},
```
