import streamlit as st
import json
import re
import xml.etree.ElementTree as ET
import requests
import os

# ── Configuration ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Territoires Ouverts – Outil d'expérimentation mobilité",
    page_icon="🚲",
    layout="wide",
)

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-sonnet-4-5-20250929"

# ── Chargement des communs ─────────────────────────────────────────────────────
@st.cache_data
def load_communs():
    """Charge les communs depuis le fichier JSON ou XML."""
    try:
        with open("communs.json", "r") as f:
            return json.load(f)
    except FileNotFoundError:
        # Fallback: parse XML
        try:
            tree = ET.parse("Communauté_de_la_Fabrique_des_Mobilités-20260311084238.xml")
            root = tree.getroot()
            ns = {'mw': 'http://www.mediawiki.org/xml/export-0.11/'}
            pages = root.findall('mw:page', ns)
            communs = []
            for page in pages:
                title = page.find('mw:title', ns).text
                text_el = page.find('.//mw:text', ns)
                text = text_el.text if text_el is not None else ""
                if not text: continue
                type_match = re.search(r'\|type=([^\n|]+)', text)
                if not type_match or 'Commun' not in type_match.group(1): continue
                def get_field(f):
                    m = re.search(r'\|' + f + r'=([^\n|{}]+(?:\n(?!\|)[^\n|{}]+)*)', text)
                    return m.group(1).strip() if m else ""
                communs.append({
                    'title': title,
                    'shortDescription': get_field('shortDescription'),
                    'description': get_field('description')[:500],
                    'challenge': get_field('challenge'),
                    'needs': get_field('needs'),
                    'license': get_field('license'),
                })
            return communs
        except Exception as e:
            st.error(f"Impossible de charger les communs: {e}")
            return []

def format_communs_for_prompt(communs):
    """Formate les communs pour le prompt Claude (version condensée)."""
    lines = []
    for c in communs:
        line = f"- **{c['title']}**: {c['shortDescription']}"
        if c.get('challenge'):
            line += f" | Défi: {c['challenge'][:120]}"
        lines.append(line)
    return "\n".join(lines)

# ── Appel Claude API ───────────────────────────────────────────────────────────
def call_claude(messages, system_prompt, api_key):
    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
    }
    payload = {
        "model": MODEL,
        "max_tokens": 4096,
        "stream": True,
        "system": system_prompt,
        "messages": messages,
    }
    try:
        response = requests.post(
            ANTHROPIC_API_URL, headers=headers, json=payload,
            timeout=180, stream=True
        )
        if not response.ok:
            try:
                err_body = response.json()
                err_msg = err_body.get("error", {}).get("message", response.text)
            except Exception:
                err_msg = response.text
            return f"❌ Erreur API ({response.status_code}): {err_msg}"
        full_text = ""
        for line in response.iter_lines():
            if not line:
                continue
            line = line.decode("utf-8") if isinstance(line, bytes) else line
            if line.startswith("data: "):
                data_str = line[6:]
                if data_str.strip() == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_str)
                    if chunk.get("type") == "content_block_delta":
                        full_text += chunk.get("delta", {}).get("text", "")
                except Exception:
                    pass
        return full_text
    except Exception as e:
        return f"❌ Erreur: {e}"

# ── Prompts ────────────────────────────────────────────────────────────────────
SYSTEM_BASE = """Tu es un expert en mobilité durable et en innovation territoriale, travaillant avec la méthode "Territoires Ouverts" de la Fabrique des Mobilités.

Ta mission : aider des collectivités et acteurs territoriaux à concevoir des expérimentations concrètes pour résoudre des problèmes de transport, en s'appuyant sur des ressources et communs ouverts.

Principes de la méthode Territoires Ouverts :
- Favoriser les expérimentations à petite échelle d'abord
- Utiliser des ressources ouvertes (open source, open data, licences libres)
- Impliquer les acteurs locaux (associations, citoyens, entrepreneurs)
- Mesurer les effets réels sur les pratiques
- Partager les résultats et livrables

Tu réponds toujours en français, de façon structurée et actionnable."""

def prompt_decompose(problem, communs_text):
    return f"""L'utilisateur décrit ce problème de transport :
« {problem} »

Voici la liste des communs ouverts disponibles (ressources open source liées à la mobilité) :
{communs_text}

**Étape 1 - Décomposition du problème**

Analyse ce problème et réponds en JSON strict (aucun texte avant ou après) avec cette structure :
{{
  "probleme_racine": "Le vrai problème sous-jacent en 1-2 phrases",
  "hypothese_principale": "L'hypothèse à tester pour avancer",
  "sous_probleme": "Un problème plus petit, mesurable, qui peut être levé par une expérimentation à petite échelle",
  "question_cle": "La question principale à laquelle l'expérimentation doit répondre",
  "donnees_manquantes": ["donnée 1", "donnée 2"],
  "acteurs_concernes": ["acteur 1", "acteur 2"],
  "resume_une_phrase": "Résumé du sous-problème en une phrase simple"
}}"""

def prompt_experimentation(problem, sous_probleme, communs_text):
    return f"""Problème initial : « {problem} »
Sous-problème à résoudre : « {sous_probleme} »

Communs disponibles :
{communs_text}

**Étape 2 - Proposition d'expérimentation**

Propose une expérimentation concrète. Sois CONCIS : max 20 mots par champ texte, max 3 éléments par liste.
Réponds en JSON strict (aucun texte avant ou après) :
{{
  "nom_experimentation": "Nom court (5 mots max)",
  "description": "2 phrases max",
  "echelle": "Ex: 1 axe de 500m, 3 mois",
  "duree_semaines": 12,
  "objectif_mesurable": "1 phrase : quoi mesurer et comment",
  "communs_recommandes": [
    {{"nom": "Nom exact du commun FabMob", "usage": "Usage en 10 mots", "lien": "URL ou vide"}}
  ],
  "ressources_open_source_complementaires": [
    {{"nom": "Nom", "type": "logiciel/données/matériel", "usage": "10 mots max", "lien": "URL"}}
  ],
  "risques": ["risque court", "risque court"],
  "facteurs_succes": ["facteur court", "facteur court"]
}}"""

