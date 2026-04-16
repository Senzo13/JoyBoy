"""
Normalisation partagée des demandes d'édition image.

Objectif:
- comprendre des prompts spatiaux / pose dans plusieurs langues
- centraliser l'interprétation au même endroit pour le router et la génération
- éviter les heuristiques FR dupliquées dans plusieurs modules
"""

from __future__ import annotations

import json
import re
import unicodedata
from functools import lru_cache

from core.ai.utility_ai import _call_utility


_DIRECTIVE_SYSTEM_PROMPT = """You normalize image-edit requests written in any language, slang, or mixed languages.

Return STRICT JSON only with these keys:
{
  "subject_reference": true,
  "move_requested": false,
  "explicit_relocation": false,
  "placement": "left|right|center|none",
  "vertical": "top|bottom|none",
  "distance": "farther|closer|none",
  "size": "smaller|bigger|none",
  "pose_flags": ["pose_change", "arms_down", "hands_face", "hands_chest", "standing", "sitting", "kneeling", "all_fours", "lying", "back_view", "bending"],
  "adult_request_detected": false,
  "adult_nudity": false,
  "adult_sexualized": false,
  "adult_clothing_exposure": false,
  "clean_prompt_en": "short English visual summary"
}

Rules:
- placement/vertical/distance/size refer to where the person/subject should appear in frame.
- explicit_relocation = true when the subject should be moved elsewhere in the frame or scene.
- move_requested = true when the user asks to move, reposition, swap sides, place elsewhere, farther, closer, etc.
- pose_change = true when the user asks for a different pose or body posture without naming a precise target pose.
- hands_face = hands touching or covering the face/head.
- hands_chest = hands on chest, torso, upper body, breasts, or cleavage.
- arms_down = arms relaxed along the body / at the sides.
- adult_request_detected only for nudity, explicit sexual exposure, or erotic sexual actions.
- clean_prompt_en must stay short, visual, and in English. If nothing useful remains, return "".
"""


_PERSON_TOKENS = (
    "person", "personne", "persona", "pessoa", "subject", "sujet",
    "woman", "man", "girl", "boy", "human", "body", "corps", "cuerpo",
    "corpo", "figure", "elle", "il", "she", "he", "her", "him",
    "them", "they", "la", "le", "lui", "l'", "someone",
    "mujer", "hombre", "femme", "homme", "ragazza", "ragazzo",
    "frau", "mann", "mulher",
)

_MOVE_PHRASES = (
    "change sa position", "changer sa position", "change de position", "change la position",
    "change de place", "deplace", "deplacer", "mets la personne", "place la personne",
    "bouge la personne", "move the person", "move her", "move him", "move subject",
    "reposition", "reposition the person", "put the person", "place the person",
    "swap sides", "elsewhere in the image", "somewhere else in the frame",
    "mueve a la persona", "cambia de posicion", "cambia de posición", "mover a pessoa",
    "verschiebe", "sposta la persona",
)

_CLOTHING_EDIT_PHRASES = (
    "habit", "habits", "vetement", "vetements", "vêtement", "vêtements",
    "fringue", "fringues", "sape", "sapes", "tenue", "outfit",
    "change ses habits", "change ses vetements", "changer ses vetements",
    "change d'habit", "changer d'habit", "change d habit", "changer d habit",
    "change sa tenue", "changer sa tenue", "change sa robe", "changer sa robe",
    "mettre une tenue", "mets lui une robe", "met une robe", "robe rouge",
    "t shirt", "t-shirt", "tee shirt", "chemise", "shirt", "dress", "robe",
    "bikini", "maillot", "maillot de bain", "swimsuit",
    "pantalon", "pants", "jupe", "skirt", "veste", "jacket", "manteau", "coat",
    "clothes", "clothing", "change clothes", "different outfit", "wearing",
    "ropa", "vestido", "camisa", "pantalones", "falda",
    "vestiti", "abito", "camicia", "pantaloni", "gonna",
    "kleidung", "kleid", "hemd", "hose", "rock",
)

