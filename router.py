"""The routing policy. Pure functions, no network. Every decision comes with a one-line `why`."""
import re, time
from config import ROUTE_TABLE, NEXT_TIER, ROUTER_CLASSIFIER, WORKLOAD_PRIORITY, DEFAULT_PRIORITY

# --- 1. language -------------------------------------------------------------------
INDIC_SCRIPT = re.compile(r"[ऀ-෿]")  # Devanagari, Bengali, Gurmukhi, Gujarati, Odia, Tamil, Telugu, Kannada, Malayalam, Sinhala
ROMAN_INDIC_WORDS = {
    # Hindi / Hinglish
    "hai", "hain", "nahi", "nahin", "kya", "kyu", "kyun", "kaise", "kab", "kahan", "mera", "meri", "mere", "aap",
    "aapka", "aapke", "tum", "karo", "karna", "raha", "rahi", "rahe", "hoga", "hogi", "tha", "thi",
    "bhi", "abhi", "paisa", "paise", "chahiye", "batao", "mujhe", "humko", "yaar", "accha", "acha",
    "theek", "thik", "toh", "bhai", "kripya", "dhanyavad", "namaste", "matlab", "wala", "wale", "wali", "lekin",
    "aur", "haan", "bilkul", "jaldi", "aaj", "samajh", "gaya", "gayi", "diya", "likho", "karein", "warna",
    # Tamil / Telugu / Kannada romanised (common)
    "enna", "illai", "illa", "vanakkam", "nandri", "epdi", "seri", "irukku", "panna", "pannunga", "venum",
    "ledu", "cheppandi", "namaskaram", "kavali", "chesanu", "chesadu", "vesaru", "rayandi", "nenu", "naaku", "sare",
}
INDIC_LANGS = r"(hindi|tamil|telugu|kannada|malayalam|marathi|bengali|bangla|gujarati|punjabi|odia|oriya|urdu|hinglish)"
TARGET_INDIC = re.compile(r"\b(into|to|in)\s+(?:\w+\s+)?" + INDIC_LANGS + r"\b", re.I)  # "into formal Hindi"
WORD_RE = re.compile(r"[a-zA-Z]+")


def detect_language(prompt: str) -> tuple[str, bool]:
    """Returns (label, is_indic). Rules: any Indic-script char; >=3 romanised-Indic keywords (or >=2 making up 20% of words);
    or an explicit Indic target language ("translate into Hindi")."""
    if INDIC_SCRIPT.search(prompt):
        return "indic_script", True
    words = [w.lower() for w in WORD_RE.findall(prompt)]
    hits = sum(1 for w in words if w in ROMAN_INDIC_WORDS)
    if hits >= 3 or (words and hits / len(words) >= 0.2 and hits >= 2):
        return "romanised_indic", True
    if TARGET_INDIC.search(prompt):
        return "indic_target", True
    return "english", False


# --- 2. difficulty -----------------------------------------------------------------
EASY_KW = ["classify", "classification", "label", "categorise", "categorize", "category", "yes or no", "is this",
           "sentiment", "tag", "which of the following", "intent", "one-line", "one line", "only the label",
           "वर्गीकृत", "श्रेणी", "வகைப்படுத்து", "వర్గీకరించ"]
MEDIUM_KW = ["summarise", "summarize", "summary", "extract", "translate", "translation", "list the", "pull out",
             "convert", "rewrite", "paraphrase", "सारांश", "अनुवाद", "निकालिए", "निकालें", "सुरुक्कम्", "சுருக்கம்", "மொழிபெயர்",
             "సారాంశం", "అనువదించ"]
HARD_KW = ["reason", "analyse", "analyze", "analysis", "compare", "contrast", "step by step", "step-by-step",
           "multi-step", "legal", "liability", "clause", "indemn", "jurisdiction", "financial", "calculate",
           "compute", "penalty", "reconcile", "discrepanc", "contradict", "justify", "evaluate",
           "trade-off", "tradeoff", "root cause", "recommend", "prioritise", "prioritize", "explain why",
           "implication"]
LONG_PROMPT_CHARS = 1500