def prompt_plan(problem, sous_probleme, experimentation_json, communs_text, acteurs_data=None):
    acteurs_str = ""
    if acteurs_data and acteurs_data.get("acteurs_valides"):
        acteurs_str = f"\nActeurs locaux impliqués : {json.dumps(acteurs_data['acteurs_valides'], ensure_ascii=False)}"
    return f"""Problème : « {problem} »
Sous-problème : « {sous_probleme} »
Expérimentation retenue : {experimentation_json}{acteurs_str}

**Étape 3 - Plan**

Sois TRÈS CONCIS : max 15 mots par champ texte, max 3 actions par phase, max 5 compétences, max 6 ressources, max 4 phases, max 3 indicateurs.
Réponds en JSON strict (aucun texte avant ou après) :
{{
  "competences_requises": [
    {{"competence": "Nom court", "role": "Rôle en 10 mots", "source_possible": "Interne/Asso/Bénévole/Prestataire", "estimation_jours": 5}}
  ],
  "ressources_materielles": [
    {{"ressource": "Nom", "quantite": "X", "cout_estime_euros": 500, "type_licence": "Open source/Libre/Commercial", "fournisseur_possible": "Type"}}
  ],
  "phases": [
    {{"phase": "Nom phase", "duree_semaines": 2, "actions": ["action 1", "action 2", "action 3"], "livrable": "Livrable en 8 mots"}}
  ],
  "budget_total": {{
    "ressources_humaines_euros": 5000,
    "ressources_materielles_euros": 2000,
    "evenements_communication_euros": 500,
    "total_euros": 7500,
    "note": "Estimation indicative."
  }},
  "besoins_territoire": ["besoin 1 court", "besoin 2 court"],
  "indicateurs_succes": [
    {{"indicateur": "Nom", "mesure": "Comment", "cible": "Valeur"}}
  ],
  "prochaine_etape_immediate": "Action dès demain en 10 mots"
}}"""


# ── Recherche Transiscope ──────────────────────────────────────────────────────
def geocode_commune(query):
    """Retourne (lat, lng, label) pour une commune via api-adresse.data.gouv.fr"""
    try:
        resp = requests.get(
            "https://api-adresse.data.gouv.fr/search/",
            params={"q": query, "type": "municipality", "limit": 5},
            timeout=10
        )
        if not resp.ok:
            return None
        features = resp.json().get("features", [])
        if not features:
            return None
        f = features[0]
        lng, lat = f["geometry"]["coordinates"]
        label = f["properties"].get("label", query)
        return {"lat": lat, "lng": lng, "label": label}
    except Exception:
        return None

def autocomplete_communes(query):
    """Retourne une liste de communes pour l'autocomplétion."""
    try:
        resp = requests.get(
            "https://api-adresse.data.gouv.fr/search/",
            params={"q": query, "type": "municipality", "limit": 8},
            timeout=8
        )
        if not resp.ok:
            return []
        features = resp.json().get("features", [])
        return [
            {
                "label": f["properties"].get("label", ""),
                "postcode": f["properties"].get("postcode", ""),
                "city": f["properties"].get("city", ""),
                "lat": f["geometry"]["coordinates"][1],
                "lng": f["geometry"]["coordinates"][0],
            }
            for f in features
        ]
    except Exception:
        return []

def parse_transiscope_element(el):
    """Normalise un élément Transiscope (différents formats possibles)."""
    addr = el.get("address", {})
    if isinstance(addr, str):
        adresse, ville = addr, ""
    elif isinstance(addr, dict):
        adresse = addr.get("streetAddress", addr.get("street", ""))
        ville = addr.get("addressLocality", addr.get("city", ""))
    else:
        adresse, ville = "", ""
    el_id = el.get("id", el.get("@id", ""))
    return {
        "nom": el.get("name", el.get("nom", el.get("title", "Sans nom"))),
        "description": (el.get("description", el.get("shortDescription", "")))[:250],
        "adresse": adresse,
        "ville": ville,
        "telephone": el.get("telephone", el.get("tel", "")),
        "email": el.get("email", ""),
        "url": el.get("website", el.get("url", el.get("siteWeb", ""))),
        "lien_carte": f"https://transiscope.gogocarto.fr/map/{el_id}" if el_id else "",
        "categories": el.get("categories", []),
        "lat": el.get("geo", {}).get("latitude", el.get("lat", None)) if isinstance(el.get("geo"), dict) else el.get("lat", None),
        "lng": el.get("geo", {}).get("longitude", el.get("lng", None)) if isinstance(el.get("geo"), dict) else el.get("lng", None),
    }

