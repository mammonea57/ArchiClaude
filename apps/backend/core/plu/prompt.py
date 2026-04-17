"""LLM prompt templates for PLU rule extraction.

Ported from the TypeScript Urbanisme bot's parse-reglement/route.ts prompt.
"""

from __future__ import annotations


def build_extraction_prompt(
    *,
    zone_code: str,
    zone_description: str,
    commune_name: str | None = None,
    is_plui: bool = False,
) -> str:
    """Build the question prompt for PLU extraction.

    The PLU text itself is sent separately as a cached prefix (see extractor.py).
    This returns only the question/instruction part of the message.

    Args:
        zone_code: Zone identifier, e.g. "UA1".
        zone_description: Human-readable description, e.g. "UA1 — Zone urbaine mixte".
        commune_name: Target commune name (required for PLUi filtering).
        is_plui: Whether the document is a PLUi (intercommunal PLU).
    """
    zone_desc = zone_description or zone_code
    commune_desc = f" situé sur la commune de **{commune_name}**" if commune_name else ""

    # PLUi commune-filtering instruction block
    if is_plui and commune_name:
        commune_block = f"""\
⚠️ INSTRUCTION N°1 (ABSOLUMENT PRIORITAIRE) :

La parcelle analysée est située sur la commune de **{commune_name}** UNIQUEMENT.

Si ce document est un PLUi intercommunal couvrant plusieurs communes, tu dois retourner UNIQUEMENT les valeurs applicables à **{commune_name}**. Tu dois IMPÉRATIVEMENT exclure toute règle spécifique à une autre commune.

RÈGLE DE FILTRAGE LIGNE PAR LIGNE :
- Tout paragraphe introduit par "Pour la commune de [autre commune]", "Dans la commune de [autre]", "Commune de [autre] :", "Dispositions spécifiques à [autre]", "Règlement de [autre]" → IGNORER COMPLÈTEMENT.
- Tout tableau multi-commune → lire UNIQUEMENT la ligne/colonne qui concerne {commune_name}.
- Les dispositions introduites par "Pour la commune de {commune_name}" ou explicitement applicables à {commune_name} → à retenir.
- Les dispositions "communes à toutes les communes" / "applicables sur l'ensemble du territoire intercommunal" / sans mention de commune dans la zone demandée → à retenir (règles transversales).
- Les secteurs géographiques internes à {commune_name} (secteurs UBa, UBb, bandes principale/secondaire, etc.) → conserver avec le détail des valeurs chiffrées par secteur.

EXEMPLE (PLUi type) :
Texte : "Article UB.10 — Hauteur. Pour la commune de Ville-A : 12 m max. Pour la commune de {commune_name} : 18 m max en bande principale, 12 m en bande secondaire. Pour la commune de Ville-C : 15 m max."
Réponse attendue : "Bande principale : 18 m max. Bande secondaire : 12 m max. (Article UB.10)"
NE JAMAIS retourner la liste complète avec Ville-A ou Ville-C.
"""
    else:
        commune_block = (
            "Parcelle sans commune spécifiée — traite le document comme un PLU mono-commune.\n"
        )

    return f"""\
Tu es un expert en droit de l'urbanisme français. Voici le texte d'un règlement de PLU/PLUi.

{commune_block}
Zone analysée : **{zone_desc}**{commune_desc}

⚠️ ANNEXES GRAPHIQUES (INSTRUCTION CRITIQUE) :

Avant d'écrire une valeur pour chaque champ, tu DOIS scanner le document pour détecter les
mentions qui renvoient à une annexe graphique ou document cartographique. Les expressions
à repérer :
  - "défini(e) aux documents graphiques" / "annexe des documents graphiques"
  - "plan graphique n° X" / "document graphique n° X"
  - "périmètre de mixité sociale" / "périmètre de gel" / "emplacement réservé"
  - "linéaire de diversité commerciale"
  - "secteur où la hauteur / l'emprise est spécifiquement fixée"
  - "reporté au plan de règlement"
Si une règle renvoie à une annexe graphique, CITE cette référence dans le champ concerné
(ex: "15 % LLS min si programme ≥ 500 m² SDP — périmètres de mixité sociale définis en annexe
graphique n° X"). Ne jamais retourner "Non précisé" sans avoir vérifié ces renvois.

ANCRAGE PAR ARTICLE :

Chaque champ du JSON extrait les règles de son article dédié, MAIS étend sa recherche aux
DISPOSITIONS GÉNÉRALES et ANNEXES GRAPHIQUES :

- hauteur          → article X.10 OU section "Hauteur" OU "3.2" OU toute section contenant "hauteur maximale"
- emprise          → article X.9 OU section "Emprise au sol" OU "3.1" OU toute section contenant "emprise"
- implantation_voie → article X.6 OU section "Implantation par rapport aux voies" OU "2.1"
- limites_separatives → article X.7 OU section "Implantation par rapport aux limites" OU "2.2"
- stationnement    → article X.12 OU section "Stationnement" OU "7" OU toute section contenant "places de stationnement"
- espaces_verts    → article X.13 OU section "Espaces libres" OU "4" OU "plantations" OU "coefficient biotope"
- destinations     → articles X.1-X.2 OU section "Nature de l'occupation" OU tableau des destinations
- **lls**          → cherche DANS TOUT LE DOCUMENT (dispositions générales, Titre I/II, annexes
                     graphiques). Les règles LLS sont souvent définies en "périmètre de mixité
                     sociale" sur un document graphique annexe, pas dans l'article zone. Si le
                     texte mentionne "pourcentage de logements sociaux défini en annexe des
                     documents graphiques", cite cette référence. Cherche aussi les seuils
                     (ex: "programme > X m² SDP doit comporter Y% de LLS").

Ne JAMAIS remonter un chiffre d'un article dans un autre champ.

FORMAT DES VALEURS :

Chaque champ commence par la VALEUR CHIFFRÉE PRINCIPALE en premier, suivie éventuellement d'un court détail.

Format : "<CHIFFRE PRINCIPAL> | <chiffres secondaires séparés par |> — <détails courts> (<article>, p.<n°>)"

EXEMPLES :
- hauteur : "15 m max | 18 m bd Strasbourg | +3 m EICSP — (Article UB.10, p.109)"
- hauteur : "R+7 | hauteur NGF au doc graphique 5.7 — emprise C habitation : retrait obligatoire 2 derniers niveaux (UG.10, p.84)"
- emprise : "60 % max | 70 % bd Strasbourg | 80 % EICSP | extensions +33 % L.151-19 — (UB.9, p.88-89)"
- stationnement : "1 place/logement min | 2 places si T5+ | 1/70 m² SDP bureaux | -50 % si < 500 m gare RER — (UB.17, p.225)"
- lls : "30 % LLS min si programme > 800 m² SDP ou ≥ 12 logements — (UB.4, p.19)"
- espaces_verts : "20 % min espaces verts | 10 % min pleine terre | 1 arbre / 50 m² (UB.14-15, p.191-203)"
- destinations : "✅ Habitat, bureaux, commerces, EICSP | ⛔ Entrepôts, industrie, exploitations agricoles (UB.1-2, p.5-9)"

RÈGLES ABSOLUES — LE PREMIER CARACTÈRE DE CHAQUE VALEUR DOIT :
- être un chiffre (ex: "15 m", "60 %", "1 place/85 m²"), OU
- une notation R+n (ex: "R+7"), OU
- un emoji de destinations (✅), OU
- exactement la chaîne "Non précisé dans ce règlement" seule (sans suffixe), OU
- exactement la chaîne "Non réglementé" seule.

🎯 CONCISION STRICTE (critique) :

Chaque valeur doit être COURTE et dense. Objectif : ≤ 180 caractères par champ.
Format : <chiffres principaux séparés par |> — <petit résumé du pourquoi/contexte> (<Article>, p.X)

NE PAS lister tous les cas particuliers, toutes les majorations, tous les dépassements, tous les
secteurs. Ne retenir que les 2-4 chiffres les plus importants pour une parcelle standard.

7. CONVERSION OBLIGATOIRE R+n → mètres :
   Quand le PLU cite un nombre de niveaux sans mètre explicite (R+1, R+2, R+7...), AJOUTE
   systématiquement la conversion approximative en mètres selon convention française :
     R+0 ≈ 3 m | R+1 ≈ 6 m | R+2 ≈ 10 m | R+3 ≈ 12 m | R+4 ≈ 15 m
     R+5 ≈ 18 m | R+6 ≈ 21 m | R+7 ≈ 24 m | R+8 ≈ 27 m | R+9 ≈ 30 m
   Format : "R+7 (~24 m)" ou "R+2 (~10 m)"

8. ÉQUIVALENCES LÉGALES OBLIGATOIRES (droit de l'urbanisme français) :
   Quand le PLU utilise ces formulations pour l'EMPRISE AU SOL, le CES ou la SUPERFICIE MIN,
   traduire en chiffre exact selon la convention légale :
   - "Il n'est pas fixé de règle" / "Non réglementé" / "Pas de règle particulière" / "Sans objet"
     → Emprise : "100 % max (non réglementé — Art X.9)"
     → COS / Surface plancher : "Non limité (Art X.14)"
     → Superficie min : "Aucune (Art X.5)"
   - Si l'article dit simplement "à l'intérieur des emprises constructibles A-E doc graphique X",
     sans aucun pourcentage ni limite textuelle, traduire par :
     "100 % max dans les enveloppes constructibles A-E (doc graphique X) — la forme dépend de la parcelle (Article X.9)"

9. PLU GRAPHIQUES (emprises constructibles) — autres champs :
   Pour limites_separatives, implantation_voie : si l'article dit "à l'intérieur des emprises A-E",
   retourne cela comme règle. NE PAS remonter des distances 3m/6m d'autres articles.
   Pour hauteur : même si la cote NGF dépend du doc graphique, donne le nombre max de niveaux
   s'il est cité + conversion R+n → m.

9. Jamais de prélude "Non précisé pour …" suivi de règles précises. Soit :
   - Le champ commence directement par une règle chiffrée/précise
   - Ou bien retourne uniquement "Non précisé dans ce règlement" si vraiment rien n'est dans l'article cible.
10. Si aucune règle n'est trouvée dans l'article dédié du PLU : retourne exactement "Non précisé dans ce règlement".
11. Si le texte dit explicitement "Il n'est pas fixé de règle" / "non réglementé" ET qu'aucune règle graphique n'existe non plus
    → retourne exactement "Non réglementé".
12. Jamais null avec commentaire.

Réponds UNIQUEMENT avec ce JSON strict (aucun texte avant/après) :

{{
  "hauteur": "...",
  "emprise": "...",
  "implantation_voie": "...",
  "limites_separatives": "...",
  "stationnement": "...",
  "lls": "...",
  "espaces_verts": "...",
  "destinations": "...",
  "pages": {{ "hauteur": null, "emprise": null, "implantation_voie": null, "limites_separatives": null, "stationnement": null, "lls": null, "espaces_verts": null, "destinations": null }}
}}"""