_POSE_PRESERVATION_PHRASES = (
    "keep original pose",
    "keep the original pose",
    "keep pose unchanged",
    "keep the pose unchanged",
    "same pose",
    "same body pose",
    "pose unchanged",
    "unchanged pose",
    "maintain exact pose",
    "maintaining exact pose",
    "preserve pose",
    "preserve the pose",
    "do not change pose",
    "do not change the pose",
    "don't change pose",
    "dont change pose",
    "garde la pose",
    "garder la pose",
    "conserve la pose",
    "conserver la pose",
    "meme pose",
    "même pose",
    "pose identique",
    "pose inchangee",
    "pose inchangée",
    "mantener la pose",
    "misma pose",
    "posa uguale",
    "stessa posa",
)

_POSE_CHANGE_PHRASES = (
    "change pose",
    "change the pose",
    "change her pose",
    "change his pose",
    "different pose",
    "new pose",
    "change sa pose",
    "changer sa pose",
    "change de pose",
    "changer de pose",
    "autre pose",
    "pose differente",
    "pose différente",
    "cambiar la pose",
    "cambia la pose",
    "cambiare posa",
    "altra posa",
)

_PLACEMENT_GROUPS = {
    "left": (
        "tout a gauche", "completement a gauche", "sur la gauche", "a gauche",
        "left side", "on the left", "to the left",
        "a la izquierda", "izquierda", "lado izquierdo",
        "links", "linke seite",
        "a sinistra", "sinistra",
        "a esquerda", "esquerda", "lado esquerdo",
    ),
    "right": (
        "tout a droite", "completement a droite", "sur la droite", "a droite",
        "right side", "on the right", "to the right",
        "a la derecha", "derecha", "lado derecho",
        "rechts", "rechte seite",
        "a destra", "destra",
        "a direita", "direita", "lado direito",
    ),
    "center": (
        "au centre", "centre de l image", "center of the frame", "centered", "center",
        "centro", "centrado", "al centro",
        "mitte", "zentriert",
    ),
}

_VERTICAL_GROUPS = {
    "top": (
        "en haut", "plus haut", "top of the frame", "higher in the frame",
        "arriba", "mas arriba", "más arriba",
        "oben", "hoeher", "höher",
        "in alto",
        "em cima", "mais alto",
    ),
    "bottom": (
        "en bas", "plus bas", "bottom of the frame", "lower in the frame",
        "abajo", "mas abajo", "más abajo",
        "unten", "tiefer",
        "in basso",
        "embaixo", "mais baixo",
    ),
}

_DISTANCE_GROUPS = {
    "farther": (
        "plus loin", "un peu plus loin", "plus loin dans la piece", "plus loin dans la salle",
        "au fond", "arriere plan", "background area",
        "farther", "further away", "further into the room", "farther into the room",
        "a bit further", "a little further", "further back",
        "mas lejos", "más lejos", "mas al fondo", "más al fondo",
        "weiter hinten", "weiter weg",
        "piu lontano", "più lontano", "piu indietro", "più indietro",
        "mais longe", "mais ao fundo",
    ),
    "closer": (
        "plus pres", "plus proche", "un peu plus pres", "un peu plus proche",
        "premier plan", "foreground",
        "closer", "nearer", "a bit closer", "a little closer",
        "mas cerca", "más cerca",
        "naher", "näher",
        "piu vicino", "più vicino",
        "mais perto",
    ),
}

_SIZE_GROUPS = {
    "smaller": (
        "plus petit", "smaller", "smaller in the frame", "petite",
        "mas pequeno", "más pequeño", "kleiner", "piu piccolo", "più piccolo",
    ),
    "bigger": (
        "plus grand", "bigger", "larger", "larger in the frame",
        "mas grande", "más grande", "groesser", "größer", "piu grande", "più grande",
    ),
}