def search_transiscope_by_bounds(lat, lng, radius_km=15, limit=25, categories=None):
    """
    Recherche Transiscope par zone geographique (boundsJson).
    L'API GoGoCarto accepte aussi des categories[]=valeur.
    """
    import math
    from urllib.parse import urlencode
    delta_lat = radius_km / 111.0
    delta_lng = radius_km / (111.0 * math.cos(math.radians(lat)))
    bounds_param = json.dumps([{
        "southWest": {"lat": round(lat - delta_lat, 6), "lng": round(lng - delta_lng, 6)},
        "northEast": {"lat": round(lat + delta_lat, 6), "lng": round(lng + delta_lng, 6)}
    }])
    base_url = "https://transiscope.gogocarto.fr/api/elements.json"
    # Construire l'URL avec les parametres (categories[] repetes si besoin)
    qs = urlencode({"limit": limit, "boundsJson": bounds_param})
    if categories:
        qs += "&" + "&".join(f"categories[]={c}" for c in categories)
    full_url = f"{base_url}?{qs}"
    try:
        resp = requests.get(full_url, timeout=20)
        if not resp.ok:
            return [], f"Erreur HTTP {resp.status_code} : {resp.text[:200]}"
        raw = resp.json()
        # Extraire selon format GoGoCarto
        # Reponse reelle : {"licence":..., "ontology":..., "data": [...]}
        def extract_elements(obj):
            if isinstance(obj, list):
                return obj
            if isinstance(obj, dict):
                d = obj.get("data")
                if isinstance(d, list):      # <- cas Transiscope reel
                    return d
                if isinstance(d, dict):
                    els = d.get("elements", [])
                    if els:
                        return els
                for key in ("elements", "features", "items", "results"):
                    if key in obj and isinstance(obj[key], list):
                        return obj[key]
            return []
        elements = extract_elements(raw)
        # Aplatir si liste de listes
        flat = []
        for el in elements:
            if isinstance(el, dict):
                flat.append(el)
            elif isinstance(el, list):
                flat.extend(e for e in el if isinstance(e, dict))
        results = [parse_transiscope_element(el) for el in flat
                   if el.get("name") or el.get("nom") or el.get("title")]
        debug = None if results else f"Reponse brute ({type(raw).__name__}) : {str(raw)[:400]}"
        return results[:limit], debug
    except Exception as e:
        return [], str(e)

def prompt_valider_acteurs(experimentation_json, acteurs_utilisateur, acteurs_transiscope):
    acteurs_str = json.dumps(acteurs_utilisateur, ensure_ascii=False)
    transiscope_str = json.dumps(acteurs_transiscope[:8], ensure_ascii=False)
    return f"""Expérimentation : {experimentation_json}

Acteurs identifiés par l'utilisateur :
{acteurs_str}

Acteurs trouvés sur Transiscope (économie sociale locale) :
{transiscope_str}

Analyse la cohérence et enrichis. Réponds en JSON strict, CONCIS (max 10 mots par champ) :
{{
  "acteurs_valides": [
    {{
      "nom": "Nom",
      "type": "Association/Entreprise/Collectif",
      "role_dans_xp": "Rôle en 8 mots",
      "ressources_apportees": ["ressource 1", "ressource 2"],
      "coherence": "Forte/Moyenne/Faible",
      "commentaire": "1 phrase max",
      "source": "Utilisateur/Transiscope"
    }}
  ],
  "acteurs_transiscope_suggeres": [
    {{
      "nom": "Nom",
      "type": "Type",
      "role_potentiel": "Rôle en 8 mots",
      "ressources_potentielles": ["ressource 1"],
      "lien": "URL Transiscope"
    }}
  ],
  "synergies_identifiees": ["synergie 1 en 10 mots", "synergie 2"],
  "avertissements": ["point de vigilance si pertinent"]
}}"""