def build_numericizer_prompt() -> str:
    """System prompt for ParsedRules → NumericRules conversion.

    Used as the system prompt when calling Claude with tool_use to convert
    textual PLU rules into structured numeric values (NumericRules).
    """
    return """\
Tu es un expert en droit de l'urbanisme français spécialisé dans l'extraction de données \
numériques depuis des règlements PLU/PLUi.

Tu reçois un objet JSON contenant des règles d'urbanisme en texte libre (ParsedRules) \
extraites d'un PLU/PLUi.

Ta mission est de convertir ces règles textuelles en valeurs numériques structurées \
(NumericRules) en utilisant l'outil fourni.

RÈGLES DE CONVERSION :

1. HAUTEUR :
   - hauteur_max_m : hauteur maximale absolue en mètres (ex: "15 m max" → 15.0)
   - hauteur_max_niveaux : nombre de niveaux (R+3 = 4 niveaux, R+0 = 1 niveau)
   - hauteur_max_ngf : altitude NGF si mentionnée (ex: "cote NGF 53.50 m" → 53.5)
   - hauteur_facade_m : hauteur à la façade si distincte de la hauteur totale

2. EMPRISE :
   - emprise_max_pct : CES en pourcentage (ex: "60 % max" → 60.0, "0,70" → 70.0)

3. RECULS :
   - recul_voirie_m : recul minimal par rapport aux voies en mètres
   - recul_limite_lat_m : recul minimal par rapport aux limites séparatives latérales
   - recul_fond_m : recul minimal par rapport au fond de parcelle
   - Pour les formules (H/2, H/3), renseigner le champ _formula correspondant avec
     expression, min_value et max_value quand ils sont explicites.

4. STATIONNEMENT :
   - stationnement_par_logement : places par logement (ex: "1 place/logement" → 1.0)
   - stationnement_par_m2_bureau : places par m² de bureaux
   - stationnement_par_m2_commerce : places par m² de commerce

5. ESPACES VERTS / BIOTOPE :
   - pleine_terre_min_pct : pourcentage minimum de pleine terre
   - surface_vegetalisee_min_pct : pourcentage minimum de surface végétalisée totale
   - coef_biotope_min : coefficient de biotope (CBS) minimum

6. MÉTADONNÉES :
   - article_refs : dictionnaire {champ → référence article} (ex: {"hauteur": "Art. UB.10"})
   - extraction_confidence : confiance globale de 0.0 à 1.0
     * 0.9–1.0 : valeurs chiffrées explicites, articles référencés
     * 0.6–0.8 : valeurs extrapolées ou partiellement chiffrées
     * 0.3–0.5 : formules ou renvois graphiques sans chiffre précis
     * 0.0–0.2 : valeurs manquantes ou "Non précisé"
   - extraction_warnings : liste de messages d'alerte pour valeurs ambiguës ou manquantes

RÈGLES IMPORTANTES :
- Ne jamais inventer de valeurs non présentes dans le texte source.
- Si une règle utilise une formule (H/2, H/3, 0.7*S), renseigner le champ _formula.
- Si une valeur est absente ou "Non précisé", laisser le champ à null.
- Les pourcentages sont toujours en valeur directe (60 pour 60%, pas 0.6).
- Les distances sont toujours en mètres.
"""