_POSE_GROUPS = {
    "pose_change": (
        "change sa pose", "changer sa pose", "change de pose", "changer de pose",
        "change posture", "change sa posture", "different pose", "new pose",
        "change the pose", "change her pose", "change his pose", "change their pose",
        "pose differente", "pose différente", "autre pose",
        "cambia la pose", "cambiar la pose", "otra pose", "cambia de postura",
        "pose andern", "andere pose", "haltung andern", "haltung ändern",
        "cambia posa", "cambiare posa", "altra posa",
        "muda a pose", "mudar a pose", "outra pose",
    ),
    "arms_down": (
        "bras le long du corps", "bras baisse", "bras baisses", "bras baisses le long du corps",
        "arms at sides", "arms down", "arms along the body", "arms relaxed along the body",
        "brazos al costado", "brazos pegados al cuerpo",
        "arme an den seiten",
        "braccia lungo il corpo",
        "bracos ao longo do corpo", "braços ao longo do corpo",
    ),
    "hands_face": (
        "mains sur son visage", "main sur son visage", "mains sur le visage",
        "hands on her face", "hands on the face", "hands touching the face",
        "manos en su rostro", "mano en su rostro", "manos en la cara",
        "hande im gesicht", "haende im gesicht", "hände im gesicht",
        "mani sul viso",
        "maos no rosto", "mãos no rosto",
    ),
    "hands_chest": (
        "mains sur son torse", "main sur son torse", "mains sur sa poitrine",
        "main sur sa poitrine", "mains sur les seins", "mains sur son buste",
        "hands on her chest", "hands on her torso", "hands on the chest",
        "manos en el pecho", "mano en el pecho", "manos en el torso",
        "hande auf der brust", "haende auf der brust", "hände auf der brust",
        "mani sul petto", "mani sul torso",
        "maos no peito", "mãos no peito", "maos no torso", "mãos no torso",
    ),
    "standing": (
        "debout", "standing", "stand up", "de pie", "stehend", "in piedi",
        "em pe", "em pé",
    ),
    "sitting": (
        "assise", "assis", "asseoir", "sitting", "sit down", "sentada", "sentado",
        "sitzend", "seduta", "seduto", "sentada",
    ),
    "kneeling": (
        "a genoux", "agenouille", "agenouiller", "kneeling", "de rodillas",
        "kniend", "in ginocchio", "ajoelhada", "ajoelhado",
    ),
    "all_fours": (
        "a quatre pattes", "quatre pattes", "all fours", "on all fours",
        "a cuatro patas", "auf allen vieren", "a quattro zampe", "a quatro patas",
    ),
    "lying": (
        "allonge", "allongee", "allonger", "sur le dos",
        "lying down", "lying", "on her back",
        "acostada", "tumbada",
        "liegend",
        "sdraiata",
        "deitada",
    ),
    "back_view": (
        "de dos", "back view", "seen from behind", "from behind",
        "de espaldas", "espalda",
        "ruckansicht", "rückenansicht", "von hinten",
        "vista posteriore",
        "de costas",
    ),
    "bending": (
        "penche", "penchee", "pencher",
        "bending forward", "leaning forward", "bent forward",
        "inclinado hacia delante", "inclinandose hacia delante",
        "vorgebeugt", "nach vorne gebeugt",
        "chinata in avanti",
        "inclinada para frente",
    ),
}

_ADULT_REGEX = re.compile(
    r"\b("
    r"nude|naked|topless|nudity|nsfw|porn|sex|sexual|cum|orgasm|masturbat|"
    r"boob|boobs|tits|nipple|nipples|pussy|vagina|penis|cock|"
    r"nu|nue|nus|nues|déshabill|deshabill|tetons?|tétons?|chatte|vagin|bite|"
    r"desnuda|desnudo|pezones?|coño|vagina|pene|sexo|porno|"
    r"nua|nuo|nudo|mamilos?|sexo|porn|"
    r"nackt|nippel|sexuell|porno"
    r")\b",
    re.IGNORECASE,
)

_ADULT_EXPOSURE_PHRASES = (
    "open shirt", "shirt open", "chemise ouverte", "ouvrir sa chemise",
    "show breasts", "show her breasts", "voir ses seins", "voir sa poitrine",
    "wardrobe malfunction", "nip slip", "soutien gorge visible",
)


def _normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", text.lower()).strip()


def _last_phrase_position(text: str, phrases: tuple[str, ...]) -> int:
    last = -1
    for phrase in phrases:
        for match in re.finditer(re.escape(phrase), text):
            last = max(last, match.start())
    return last


def _contains_any(text: str, phrases: tuple[str, ...]) -> bool:
    return any(phrase in text for phrase in phrases)


def _contains_token(text: str, token: str) -> bool:
    return bool(re.search(rf"\b{re.escape(token)}\b", text))