# ── Parsing JSON robuste ───────────────────────────────────────────────────────
def parse_json_response(text):
    """Extrait le JSON d'une réponse même si entouré de texte."""
    text = text.strip()
    # Remove markdown code blocks if present
    text = re.sub(r'^```json\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'^```\s*', '', text, flags=re.MULTILINE)
    text = text.strip()
    try:
        return json.loads(text), None
    except json.JSONDecodeError as e:
        # Try to find JSON object
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group()), None
            except:
                pass
        return None, str(e)

# ── UI Components ──────────────────────────────────────────────────────────────
def render_step_badge(n, label, active=False, done=False):
    color = "#10b981" if done else ("#3b82f6" if active else "#6b7280")
    bg = "#d1fae5" if done else ("#dbeafe" if active else "#f3f4f6")
    icon = "✓" if done else str(n)
    st.markdown(f"""
    <div style="display:inline-flex;align-items:center;gap:8px;padding:6px 14px;
                border-radius:20px;background:{bg};margin:4px;">
        <span style="background:{color};color:white;border-radius:50%;
                     width:22px;height:22px;display:inline-flex;align-items:center;
                     justify-content:center;font-size:12px;font-weight:bold;">{icon}</span>
        <span style="color:{color};font-weight:{'bold' if active else 'normal'};font-size:14px;">{label}</span>
    </div>""", unsafe_allow_html=True)

def card(title, content, color="#3b82f6", icon=""):
    st.markdown(f"""
    <div style="border-left:4px solid {color};padding:12px 16px;
                background:#f8fafc;border-radius:0 8px 8px 0;margin:8px 0;">
        <strong style="color:{color};">{icon} {title}</strong>
        <div style="margin-top:6px;color:#374151;">{content}</div>
    </div>""", unsafe_allow_html=True)

# ── Main App ───────────────────────────────────────────────────────────────────
def main():
    # Header
    st.markdown("""
    <div style="background:linear-gradient(135deg,#1e40af,#0d9488);padding:24px 32px;
                border-radius:12px;margin-bottom:24px;">
        <h1 style="color:white;margin:0;font-size:28px;">🚀 Territoires Ouverts</h1>
        <p style="color:#bfdbfe;margin:8px 0 0 0;font-size:16px;">
            Outil d'aide à la conception d'expérimentations de mobilité
        </p>
        <p style="color:#99f6e4;margin:4px 0 0 0;font-size:13px;">
            Basé sur la méthode FabMob · 346 communs ouverts indexés
        </p>
    </div>
    """, unsafe_allow_html=True)

    # ── Récupération de la clé API (Secrets Streamlit en priorité) ───────────
    api_key = st.secrets.get("ANTHROPIC_API_KEY", "") if hasattr(st, "secrets") else ""

    # Sidebar: info (+ saisie clé seulement si absente des secrets)
    with st.sidebar:
        if not api_key:
            st.markdown("### ⚙️ Configuration")
            api_key = st.text_input(
                "Clé API Anthropic",
                type="password",
                placeholder="sk-ant-...",
                help="Obtenez votre clé sur console.anthropic.com"
            )
            st.caption("💡 Pour ne plus avoir à la saisir, ajoutez `ANTHROPIC_API_KEY` dans les Secrets Streamlit.")
        st.markdown("---")
        st.markdown("### 📖 À propos")
        st.markdown("""
Cette application utilise :
- **346 communs** de la Fabrique des Mobilités
- **Méthode Territoires Ouverts** (FabMob 2022)
- **Claude (Anthropic)** pour l'analyse IA

**Étapes :**
1. Décrire votre problème
2. Valider la décomposition
3. Valider l'expérimentation
4. Obtenir le plan complet
        """)
        st.markdown("---")
        communs = load_communs()
        st.metric("Communs disponibles", len(communs))

    # Load communs
    communs = load_communs()
    if not communs:
        st.error("❌ Impossible de charger les communs. Vérifiez que le fichier XML est présent.")
        st.stop()

    # Initialize session state
    for key in ['step', 'problem', 'decomposition', 'experimentation', 'plan', 'communs_context']:
        if key not in st.session_state:
            st.session_state[key] = None
    if st.session_state.step is None:
        st.session_state.step = 1

    # Progress indicators
    steps = [
        (1, "Problème"),
        (2, "Décomposition"),
        (3, "Expérimentation"),
        (4, "Acteurs locaux"),
        (5, "Plan complet"),
    ]
    cols = st.columns(len(steps))
    for col, (n, label) in zip(cols, steps):
        with col:
            done = st.session_state.step > n
            active = st.session_state.step == n
            render_step_badge(n, label, active=active, done=done)

    st.markdown("---")

    # ── STEP 1 : Saisie du problème ──────────────────────────────────────────
    if st.session_state.step == 1:
        st.markdown("## 🎯 Étape 1 — Décrivez votre problème de transport")
        st.markdown("""
        Décrivez en quelques phrases le problème de mobilité que vous souhaitez résoudre
        sur votre territoire. Soyez aussi précis que possible sur le contexte.
        """)

        examples = [
            "Je veux développer la pratique du vélo dans ma commune",
            "Je veux réduire l'usage de la voiture individuelle en centre-ville",
            "Je veux améliorer le covoiturage entre les zones rurales et la gare",
            "Je veux faciliter les déplacements des personnes âgées dans mon territoire",
        ]
        st.markdown("**Exemples :**")
        ex_cols = st.columns(2)
        for i, ex in enumerate(examples):
            with ex_cols[i % 2]:
                if st.button(f"💡 {ex}", key=f"ex_{i}", use_container_width=True):
                    st.session_state['prefill_problem'] = ex

        problem_default = st.session_state.get('prefill_problem', '')
        problem = st.text_area(
            "Votre problème de transport",
            value=problem_default,
            height=120,
            placeholder="Ex : Je veux développer la pratique du vélo dans ma commune de 15 000 habitants. Actuellement peu de cyclistes, manque de données et d'infrastructures.",
        )

        territory = st.text_input(
            "Votre territoire (optionnel)",
            placeholder="Ex : Commune de 15 000 hab., zone périurbaine, département de l'Isère..."
        )

        if territory:
            problem = f"{problem}\nContexte territorial : {territory}"

        if st.button("▶️ Analyser ce problème", type="primary", disabled=not problem.strip() or not api_key):
            if not api_key:
                st.warning("⚠️ Veuillez entrer votre clé API Anthropic dans la barre latérale.")
            elif not problem.strip():
                st.warning("⚠️ Veuillez décrire votre problème.")
            else:
                with st.spinner("🔍 Analyse du problème en cours..."):
                    # Select relevant communs (first 80 for context)
                    communs_text = format_communs_for_prompt(communs[:80])
                    msg = prompt_decompose(problem, communs_text)
                    response = call_claude(
                        [{"role": "user", "content": msg}],
                        SYSTEM_BASE,
                        api_key
                    )
                    data, err = parse_json_response(response)
                    if data:
                        st.session_state.problem = problem
                        st.session_state.decomposition = data
                        st.session_state.communs_context = communs_text
                        st.session_state.step = 2
                        st.rerun()
                    else:
                        st.error(f"Erreur de parsing : {err}")
                        st.code(response)

    # ── STEP 2 : Décomposition du problème ──────────────────────────────────
    elif st.session_state.step == 2:
        st.markdown("## 🔍 Étape 2 — Décomposition du problème")
        d = st.session_state.decomposition
        p = st.session_state.problem

        st.markdown(f"**Problème initial :** _{p}_")
        st.markdown("---")

        col1, col2 = st.columns(2)
        with col1:
            card("Problème racine identifié", d.get('probleme_racine', ''), "#dc2626", "🎯")
            card("Hypothèse principale", d.get('hypothese_principale', ''), "#7c3aed", "💡")
            card("Sous-problème à explorer", d.get('sous_probleme', ''), "#059669", "🔬")

        with col2:
            card("Question clé de l'expérimentation", d.get('question_cle', ''), "#d97706", "❓")

            if d.get('donnees_manquantes'):
                st.markdown("**📊 Données manquantes identifiées :**")
                for dm in d['donnees_manquantes']:
                    st.markdown(f"- {dm}")

            if d.get('acteurs_concernes'):
                st.markdown("**👥 Acteurs concernés :**")
                for a in d['acteurs_concernes']:
                    st.markdown(f"- {a}")

        st.info(f"💬 **En résumé :** {d.get('resume_une_phrase', '')}")

        st.markdown("---")
        st.markdown("### ✅ Validez cette décomposition")

        col_a, col_b = st.columns([3, 1])
        with col_a:
            validation = st.radio(
                "Cette décomposition correspond-elle à votre problème ?",
                ["Oui, je valide", "Non, je veux affiner"],
                index=0
            )
        with col_b:
            if st.button("⬅️ Recommencer", use_container_width=True):
                st.session_state.step = 1
                st.rerun()

        if validation == "Non, je veux affiner":
            ajout = st.text_area("Précisions supplémentaires :", placeholder="Ce qui manque ou est inexact...")
            if st.button("🔄 Relancer l'analyse", type="primary", disabled=not ajout.strip() or not api_key):
                with st.spinner("Réanalyse..."):
                    new_problem = p + "\n\nPrécisions : " + ajout
                    msg = prompt_decompose(new_problem, st.session_state.communs_context)
                    response = call_claude([{"role": "user", "content": msg}], SYSTEM_BASE, api_key)
                    data, err = parse_json_response(response)
                    if data:
                        st.session_state.problem = new_problem
                        st.session_state.decomposition = data
                        st.rerun()
                    else:
                        st.error(f"Erreur: {err}")
        else:
            if st.button("▶️ Passer à la proposition d'expérimentation", type="primary", disabled=not api_key):
                with st.spinner("🧪 Conception de l'expérimentation..."):
                    msg = prompt_experimentation(
                        st.session_state.problem,
                        d.get('sous_probleme', ''),
                        st.session_state.communs_context
                    )
                    response = call_claude([{"role": "user", "content": msg}], SYSTEM_BASE, api_key)
                    data, err = parse_json_response(response)
                    if data:
                        st.session_state.experimentation = data
                        st.session_state.step = 3
                        st.rerun()
                    else:
                        st.error(f"Erreur: {err}")
                        st.code(response)

    # ── STEP 3 : Proposition d'expérimentation ───────────────────────────────
    elif st.session_state.step == 3:
        st.markdown("## 🧪 Étape 3 — Proposition d'expérimentation")
        e = st.session_state.experimentation

        # Header card
        st.markdown(f"""
        <div style="background:linear-gradient(135deg,#0d9488,#0891b2);padding:20px 24px;
                    border-radius:12px;margin-bottom:16px;color:white;">
            <h3 style="margin:0;color:white;">🔬 {e.get('nom_experimentation', 'Expérimentation proposée')}</h3>
            <p style="margin:8px 0 0 0;opacity:0.9;">{e.get('description', '')}</p>
            <div style="margin-top:12px;display:flex;gap:20px;">
                <span>📏 Échelle : <strong>{e.get('echelle', 'À définir')}</strong></span>
                <span>⏱️ Durée : <strong>{e.get('duree_semaines', '?')} semaines</strong></span>
            </div>
        </div>
        """, unsafe_allow_html=True)

        card("Objectif mesurable", e.get('objectif_mesurable', ''), "#059669", "📊")

        col1, col2 = st.columns(2)

        with col1:
            st.markdown("#### 🔓 Communs FabMob recommandés")
            communs_reco = e.get('communs_recommandes', [])
            if communs_reco:
                for c in communs_reco:
                    with st.expander(f"📦 {c.get('nom', '')}"):
                        st.markdown(f"**Usage :** {c.get('usage', '')}")
                        if c.get('lien'):
                            st.markdown(f"🔗 [Accéder]({c.get('lien')})")
            else:
                st.info("Aucun commun spécifique identifié")

        with col2:
            st.markdown("#### 🌐 Ressources open source complémentaires")
            resources = e.get('ressources_open_source_complementaires', [])
            if resources:
                for r in resources:
                    with st.expander(f"🛠️ {r.get('nom', '')} ({r.get('type', '')})"):
                        st.markdown(f"**Usage :** {r.get('usage', '')}")
                        if r.get('lien'):
                            st.markdown(f"🔗 [Accéder]({r.get('lien')})")
            else:
                st.info("Aucune ressource complémentaire identifiée")

        col3, col4 = st.columns(2)
        with col3:
            if e.get('facteurs_succes'):
                st.markdown("#### ✅ Facteurs de succès")
                for f in e['facteurs_succes']:
                    st.markdown(f"- ✓ {f}")
        with col4:
            if e.get('risques'):
                st.markdown("#### ⚠️ Risques identifiés")
                for r in e['risques']:
                    st.markdown(f"- ⚠ {r}")

        st.markdown("---")
        st.markdown("### ✅ Validez cette expérimentation")

        # Persist radio choice across reruns so it doesn't reset after st.rerun()
        if 'exp_validation' not in st.session_state:
            st.session_state.exp_validation = "Oui, je valide"

        col_a, col_b = st.columns([3, 1])
        with col_a:
            validation = st.radio(
                "Cette expérimentation vous convient-elle ?",
                ["Oui, je valide", "Non, je veux l'ajuster"],
                index=0 if st.session_state.exp_validation == "Oui, je valide" else 1,
                key="radio_exp_validation"
            )
            st.session_state.exp_validation = validation
        with col_b:
            if st.button("⬅️ Retour", use_container_width=True):
                st.session_state.exp_validation = "Oui, je valide"
                st.session_state.step = 2
                st.rerun()

        if validation == "Non, je veux l'ajuster":
            ajout = st.text_area("Vos ajustements :", key="ajout_exp",
                                  placeholder="Ex : trop grande échelle, manque tel outil...")
            if st.button("🔄 Revoir l'expérimentation", type="primary",
                         disabled=not (ajout or "").strip() or not api_key):
                with st.spinner("Révision en cours..."):
                    msg = prompt_experimentation(
                        st.session_state.problem,
                        st.session_state.decomposition.get('sous_probleme', '') + "\n\nAjustements demandés: " + ajout,
                        st.session_state.communs_context
                    )
                    response = call_claude([{"role": "user", "content": msg}], SYSTEM_BASE, api_key)
                    if response.startswith("❌"):
                        st.error(response)
                    else:
                        data, err = parse_json_response(response)
                        if data:
                            st.session_state.experimentation = data
                            st.session_state.exp_validation = "Oui, je valide"
                            st.rerun()
                        else:
                            st.error(f"Erreur de parsing : {err}")
                            st.code(response[:500])
        else:
            if st.button("▶️ Identifier les acteurs locaux", type="primary"):
                st.session_state.exp_validation = "Oui, je valide"
                st.session_state.step = 4
                st.rerun()


    # ── STEP 4 : Acteurs locaux ──────────────────────────────────────────────────
    elif st.session_state.step == 4:
        st.markdown("## 🤝 Étape 4 — Acteurs locaux et ressources")
        st.markdown("""
        Identifiez les associations, entreprises ou collectifs de votre territoire qui pourraient s'impliquer.
        L'outil recherche aussi sur **Transiscope** (carte des alternatives locales) par zone géographique.
        """)

        e = st.session_state.experimentation

        # ── Recherche Transiscope par commune ───────────────────────────────
        st.markdown("### 🗺️ Localisation pour Transiscope")

        for k in ['commune_label', 'commune_lat', 'commune_lng', 'transiscope_results', 'acteurs_utilisateur']:
            if k not in st.session_state:
                st.session_state[k] = None if k != 'acteurs_utilisateur' else []

        col_geo1, col_geo2, col_geo3 = st.columns([3, 1, 1])
        with col_geo1:
            commune_input = st.text_input(
                "🏙️ Commune ou code postal",
                placeholder="Ex: Mouans-Sartoux, 06370, Grenoble...",
                key="commune_input_field"
            )
        with col_geo2:
            radius_km = st.selectbox("Rayon", [5, 10, 15, 20, 30], index=1, key="radius_select")
            st.caption("km autour")
        with col_geo3:
            st.markdown("<br>", unsafe_allow_html=True)
            btn_geocode = st.button("📍 Localiser", use_container_width=True)

        if btn_geocode and commune_input.strip():
            with st.spinner("Géolocalisation..."):
                geo = geocode_commune(commune_input.strip())
                if geo:
                    st.session_state.commune_label = geo["label"]
                    st.session_state.commune_lat = geo["lat"]
                    st.session_state.commune_lng = geo["lng"]
                    st.session_state.transiscope_results = None  # reset results
                    st.rerun()
                else:
                    st.error("Commune non trouvée. Essayez avec le code postal ou un nom différent.")

        # Show geocode result + search button
        if st.session_state.commune_lat:
            st.success(f"📍 **{st.session_state.commune_label}** — rayon {radius_km} km")
            col_srch1, col_srch2 = st.columns([3,1])
            with col_srch2:
                do_transiscope = st.button("🔎 Chercher sur Transiscope", use_container_width=True, type="primary")
            with col_srch1:
                st.caption(f"Lat {st.session_state.commune_lat:.4f}, Lng {st.session_state.commune_lng:.4f}")

            if do_transiscope:
                with st.spinner(f"Recherche dans un rayon de {radius_km} km autour de {st.session_state.commune_label}..."):
                    results, err = search_transiscope_by_bounds(
                        st.session_state.commune_lat,
                        st.session_state.commune_lng,
                        radius_km=radius_km,
                        limit=25,
                        categories=None  # None = tous les acteurs
                    )
                    st.session_state.transiscope_results = results
                    st.session_state.transiscope_err = err

        if st.session_state.transiscope_results is not None:
            results = st.session_state.transiscope_results
            err = st.session_state.get('transiscope_err')
            if err:
                st.warning(f"⚠️ API Transiscope : {err}")
            st.markdown("---")
            if results:
                st.markdown(f"**{len(results)} acteur(s) trouvé(s) sur Transiscope dans cette zone :**")
                for r in results:
                    label = f"🏢 {r['nom']}"
                    if r.get('ville'):
                        label += f" — {r['ville']}"
                    with st.expander(label):
                        if r.get('description'):
                            st.markdown(r['description'])
                        cols_r = st.columns(3)
                        if r.get('adresse'):
                            cols_r[0].markdown(f"📍 {r['adresse']}")
                        if r.get('telephone'):
                            cols_r[1].markdown(f"📞 {r['telephone']}")
                        if r.get('email'):
                            cols_r[2].markdown(f"✉️ {r['email']}")
                        if r.get('url'):
                            st.markdown(f"🔗 [{r['url']}]({r['url']})")
                        if r.get('lien_carte'):
                            st.markdown(f"[👁️ Voir sur Transiscope]({r['lien_carte']})")
                        if r.get('categories'):
                            st.caption(f"Catégories : {', '.join(str(c) for c in r['categories'][:5])}")
            else:
                st.info(f"Aucun acteur trouvé dans un rayon de {radius_km} km. "
                        f"Essayez d'augmenter le rayon.")
                err_msg = st.session_state.get("transiscope_err")
                if err_msg:
                    with st.expander("🔍 Détail réponse API (debug)"):
                        st.code(err_msg)
                st.markdown("💡 [Vérifier manuellement sur Transiscope](https://transiscope.gogocarto.fr/)")

        # ── Acteurs connus de l'utilisateur ─────────────────────────────────
        st.markdown("---")
        st.markdown("### 👥 Acteurs que vous connaissez déjà")
        st.caption("Ajoutez les associations ou entreprises locales que vous souhaitez impliquer.")

        if st.session_state.acteurs_utilisateur is None:
            st.session_state.acteurs_utilisateur = []

        with st.expander("➕ Ajouter un acteur", expanded=len(st.session_state.acteurs_utilisateur) == 0):
            col_a1, col_a2 = st.columns(2)
            with col_a1:
                new_nom = st.text_input("Nom de l'acteur", key="new_nom", placeholder="Ex: Choisir le vélo")
                new_type = st.selectbox("Type", ["Association", "Entreprise", "Collectif citoyen", "Établissement public", "Autre"], key="new_type")
            with col_a2:
                new_ressources = st.text_area("Ressources qu'il pourrait apporter",
                                               key="new_ressources",
                                               placeholder="Ex: Bénévoles formés, vélos, local de réunion...",
                                               height=80)
                new_contact = st.text_input("Contact (optionnel)", key="new_contact", placeholder="Email ou téléphone")

            if st.button("✅ Ajouter cet acteur", key="add_actor"):
                if new_nom.strip():
                    st.session_state.acteurs_utilisateur.append({
                        "nom": new_nom.strip(),
                        "type": new_type,
                        "ressources": [r.strip() for r in new_ressources.split(",") if r.strip()],
                        "contact": new_contact.strip(),
                    })
                    st.rerun()
                else:
                    st.warning("Veuillez saisir un nom.")

        if st.session_state.acteurs_utilisateur:
            st.markdown(f"**{len(st.session_state.acteurs_utilisateur)} acteur(s) identifié(s) :**")
            for i, act in enumerate(st.session_state.acteurs_utilisateur):
                col_x, col_del = st.columns([5, 1])
                with col_x:
                    ressources_str = ", ".join(act.get("ressources", [])) or "Non précisé"
                    st.markdown(f"- **{act['nom']}** ({act['type']}) — {ressources_str}")
                with col_del:
                    if st.button("🗑️", key=f"del_{i}"):
                        st.session_state.acteurs_utilisateur.pop(i)
                        st.rerun()

        st.markdown("---")
        col_back, col_next = st.columns([1, 3])
        with col_back:
            if st.button("⬅️ Retour", use_container_width=True):
                st.session_state.step = 3
                st.session_state.transiscope_results = None
                st.rerun()
        with col_next:
            btn_label = "▶️ Valider et générer le plan complet"
            if st.button(btn_label, type="primary", use_container_width=True, disabled=not api_key):
                with st.spinner("🤝 Analyse des acteurs et génération du plan..."):
                    # Validate actors with Claude
                    transiscope_for_claude = st.session_state.transiscope_results or []
                    msg_acteurs = prompt_valider_acteurs(
                        json.dumps(st.session_state.experimentation, ensure_ascii=False),
                        st.session_state.acteurs_utilisateur,
                        transiscope_for_claude
                    )
                    response_acteurs = call_claude([{"role": "user", "content": msg_acteurs}], SYSTEM_BASE, api_key)
                    acteurs_data, err = parse_json_response(response_acteurs)
                    if not acteurs_data:
                        acteurs_data = {"acteurs_valides": st.session_state.acteurs_utilisateur}

                    st.session_state.acteurs_valides = acteurs_data

                    # Generate plan with actors integrated
                    msg_plan = prompt_plan(
                        st.session_state.problem,
                        st.session_state.decomposition.get('sous_probleme', ''),
                        json.dumps(st.session_state.experimentation, ensure_ascii=False),
                        st.session_state.communs_context,
                        acteurs_data
                    )
                    response_plan = call_claude([{"role": "user", "content": msg_plan}], SYSTEM_BASE, api_key)
                    plan_data, err2 = parse_json_response(response_plan)
                    if plan_data:
                        st.session_state.plan = plan_data
                        st.session_state.step = 5
                        st.rerun()
                    else:
                        st.error(f"Erreur plan: {err2}")
                        st.code(response_plan)

    # ── STEP 5 : Plan complet ─────────────────────────────────────────────────
    elif st.session_state.step == 5:
        st.markdown("## 📋 Plan complet de l'expérimentation")
        pl = st.session_state.plan
        e = st.session_state.experimentation

        # Summary header
        budget = pl.get('budget_total', {})
        total = budget.get('total_euros', 0)
        duree = e.get('duree_semaines', '?')
        phases = pl.get('phases', [])

        st.markdown(f"""
        <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin-bottom:24px;">
            <div style="background:#dbeafe;padding:16px;border-radius:10px;text-align:center;">
                <div style="font-size:28px;font-weight:bold;color:#1d4ed8;">{total:,} €</div>
                <div style="color:#1d4ed8;font-size:13px;">Budget estimé</div>
            </div>
            <div style="background:#d1fae5;padding:16px;border-radius:10px;text-align:center;">
                <div style="font-size:28px;font-weight:bold;color:#065f46;">{duree} sem.</div>
                <div style="color:#065f46;font-size:13px;">Durée totale</div>
            </div>
            <div style="background:#fef3c7;padding:16px;border-radius:10px;text-align:center;">
                <div style="font-size:28px;font-weight:bold;color:#92400e;">{len(phases)}</div>
                <div style="color:#92400e;font-size:13px;">Phases</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        tab0, tab1, tab2, tab3, tab4, tab5 = st.tabs([
            "🤝 Acteurs locaux", "👥 Compétences", "📦 Ressources", "🗓️ Planning", "💰 Budget", "🎯 Indicateurs"
        ])

        with tab0:
            st.markdown("### Acteurs locaux impliqués")
            acteurs_data = st.session_state.get('acteurs_valides', {})
            acteurs = acteurs_data.get('acteurs_valides', [])
            if acteurs:
                for act in acteurs:
                    coherence = act.get('coherence', '')
                    color = "#10b981" if coherence == "Forte" else "#f59e0b" if coherence == "Moyenne" else "#6b7280"
                    with st.expander(f"🏢 {act.get('nom', '')} ({act.get('type', '')}) — Cohérence : {coherence}"):
                        st.markdown(f"**Rôle :** {act.get('role_dans_xp', '')}")
                        ressources = act.get('ressources_apportees', [])
                        if ressources:
                            st.markdown("**Ressources apportées :**")
                            for r in ressources:
                                st.markdown(f"- {r}")
                        if act.get('commentaire'):
                            st.info(act['commentaire'])
                        source = act.get('source', '')
                        st.caption(f"Source : {source}")
            suggeres = acteurs_data.get('acteurs_transiscope_suggeres', [])
            if suggeres:
                st.markdown("#### 💡 Autres acteurs suggérés par Transiscope")
                for s in suggeres:
                    with st.expander(f"🔍 {s.get('nom', '')} — {s.get('type', '')}"):
                        st.markdown(f"**Rôle potentiel :** {s.get('role_potentiel', '')}")
                        for r in s.get('ressources_potentielles', []):
                            st.markdown(f"- {r}")
                        if s.get('lien'):
                            st.markdown(f"[Voir sur Transiscope]({s['lien']})")
            synergies = acteurs_data.get('synergies_identifiees', [])
            if synergies:
                st.markdown("#### ⚡ Synergies identifiées")
                for syn in synergies:
                    st.markdown(f"- {syn}")
            if not acteurs and not suggeres:
                st.info("Aucun acteur local n'a été identifié pour cette expérimentation.")

        with tab1:
            st.markdown("### Compétences requises")
            competences = pl.get('competences_requises', [])
            if competences:
                for comp in competences:
                    with st.expander(f"👤 {comp.get('competence', '')} — {comp.get('estimation_jours', '?')} j."):
                        col_a, col_b = st.columns(2)
                        with col_a:
                            st.markdown(f"**Rôle :** {comp.get('role', '')}")
                        with col_b:
                            source = comp.get('source_possible', '')
                            color = "#10b981" if "Bénévole" in source or "Association" in source else "#6b7280"
                            st.markdown(f"**Source :** <span style='color:{color}'>{source}</span>", unsafe_allow_html=True)

        with tab2:
            st.markdown("### Ressources matérielles et logicielles")
            ressources = pl.get('ressources_materielles', [])
            if ressources:
                for r in ressources:
                    licence = r.get('type_licence', '')
                    badge_color = "#10b981" if "Open" in licence or "Libre" in licence else "#f59e0b"
                    with st.expander(f"📦 {r.get('ressource', '')} — {r.get('cout_estime_euros', '?')} €"):
                        cols = st.columns(3)
                        cols[0].markdown(f"**Quantité :** {r.get('quantite', '')}")
                        cols[1].markdown(f"**Licence :** <span style='color:{badge_color}'>{licence}</span>", unsafe_allow_html=True)
                        cols[2].markdown(f"**Fournisseur :** {r.get('fournisseur_possible', '')}")

            besoins = pl.get('besoins_territoire', [])
            if besoins:
                st.markdown("#### 🏛️ Besoins auprès du territoire")
                for b in besoins:
                    st.markdown(f"- {b}")

        with tab3:
            st.markdown("### Planning par phases")
            semaine_courante = 1
            for i, phase in enumerate(phases):
                duree_phase = phase.get('duree_semaines', 2)
                with st.expander(
                    f"Phase {i+1} : {phase.get('phase', '')} "
                    f"(S{semaine_courante}–S{semaine_courante+duree_phase-1}) — {duree_phase} semaines"
                ):
                    st.markdown(f"**Livrable :** {phase.get('livrable', '')}")
                    st.markdown("**Actions :**")
                    for action in phase.get('actions', []):
                        st.markdown(f"- {action}")
                semaine_courante += duree_phase

        with tab4:
            st.markdown("### Estimation budgétaire")
            budget = pl.get('budget_total', {})
            postes = [
                ("Ressources humaines", budget.get('ressources_humaines_euros', 0), "#3b82f6"),
                ("Ressources matérielles", budget.get('ressources_materielles_euros', 0), "#10b981"),
                ("Événements & communication", budget.get('evenements_communication_euros', 0), "#f59e0b"),
            ]
            for nom, montant, color in postes:
                total_budget = budget.get('total_euros', 1) or 1
                pct = int(montant / total_budget * 100)
                st.markdown(f"""
                <div style="margin:8px 0;">
                    <div style="display:flex;justify-content:space-between;">
                        <span>{nom}</span><span><strong>{montant:,} €</strong> ({pct}%)</span>
                    </div>
                    <div style="background:#e5e7eb;border-radius:4px;height:8px;margin-top:4px;">
                        <div style="background:{color};width:{pct}%;height:8px;border-radius:4px;"></div>
                    </div>
                </div>
                """, unsafe_allow_html=True)
            st.markdown(f"---")
            st.markdown(f"### 💰 Total estimé : **{budget.get('total_euros', 0):,} €**")
            if budget.get('note'):
                st.info(f"ℹ️ {budget['note']}")

        with tab5:
            st.markdown("### Indicateurs de succès")
            indicateurs = pl.get('indicateurs_succes', [])
            if indicateurs:
                for ind in indicateurs:
                    with st.expander(f"📊 {ind.get('indicateur', '')}"):
                        col_a, col_b = st.columns(2)
                        col_a.markdown(f"**Mesure :** {ind.get('mesure', '')}")
                        col_b.markdown(f"**Cible :** {ind.get('cible', '')}")

        # Next step
        st.markdown("---")
        prochaine = pl.get('prochaine_etape_immediate', '')
        if prochaine:
            st.success(f"🚀 **Prochaine étape immédiate :** {prochaine}")

        # Export
        col_exp1, col_exp2 = st.columns([1, 1])
        with col_exp1:
            export_data = {
                "probleme": st.session_state.problem,
                "decomposition": st.session_state.decomposition,
                "experimentation": st.session_state.experimentation,
                "plan": st.session_state.plan,
            }
            st.download_button(
                "⬇️ Télécharger le plan (JSON)",
                data=json.dumps(export_data, ensure_ascii=False, indent=2),
                file_name="plan_experimentation.json",
                mime="application/json",
                use_container_width=True
            )
        with col_exp2:
            if st.button("🔄 Nouvelle expérimentation", use_container_width=True):
                for key in ['step', 'problem', 'decomposition', 'experimentation', 'plan']:
                    st.session_state[key] = None
                st.session_state.step = 1
                st.rerun()

if __name__ == "__main__":
    main()
