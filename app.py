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
MODEL = "claude-sonnet-4-20250514"

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
        "max_tokens": 2000,
        "system": system_prompt,
        "messages": messages,
    }
    try:
        response = requests.post(ANTHROPIC_API_URL, headers=headers, json=payload, timeout=60)
        response.raise_for_status()
        data = response.json()
        return data["content"][0]["text"]
    except requests.exceptions.HTTPError as e:
        if response.status_code == 401:
            return "❌ Clé API invalide. Vérifiez votre clé Anthropic."
        return f"❌ Erreur API ({response.status_code}): {e}"
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

Propose une expérimentation concrète. Réponds en JSON strict :
{{
  "nom_experimentation": "Nom court de l'expérimentation",
  "description": "Description en 3-4 phrases",
  "echelle": "L'échelle la plus petite possible (ex: 1 quartier, 1 axe de 500m, 3 mois...)",
  "duree_semaines": 12,
  "objectif_mesurable": "Ce qu'on mesure concrètement et comment",
  "communs_recommandes": [
    {{
      "nom": "Nom du commun de la liste FabMob",
      "usage": "Comment l'utiliser dans cette expérimentation",
      "lien": "URL si connue"
    }}
  ],
  "ressources_open_source_complementaires": [
    {{
      "nom": "Nom de la ressource",
      "type": "logiciel / données / matériel / méthode",
      "usage": "Utilisation concrète",
      "lien": "URL"
    }}
  ],
  "risques": ["risque 1", "risque 2"],
  "facteurs_succes": ["facteur 1", "facteur 2"]
}}"""

def prompt_plan(problem, sous_probleme, experimentation_json, communs_text):
    return f"""Problème : « {problem} »
Sous-problème : « {sous_probleme} »
Expérimentation retenue : {experimentation_json}

**Étape 3 - Plan complet**

Produis le plan détaillé. Réponds en JSON strict :
{{
  "competences_requises": [
    {{
      "competence": "Nom",
      "role": "Ce qu'elle fait dans le projet",
      "source_possible": "Interne / Association locale / Bénévole / Prestataire",
      "estimation_jours": 5
    }}
  ],
  "ressources_materielles": [
    {{
      "ressource": "Nom",
      "quantite": "X unités",
      "cout_estime_euros": 500,
      "type_licence": "Open source / Libre / Commercial",
      "fournisseur_possible": "Nom ou type"
    }}
  ],
  "phases": [
    {{
      "phase": "Nom de la phase",
      "duree_semaines": 2,
      "actions": ["action 1", "action 2"],
      "livrable": "Ce qui est produit"
    }}
  ],
  "budget_total": {{
    "ressources_humaines_euros": 5000,
    "ressources_materielles_euros": 2000,
    "evenements_communication_euros": 500,
    "total_euros": 7500,
    "note": "Estimation indicative. Une partie peut être couverte par des ressources bénévoles ou mutualisées."
  }},
  "besoins_territoire": [
    "Accès à [espace/donnée/réseau]...",
    "Soutien politique de..."
  ],
  "indicateurs_succes": [
    {{
      "indicateur": "Nom",
      "mesure": "Comment le mesurer",
      "cible": "Valeur cible"
    }}
  ],
  "prochaine_etape_immediate": "L'action concrète à faire dès demain"
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

    # Sidebar: API key + info
    with st.sidebar:
        st.markdown("### ⚙️ Configuration")
        api_key = st.text_input(
            "Clé API Anthropic",
            type="password",
            placeholder="sk-ant-...",
            help="Obtenez votre clé sur console.anthropic.com"
        )
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
        (4, "Plan complet"),
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
        col_a, col_b = st.columns([3, 1])
        with col_a:
            validation = st.radio(
                "Cette expérimentation vous convient-elle ?",
                ["Oui, je valide", "Non, je veux l'ajuster"],
                index=0
            )
        with col_b:
            if st.button("⬅️ Retour", use_container_width=True):
                st.session_state.step = 2
                st.rerun()

        if validation == "Non, je veux l'ajuster":
            ajout = st.text_area("Vos ajustements :", placeholder="Ex : trop grande échelle, manque tel outil...")
            if st.button("🔄 Revoir l'expérimentation", type="primary", disabled=not ajout.strip() or not api_key):
                with st.spinner("Révision..."):
                    msg = prompt_experimentation(
                        st.session_state.problem,
                        st.session_state.decomposition.get('sous_probleme', '') + "\n\nAjustements demandés: " + ajout,
                        st.session_state.communs_context
                    )
                    response = call_claude([{"role": "user", "content": msg}], SYSTEM_BASE, api_key)
                    data, err = parse_json_response(response)
                    if data:
                        st.session_state.experimentation = data
                        st.rerun()
                    else:
                        st.error(f"Erreur: {err}")
        else:
            if st.button("▶️ Générer le plan complet", type="primary", disabled=not api_key):
                with st.spinner("📋 Génération du plan complet (compétences, budget, planning)..."):
                    msg = prompt_plan(
                        st.session_state.problem,
                        st.session_state.decomposition.get('sous_probleme', ''),
                        json.dumps(st.session_state.experimentation, ensure_ascii=False),
                        st.session_state.communs_context
                    )
                    response = call_claude([{"role": "user", "content": msg}], SYSTEM_BASE, api_key)
                    data, err = parse_json_response(response)
                    if data:
                        st.session_state.plan = data
                        st.session_state.step = 4
                        st.rerun()
                    else:
                        st.error(f"Erreur: {err}")
                        st.code(response)

    # ── STEP 4 : Plan complet ─────────────────────────────────────────────────
    elif st.session_state.step == 4:
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

        tab1, tab2, tab3, tab4, tab5 = st.tabs([
            "👥 Compétences", "📦 Ressources", "🗓️ Planning", "💰 Budget", "🎯 Indicateurs"
        ])

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