def _is_clothing_edit_request(text: str) -> bool:
    return _contains_any(text, _CLOTHING_EDIT_PHRASES)


def _is_pose_preservation_reference(text: str) -> bool:
    """True when "pose" is only mentioned as something to preserve.

    Suggestion prompts often append "keep original pose/body proportions" to
    protect composition. Treating that as a pose edit sends the job into the
    destructive two-pass repose path, so only real pose-change phrases may
    override this guard.
    """
    text = _normalize_text(text)
    return _contains_any(text, _POSE_PRESERVATION_PHRASES) and not _contains_any(text, _POSE_CHANGE_PHRASES)


def _extract_json_object(raw: str) -> dict | None:
    if not raw:
        return None
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text, flags=re.IGNORECASE).strip()
        text = re.sub(r"```$", "", text).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    candidate = text[start:end + 1]
    try:
        data = json.loads(candidate)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _normalize_choice(value: str | None, allowed: set[str]) -> str:
    cleaned = _normalize_text(str(value or ""))
    return cleaned if cleaned in allowed else "none"


def _normalize_pose_flags(flags) -> list[str]:
    aliases = {
        "pose_change": "pose_change",
        "different pose": "pose_change",
        "change pose": "pose_change",
        "change the pose": "pose_change",
        "arms_down": "arms_down",
        "arms at sides": "arms_down",
        "arms along the body": "arms_down",
        "hands_face": "hands_face",
        "hands on face": "hands_face",
        "hands_face/head": "hands_face",
        "hands_chest": "hands_chest",
        "hands on chest": "hands_chest",
        "hands on torso": "hands_chest",
        "standing": "standing",
        "sitting": "sitting",
        "kneeling": "kneeling",
        "all_fours": "all_fours",
        "all fours": "all_fours",
        "lying": "lying",
        "back_view": "back_view",
        "back view": "back_view",
        "bending": "bending",
    }
    normalized = []
    seen = set()
    if not isinstance(flags, (list, tuple)):
        return normalized
    for item in flags:
        alias = aliases.get(_normalize_text(str(item or "")))
        if alias and alias not in seen:
            normalized.append(alias)
            seen.add(alias)
    return normalized


@lru_cache(maxsize=256)
def _llm_extract_prompt(prompt: str) -> dict:
    raw = _call_utility(
        [
            {"role": "system", "content": _DIRECTIVE_SYSTEM_PROMPT},
            {"role": "user", "content": f'Prompt: """{prompt.strip()}"""'},
        ],
        num_predict=220,
        temperature=0.0,
        timeout=30,
    )
    data = _extract_json_object(raw or "")
    if not data:
        return {}

    provided = set(data.keys())
    return {
        "_provided": provided,
        "subject_reference": bool(data.get("subject_reference")) if "subject_reference" in provided else None,
        "move_requested": bool(data.get("move_requested")) if "move_requested" in provided else None,
        "explicit_relocation": bool(data.get("explicit_relocation")) if "explicit_relocation" in provided else None,
        "placement": _normalize_choice(data.get("placement"), {"left", "right", "center", "none"}) if "placement" in provided else None,
        "vertical": _normalize_choice(data.get("vertical"), {"top", "bottom", "none"}) if "vertical" in provided else None,
        "distance": _normalize_choice(data.get("distance"), {"farther", "closer", "none"}) if "distance" in provided else None,
        "size": _normalize_choice(data.get("size"), {"smaller", "bigger", "none"}) if "size" in provided else None,
        "pose_flags": _normalize_pose_flags(data.get("pose_flags")) if "pose_flags" in provided else None,
        "adult_request_detected": bool(data.get("adult_request_detected")) if "adult_request_detected" in provided else None,
        "adult_nudity": bool(data.get("adult_nudity")) if "adult_nudity" in provided else None,
        "adult_sexualized": bool(data.get("adult_sexualized")) if "adult_sexualized" in provided else None,
        "adult_clothing_exposure": bool(data.get("adult_clothing_exposure")) if "adult_clothing_exposure" in provided else None,
        "clean_prompt_en": str(data.get("clean_prompt_en", "") or "").strip() if "clean_prompt_en" in provided else None,
    }


