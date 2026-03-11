# 🚀 Territoires Ouverts — Outil d'expérimentation mobilité

Outil d'aide à la conception d'expérimentations de mobilité, basé sur la méthode [Territoires Ouverts](https://wiki.lafabriquedesmobilites.fr) de la Fabrique des Mobilités.

## Fonctionnement

L'outil guide l'utilisateur en **4 étapes** :

1. **Problème** — L'utilisateur décrit son problème de transport
2. **Décomposition** — L'IA identifie un sous-problème testable à petite échelle
3. **Expérimentation** — Proposition d'une expérimentation concrète avec des communs ouverts
4. **Plan complet** — Compétences, ressources, planning et budget estimé

## Déploiement sur Streamlit Cloud

### Prérequis
- Compte [Streamlit Cloud](https://streamlit.io/cloud) (gratuit)
- Compte [Anthropic](https://console.anthropic.com) (clé API)
- Compte GitHub

### Structure du dépôt GitHub
```
votre-repo/
├── app.py                                          ← Application principale
├── communs.json                                    ← 346 communs FabMob (généré)
├── requirements.txt                               ← Dépendances Python
└── README.md
```

### Étapes

1. **Créez un dépôt GitHub** et uploadez ces fichiers
2. **Sur Streamlit Cloud** :
   - New app → sélectionnez votre dépôt
   - Main file: `app.py`
   - Déployez !
3. **Dans l'app** : entrez votre clé API Anthropic dans la barre latérale

### Sécuriser la clé API (optionnel)
Pour éviter de saisir la clé à chaque fois, ajoutez-la dans les **Secrets Streamlit** :
```toml
# .streamlit/secrets.toml (ne pas committer !)
ANTHROPIC_API_KEY = "sk-ant-..."
```

## Utilisation en local (Google Colab)

```python
# Installer les dépendances
!pip install streamlit requests pdfplumber

# Lancer l'app (avec ngrok ou localtunnel)
!pip install pyngrok
from pyngrok import ngrok
import subprocess

ngrok.set_auth_token("VOTRE_TOKEN_NGROK")
public_url = ngrok.connect(8501)
print(f"URL publique : {public_url}")

subprocess.Popen(["streamlit", "run", "app.py", "--server.port=8501"])
```

## Données utilisées

- **[Fabrique des Mobilités](https://wiki.lafabriquedesmobilites.fr)** — 346 communs ouverts (export XML)
- **Méthode Territoires Ouverts** — FabMob, 2022
- **Claude (Anthropic)** — Modèle `claude-sonnet-4`

## Licence

Code : MIT  
Données communs : [Licence FabMob](https://wiki.lafabriquedesmobilites.fr)