def detect_difficulty(prompt: str) -> tuple[str, str]:
    """Returns (easy|medium|hard, reason). Keyword tiers; hard beats medium beats easy; long prompts bump one level."""
    p = prompt.lower()
    hard = [k for k in HARD_KW if k in p]
    med = [k for k in MEDIUM_KW if k in p]
    easy = [k for k in EASY_KW if k in p]
    if hard:
        level, reason = "hard", f"hard keywords {hard[:3]}"
    elif med:
        level, reason = "medium", f"medium keywords {med[:3]}"
    elif easy:
        level, reason = "easy", f"easy keywords {easy[:3]}"
    else:
        level, reason = "medium", "no task keywords, default medium"
    if len(prompt) > LONG_PROMPT_CHARS and level != "hard":
        level = {"easy": "medium", "medium": "hard"}[level]
        reason += f" + long prompt ({len(prompt)} chars) bumps to {level}"
    return level, reason


# --- 3. workload (Lookup 1) --------------------------------------------------------
WORKLOAD_RULES = [  # checked in order, first match wins; only used by classifier="rules"/"hybrid"
    ("classification", ["classify", "classification", "label", "categor", "intent", "sentiment", "yes or no", "वर्गीकृत", "श्रेणी"]),
    ("translation", ["translate", "translation", "अनुवाद", "மொழிபெயர்", "అనువదించ", "into english", "into hindi", "into telugu", "into tamil", "in english"]),
    ("call_centre_summary", ["call", "transcript", "agent:", "customer:", "कॉल", "अझைப்ப", "ఏజెంట్", "एजेंट"]),
    ("document_extraction", ["extract", "निकालिए", "निकालें", "invoice", "receipt", "contract", "json", "fields"]),
]


def detect_workload_rules(prompt: str) -> tuple[str, str]:
    p = prompt.lower()
    for wl, kws in WORKLOAD_RULES:
        hit = [k for k in kws if k in p]
        if hit:
            return wl, f"rules {wl} {hit[:2]}"
    return "unknown", "rules: no workload keywords"


def classify_workload(prompt: str, classifier: str) -> tuple[str, str]:
    wl, reason = detect_workload_rules(prompt)
    if classifier == "rules" or (classifier == "hybrid" and wl != "unknown"):
        return wl, reason
    from classifier import deberta_workload
    wl, reason, _ = deberta_workload(prompt)
    return wl, reason


# --- 4. difficulty (Lookup 2) ------------------------------------------------------
def classify_difficulty(prompt: str, classifier: str) -> tuple[str, str]:
    """rules | deberta | hybrid. DeBERTa is a local non-generative encoder (classifier.py); its time lands in
    router_overhead_ms because route() wraps this call, and its token cost is zero."""
    level, reason = detect_difficulty(prompt)
    if classifier == "rules":
        return level, reason
    from classifier import deberta_difficulty  # lazy: torch is optional
    if classifier == "deberta":
        d_level, d_reason, _ = deberta_difficulty(prompt)
        return d_level, d_reason
    if "no task keywords" in reason:  # hybrid: rules were unsure
        d_level, d_reason, _ = deberta_difficulty(prompt)
        return d_level, f"rules unsure, {d_reason}"
    return level, reason


# --- 5. route: three lookups, two rules --------------------------------------------
def route(prompt: str, mode: str | None = None, classifier: str | None = None) -> dict:
    """Decide the tier for a prompt. Never sees hidden labels. Returns decision + overhead_ms.
    mode: None = derive the priority from the detected workload (normal operation); or force one of
    speed | cost | balanced | quality (benchmark sensitivity runs). classifier: deberta | rules | hybrid."""
    t0 = time.perf_counter()
    classifier = classifier or ROUTER_CLASSIFIER
    workload, wreason = classify_workload(prompt, classifier)              # Lookup 1
    priority = mode or WORKLOAD_PRIORITY.get(workload, DEFAULT_PRIORITY)   # workload -> what the customer cares about
    if priority not in ROUTE_TABLE:
        raise ValueError(f"unknown mode {priority}")
    difficulty, dreason = classify_difficulty(prompt, classifier)          # Lookup 2
    lang, is_indic = detect_language(prompt)
    if is_indic and difficulty != "hard":                                  # Indic rule
        tier = "indic"
        why = f"{workload} ({priority}), {difficulty}, {lang} -> Sarvam (Indic rule)"
    else:
        tier = ROUTE_TABLE[priority][difficulty]                           # Lookup 3
        why = f"{workload} ({priority}{' forced' if mode else ''}), {difficulty}, {lang} -> {tier}"
    return {"tier": tier, "workload": workload, "priority": priority, "language": lang, "is_indic": is_indic,
            "difficulty": difficulty, "why": why, "detail": f"{wreason}; {dreason}",
            "classifier": classifier, "router_overhead_ms": round((time.perf_counter() - t0) * 1000, 3)}


def next_tier(tier: str):
    return NEXT_TIER.get(tier)