def _heuristic_parse(prompt: str) -> dict:
    text = _normalize_text(prompt)
    placement = "none"
    vertical = "none"
    distance = "none"
    size = "none"

    left_pos = _last_phrase_position(text, _PLACEMENT_GROUPS["left"])
    right_pos = _last_phrase_position(text, _PLACEMENT_GROUPS["right"])
    center_pos = _last_phrase_position(text, _PLACEMENT_GROUPS["center"])
    if max(left_pos, right_pos, center_pos) >= 0:
        if left_pos > max(right_pos, center_pos):
            placement = "left"
        elif right_pos > max(left_pos, center_pos):
            placement = "right"
        else:
            placement = "center"

    top_pos = _last_phrase_position(text, _VERTICAL_GROUPS["top"])
    bottom_pos = _last_phrase_position(text, _VERTICAL_GROUPS["bottom"])
    if top_pos > bottom_pos and top_pos >= 0:
        vertical = "top"
    elif bottom_pos > top_pos and bottom_pos >= 0:
        vertical = "bottom"

    if _contains_any(text, _DISTANCE_GROUPS["farther"]):
        distance = "farther"
    elif _contains_any(text, _DISTANCE_GROUPS["closer"]):
        distance = "closer"

    if _contains_any(text, _SIZE_GROUPS["smaller"]):
        size = "smaller"
    elif _contains_any(text, _SIZE_GROUPS["bigger"]):
        size = "bigger"

    pose_flags = [
        flag
        for flag, phrases in _POSE_GROUPS.items()
        if _contains_any(text, phrases)
    ]

    if "pose_change" not in pose_flags and any(flag in pose_flags for flag in ("arms_down", "hands_face", "hands_chest", "standing", "sitting", "kneeling", "all_fours", "lying", "back_view", "bending")):
        pose_flags.insert(0, "pose_change")

    subject_reference = any(_contains_token(text, token) for token in _PERSON_TOKENS)
    move_requested = _contains_any(text, _MOVE_PHRASES) or placement != "none" or vertical != "none" or distance != "none" or size != "none"
    explicit_relocation = placement != "none" or vertical != "none" or distance != "none" or size != "none"
    adult_request_detected = bool(_ADULT_REGEX.search(text)) or _contains_any(text, _ADULT_EXPOSURE_PHRASES)
    clothing_edit = _is_clothing_edit_request(text)

    return {
        "source": "heuristic",
        "subject_reference": subject_reference,
        "move_requested": move_requested,
        "explicit_relocation": explicit_relocation,
        "placement": placement,
        "vertical": vertical,
        "distance": distance,
        "size": size,
        "pose_flags": pose_flags,
        "adult_request_detected": adult_request_detected,
        "adult_nudity": bool(_ADULT_REGEX.search(text)),
        "adult_sexualized": adult_request_detected,
        "adult_clothing_exposure": _contains_any(text, _ADULT_EXPOSURE_PHRASES),
        "clothing_edit": clothing_edit,
        "clean_prompt_en": "",
    }


def parse_edit_request(prompt: str, image_present: bool = False, has_brush_mask: bool = False) -> dict:
    if not prompt:
        return {
            "source": "empty",
            "raw_prompt": "",
            "subject_reference": False,
            "move_requested": False,
            "explicit_relocation": False,
            "placement": "none",
            "vertical": "none",
            "distance": "none",
            "size": "none",
            "pose_flags": [],
            "adult_request_detected": False,
            "adult_nudity": False,
            "adult_sexualized": False,
            "adult_clothing_exposure": False,
            "clothing_edit": False,
            "clean_prompt_en": "",
            "should_repose": False,
        }

    heuristic = _heuristic_parse(prompt)
    llm_payload = _llm_extract_prompt(prompt)
    result = dict(heuristic)

    if llm_payload:
        provided = llm_payload.get("_provided", set())
        result["source"] = "llm"
        for key in ("subject_reference", "move_requested", "explicit_relocation", "placement", "vertical", "distance", "size"):
            if key in provided:
                result[key] = llm_payload.get(key)
        if "pose_flags" in provided:
            result["pose_flags"] = llm_payload.get("pose_flags") or []
        if "clean_prompt_en" in provided and llm_payload.get("clean_prompt_en"):
            result["clean_prompt_en"] = llm_payload["clean_prompt_en"]

        # Pour les flags adultes, rester conservateur: le LLM peut élargir le signal,
        # mais on garde aussi la détection heuristique si elle a déjà matché.
        for key in ("adult_request_detected", "adult_nudity", "adult_sexualized", "adult_clothing_exposure"):
            if key in provided:
                result[key] = bool(result.get(key) or llm_payload.get(key))

    result["explicit_relocation"] = bool(
        result.get("explicit_relocation")
        or result.get("placement") != "none"
        or result.get("vertical") != "none"
        or result.get("distance") != "none"
        or result.get("size") != "none"
    )
    result["move_requested"] = bool(result.get("move_requested") or result["explicit_relocation"])

    # Clothing/adult edit requests should stay in the targeted inpaint/router
    # path unless the local heuristics also see a real spatial or pose request.
    # Small text models can hallucinate pose_flags/size for prompts such as
    # "change d'habit" or "completely nude", which otherwise short-circuits
    # into the destructive two-pass repose pipeline.
    heuristic_pose_flags = heuristic.get("pose_flags") or []
    heuristic_explicit_relocation = bool(heuristic.get("explicit_relocation"))
    targeted_edit_request = bool(result.get("clothing_edit") or result.get("adult_request_detected"))
    if targeted_edit_request and not heuristic_explicit_relocation:
        if not heuristic_pose_flags:
            result["pose_flags"] = []
        result["placement"] = heuristic.get("placement", "none")
        result["vertical"] = heuristic.get("vertical", "none")
        result["distance"] = heuristic.get("distance", "none")
        result["size"] = heuristic.get("size", "none")
        result["explicit_relocation"] = False
        result["move_requested"] = bool(heuristic.get("move_requested"))

    if (
        _is_pose_preservation_reference(prompt)
        and not heuristic_pose_flags
        and not heuristic_explicit_relocation
    ):
        result["pose_flags"] = []
        result["placement"] = heuristic.get("placement", "none")
        result["vertical"] = heuristic.get("vertical", "none")
        result["distance"] = heuristic.get("distance", "none")
        result["size"] = heuristic.get("size", "none")
        result["explicit_relocation"] = False
        result["move_requested"] = bool(heuristic.get("move_requested"))

    result["should_repose"] = bool(
        image_present
        and not has_brush_mask
        and (
            bool(result.get("pose_flags"))
            or result["explicit_relocation"]
            or (result["move_requested"] and result.get("subject_reference"))
        )
    )
    result["raw_prompt"] = prompt
    return result


def build_repose_directives(
    prompt: str,
    image_present: bool = True,
    has_brush_mask: bool = False,
    parsed_request: dict | None = None,
) -> dict:
    parsed = parsed_request or parse_edit_request(
        prompt,
        image_present=image_present,
        has_brush_mask=has_brush_mask,
    )
    directives = {
        "anchor_x": None,
        "anchor_y": None,
        "scale_mult": 1.0,
        "box_scale_x": 1.0,
        "box_scale_y": 1.0,
        "y_shift": 0.0,
        "move_requested": bool(parsed.get("move_requested")),
        "explicit_relocation": bool(parsed.get("explicit_relocation")),
        "prompt_terms": [
            "single person",
            "full body",
            "entire figure visible",
            "feet visible",
            "same person",
            "same face identity",
            "realistic anatomy",
        ],
        "negative_terms": [
            "duplicate person",
            "cropped body",
            "cut off feet",
            "cut off hands",
        ],
        "debug_flags": [],
        "parsed_request": parsed,
    }

    placement = parsed.get("placement", "none")
    if placement == "left":
        directives["anchor_x"] = 0.28
        directives["prompt_terms"].append("positioned on the left side of the frame")
        directives["debug_flags"].append("left")
    elif placement == "right":
        directives["anchor_x"] = 0.72
        directives["prompt_terms"].append("positioned on the right side of the frame")
        directives["debug_flags"].append("right")
    elif placement == "center":
        directives["anchor_x"] = 0.50
        directives["prompt_terms"].append("positioned near the center of the frame")
        directives["debug_flags"].append("center")

    vertical = parsed.get("vertical", "none")
    if vertical == "top":
        directives["anchor_y"] = 0.40
        directives["prompt_terms"].append("positioned higher in the frame")
        directives["debug_flags"].append("top")
    elif vertical == "bottom":
        directives["anchor_y"] = 0.68
        directives["prompt_terms"].append("positioned lower in the frame")
        directives["debug_flags"].append("bottom")

    distance = parsed.get("distance", "none")
    if distance == "farther":
        directives["scale_mult"] *= 0.78
        directives["y_shift"] -= 0.05
        directives["prompt_terms"].append("farther from the camera, smaller in the frame")
        directives["negative_terms"].append("large close-up person")
        directives["debug_flags"].append("farther")
    elif distance == "closer":
        directives["scale_mult"] *= 1.18
        directives["y_shift"] += 0.05
        directives["prompt_terms"].append("closer to the camera, larger in the frame")
        directives["negative_terms"].append("tiny distant person")
        directives["debug_flags"].append("closer")

    size = parsed.get("size", "none")
    if size == "smaller":
        directives["scale_mult"] *= 0.88
        directives["prompt_terms"].append("slightly smaller in the frame")
        directives["debug_flags"].append("smaller")
    elif size == "bigger":
        directives["scale_mult"] *= 1.10
        directives["prompt_terms"].append("slightly larger in the frame")
        directives["debug_flags"].append("bigger")

    pose_flags = parsed.get("pose_flags") or []
    if "pose_change" in pose_flags:
        directives["prompt_terms"].append("different body pose from the original")
        directives["debug_flags"].append("pose_change")
    if "arms_down" in pose_flags:
        directives["prompt_terms"].append("standing with both arms relaxed along the body")
        directives["negative_terms"].extend([
            "raised arms",
            "crossed arms",
            "hands on hips",
            "bent elbows",
        ])
        directives["debug_flags"].append("arms_down")
    if "hands_face" in pose_flags:
        directives["prompt_terms"].append("both hands touching the face")
        directives["negative_terms"].extend([
            "hands away from face",
            "arms at sides",
        ])
        directives["debug_flags"].append("hands_face")
    if "hands_chest" in pose_flags:
        directives["prompt_terms"].append("both hands resting on the upper chest")
        directives["negative_terms"].extend([
            "hands away from chest",
            "arms at sides",
        ])
        directives["debug_flags"].append("hands_chest")
    if "standing" in pose_flags:
        directives["prompt_terms"].append("standing upright")
        directives["debug_flags"].append("standing")
    if "sitting" in pose_flags:
        directives["prompt_terms"].append("sitting naturally")
        directives["debug_flags"].append("sitting")
    if "kneeling" in pose_flags:
        directives["prompt_terms"].append("kneeling on the floor")
        directives["debug_flags"].append("kneeling")
    if "all_fours" in pose_flags:
        directives["prompt_terms"].append("on all fours")
        directives["debug_flags"].append("all_fours")
    if "lying" in pose_flags:
        directives["prompt_terms"].append("lying down")
        directives["debug_flags"].append("lying")
    if "back_view" in pose_flags:
        directives["prompt_terms"].append("seen from behind, back view")
        directives["debug_flags"].append("back_view")
    if "bending" in pose_flags:
        directives["prompt_terms"].append("bending forward")
        directives["debug_flags"].append("bending")

    if not pose_flags:
        directives["prompt_terms"].append("natural body pose")

    return directives


def should_use_repose_pipeline(prompt: str, image_present: bool = False, has_brush_mask: bool = False) -> bool:
    return bool(parse_edit_request(prompt, image_present=image_present, has_brush_mask=has_brush_mask).get("should_repose"))


def is_adult_request_heuristic(prompt: str) -> bool:
    """Fast adult-request check that never calls the utility LLM.

    Generation routes use this before model preload so a locked local adult pack
    can refuse immediately instead of loading SDXL/ControlNet first.
    """
    return bool(_heuristic_parse(prompt).get("adult_request_detected"))


def is_adult_request(prompt: str) -> bool:
    parsed = parse_edit_request(prompt, image_present=False, has_brush_mask=False)
    return bool(parsed.get("adult_request_detected"))
