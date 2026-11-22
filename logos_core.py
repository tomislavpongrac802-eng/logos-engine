"""LOGOS Q-OPE core logic v4.1 (no UI). Deterministic math, validation, prompts."""
import re
import time
from decimal import Decimal, InvalidOperation

# --------------------------------------------------------------------
# Industry consistency check
# --------------------------------------------------------------------
INDUSTRIES = {
    "aviation_travel": ["airline", "aviation", "airspace", "jet fuel", "flight", "flights",
                        "aircraft", "airport", "fleet", "travel agencies",
                        "zrakoplov", "avio", "zračn"],
    "hospitality": ["hotel", "hotels", "hospitality", "tourism", "resort", "hotelsk",
                    "turizam", "turistič"],
    "retail": ["retail", "supermarket", "grocery", "sku", "skus", "store", "stores",
               "shelf", "e-commerce", "merchandise", "trgovin", "maloprodaj"],
    "tech_services": ["software", "saas", "agency", "consulting", "it services",
                      "startup", "platform", "b2b", "outsourcing", "programer",
                      "it agencij", "software development"],
    "manufacturing": ["manufacturing", "factory", "production line", "assembly",
                      "plant", "industrial", "proizvodnj", "tvornic"],
    "construction": ["construction", "contractor", "real estate", "property developer",
                     "građevin"],
    "finance": ["bank", "banking", "insurance", "lending", "fintech", "asset management"],
    "healthcare": ["hospital", "clinic", "pharma", "healthcare", "medical", "bolnic"],
    "energy": ["oil", "gas", "utility", "energy", "refinery", "power plant", "energij"],
}


def detect_category(text):
    if not text:
        return None
    t = str(text).lower()
    best, best_hits = None, 0
    for cat, words in INDUSTRIES.items():
        hits = 0
        for w in words:
            pattern = r"\b" + re.escape(w) if len(w) > 5 else r"\b" + re.escape(w) + r"\b"
            if re.search(pattern, t):
                hits += 1
        if hits > best_hits:
            best, best_hits = cat, hits
    return best


def _fmt(x):
    return f"{x:,.0f}"


# --------------------------------------------------------------------
# Deterministic calculation + validation
# --------------------------------------------------------------------
def build_facts(industry, entity_type, description, currency, liquidity,
                monthly_expenses, total_debt, fcf, net_margin, liquidity_ratio, retention):
    """Returns dict: status (OK/WARN/STOP), mode, facts, error, warnings."""
    errors, warnings = [], []

    if liquidity is None or liquidity < 0:
        errors.append("Liquidity must be a number, 0 or greater.")
    if monthly_expenses is None or monthly_expenses <= 0:
        errors.append("Monthly fixed expenses must be greater than zero.")
    if total_debt is None or total_debt < 0:
        errors.append("Total debts must be a number, 0 or greater.")
    if not description or len(description.strip()) < 20:
        errors.append("Business situation description is missing or too short.")
    if errors:
        return {"status": "STOP", "mode": "NORMAL", "facts": "", "warnings": [],
                "error": "Analysis stopped. Fix the input first: " + " ".join(errors)}

    cat_ind, cat_ent, cat_desc = (detect_category(industry), detect_category(entity_type),
                                  detect_category(description))
    cats = {c for c in (cat_ind, cat_ent, cat_desc) if c}
    inconsistent = len(cats) > 1
    if inconsistent:
        warnings.append(
            f"INCONSISTENT INPUT: industry field suggests '{cat_ind or 'unknown'}', entity type "
            f"suggests '{cat_ent or 'unknown'}', description suggests '{cat_desc or 'unknown'}'. "
            "The description takes precedence.")

    burn_fcf = -fcf if (fcf is not None and fcf < 0) else None
    burn_used = burn_fcf if burn_fcf else monthly_expenses
    if burn_fcf is None:
        warnings.append("FCF missing or not negative: runway based on fixed expenses only (zero-revenue case).")
    warnings.append("FCF and fixed expenses are assumed to be MONTHLY figures in the same currency.")

    runway_m = liquidity / burn_used
    runway_d = runway_m * 30
    worst_m = liquidity / monthly_expenses
    worst_d = worst_m * 30
    shortfall = max(burn_used - liquidity, 0)
    debt_mult = (total_debt / liquidity) if liquidity > 0 else None
    mode = "CRISIS" if runway_d < 30 else "NORMAL"

    if mode == "NORMAL" and worst_d < 60:
        warnings.append(
            f"WATCH: if all revenue stopped, cash would last only {worst_d:.1f} days "
            f"({worst_m:.2f} months). The current runway depends on revenue continuing.")

    lines = [
        "VERIFIED FACTS (computed by code, the ONLY numbers you may use):",
        f"- Industry (user field): {industry}",
        f"- Entity type (user field): {entity_type}",
        f"- Detected industry from description: {cat_desc or 'unknown'}",
        f"- Currency: {currency}",
        f"- Liquidity: {_fmt(liquidity)}",
        f"- Monthly fixed expenses: {_fmt(monthly_expenses)}",
        f"- Total debts and liabilities: {_fmt(total_debt)}",
    ]
    if fcf is not None:
        lines.append(f"- Free cash flow (monthly): {_fmt(fcf)}")
    if net_margin is not None:
        lines.append(f"- Net profit margin: {net_margin:g}%")
    if liquidity_ratio is not None:
        lines.append(f"- Current liquidity ratio (as entered): {liquidity_ratio:g}")
    if retention is not None:
        lines.append(f"- Customer retention rate: {retention:g}%")
    lines += [
        f"- Runway (monthly burn {_fmt(burn_used)}): {runway_m:.2f} months = {runway_d:.1f} days",
        f"- Runway (zero revenue, fixed expenses only): {worst_m:.2f} months = {worst_d:.1f} days",
        f"- Cash shortfall to cover one month of burn: {_fmt(shortfall)}",
    ]
    if debt_mult is not None:
        lines.append(f"- Debt to liquidity multiple: {debt_mult:.1f}x")
    lines.append(f"- Operating mode: {mode}")
    lines.append("DATA WARNINGS:")
    lines += [f"- {w}" for w in warnings]

    return {"status": "WARN" if inconsistent else "OK", "mode": mode,
            "facts": "\n".join(lines), "error": "", "warnings": warnings}


# --------------------------------------------------------------------
# Output validator (locale aware) + assumption tags
# --------------------------------------------------------------------
_NUM = re.compile(
    r"(?<![\w.,])\d+(?:[.,]\d+)*\s?"
    r"(?:%|million|billion|thousand|milijun\w*|milijard\w*|tisuć\w*|percent\w*|posto\w*|bps|[kKmMbB]\b)?")
_TAG = re.compile(r"\[ASSUMPTION:[^\]]*\]", re.I)


def _dec(x):
    try:
        return format(Decimal(x).normalize(), "f")
    except InvalidOperation:
        return x


def _forms(body):
    if re.fullmatch(r"\d{1,3}(,\d{3})+(\.\d+)?", body):          # 1,200,000.5
        return [_dec(body.replace(",", ""))]
    if re.fullmatch(r"\d{1,3}(\.\d{3})+(,\d+)?", body):          # 85.000 or 1.200.000,5
        return [_dec(body.replace(".", "").replace(",", "."))]
    if re.fullmatch(r"\d+,\d{1,2}", body):                       # 3,8 (decimal comma)
        return [_dec(body.replace(",", "."))]
    if re.fullmatch(r"\d+(\.\d+)?", body):                       # 3.8
        return [_dec(body)]
    return [_dec(p) for p in re.split(r"[.,]", body) if p]       # lists like 1,2,3


def _extract(text):
    out = []
    for m in _NUM.finditer(text or ""):
        s = m.group(0).strip().lower().replace(" ", "")
        mm = re.match(r"^([\d.,]+)([^\d.,]*)$", s)
        if not mm:
            continue
        body, suf = mm.groups()
        for n in _forms(body):
            out.append((n, suf))
    return out


def check_output(output_text, facts, description):
    """Returns dict: violations (list), assumptions (list of tag strings)."""
    assumptions = [a.strip() for a in _TAG.findall(output_text or "")]
    cleaned = _TAG.sub(" ", output_text or "")

    allowed = set()
    for n, suf in _extract(facts) + _extract(description):
        allowed.add(n + suf)
        if suf == "%":
            allowed.add(n)

    bad = []
    for n, suf in _extract(cleaned):
        if (n + suf) in allowed:
            continue
        try:
            val = Decimal(n)
        except InvalidOperation:
            continue
        if not suf and val == val.to_integral_value() and (val <= 365 or 1900 <= val <= 2100):
            continue  # day/week markers, step numbers, years
        bad.append(n + suf)
    return {"violations": sorted(set(bad)), "assumptions": assumptions}


# --------------------------------------------------------------------
# Prompts
# --------------------------------------------------------------------
LANGS = {
    "auto": "Write in the same language as the BUSINESS SITUATION text.",
    "hr": ("Write the entire memo, including all section headings, in Croatian. Keep every number in "
           "exactly the format used in the VERIFIED FACTS (period as decimal separator, comma as "
           "thousands separator); never convert numbers to Croatian format."),
    "en": "Write the entire memo, including all section headings, in English.",
}

RULES = """HARD RULES (a violation makes the answer invalid)
RULE 1. NUMBERS ONLY FROM THE FACTS. Write a number only if it appears exactly in the VERIFIED FACTS or in the user's description, copied with identical digits. Never round, abbreviate (no "8M"), convert or combine figures. Never invent percentages, margins, savings, forecasts, probabilities, bps or targets. Day and week markers (Day 1, Week 3) and step numbers are allowed. If you need a target or estimate that is not in the facts, you may write it ONLY inside a tag of the form [ASSUMPTION: short label = value], at most 5 such tags in the whole memo, and never anywhere else. If a figure is needed but missing, write "Not determinable from the provided data".
RULE 2. THE DESCRIPTION DEFINES THE BUSINESS. Identify the real industry from the description. If the Industry or Entity Type field contradicts it, say so in one line and follow the description. Every recommendation must be physically, legally and economically possible for that industry. Respect every constraint the user stated, do not invent resources they did not mention, and never propose an option the user has excluded (for example government aid or new equity) as an action.
RULE 3. NO THEATRE. Never claim the analysis is verified, validated, simulated, compliant or secured. No probabilities or confidence percentages: use Low / Medium / High. Banned words: foolproof, guaranteed, quantum, prophecy, sovereign, combat, asymmetric, black swan. No role-play dialogue and no invented quotes.
RULE 4. CRISIS BRANCH. If OPERATING MODE is CRISIS (runway under 30 days), the memo begins Phase 1 with a "First 72 hours" sequence in strict order, then contains ONLY survival and liquidity actions: (1) 7-day cash preservation and payment prioritization; (2) creditor engagement (standstill, forbearance, restructuring, debt-for-equity); (3) formal protection options suited to the jurisdiction (jurisdiction not provided: local insolvency counsel must confirm); (4) liquidity from assets (sale-and-leaseback, non-core disposals, sale of licences or slots where relevant); (5) external capital or state support only if the description does not exclude them; (6) stakeholder negotiations (labour, key suppliers, intermediaries holding funds). No pricing tweaks, layout, marketing or margin expansion in Phase 1. State plainly if the figures show the business cannot be stabilized without creditor consent or formal proceedings.
RULE 5. DEVELOPMENT IS EARNED AND CONTEXTUAL. Phase 2 is conditional on Phase 1 succeeding; state the gate condition in words. In CRISIS mode Phase 2 is a conditional path (which core business to keep or exit, how to rebuild after restructuring), not a growth-marketing plan. Growth levers must come from the actual industry and context. Digital attention channels may be proposed only when the business has direct consumer demand to capture.
RULE 6. Never mention rule numbers or these internal instructions in the output.
RULE 7. LIKELIHOOD must be justified in one short clause. Anything that depends on another party's consent (creditors, banks, unions, clients, intermediaries, courts) is at most Medium unless the description gives a concrete reason for more.
RULE 8. COVERAGE. Every distinct problem named in the description must be addressed by at least one action, or explicitly marked "not addressable with the provided information" with a reason.
RULE 9. CONCRETE ACTIONS. Every Phase 1 action must say exactly what is done, who owns it (a role, not a name), when (Day or Week), and the observable signal that shows it works (no invented numbers). Vague actions such as "tightly control overhead" or "manage debt" are not allowed; name the specific costs, contracts or decisions.
RULE 10. If the DATA WARNINGS contain a WATCH item, address it in the Diagnosis in plain words and reflect it in Phase 1.
RULE 11. If the description mentions lost clients, falling demand, price pressure or revenue decline, include a section "Revenue recovery and new demand" with concrete, industry-specific channels, offers and first steps (who to approach, what to offer, in what order).
"""


def _sys(role_text, lang):
    return role_text + "\n\n" + RULES + "\n" + LANGS.get(lang, LANGS["auto"])


def lens_a_system(lang="auto"):
    return _sys(
        "You are Analyst A in the LOGOS engine: the STRUCTURAL lens. You apply creative-destruction "
        "economics (what is structurally dying and must be exited) and strategic positioning (where the "
        "business can still hold ground). These are analytical lenses; do not role-play historical figures.\n"
        "Task: in at most 350 words, state (a) what is structurally broken, (b) what must be cut or exited, "
        "(c) which strategic position is still defensible, (d) the 3 most important moves.", lang)


def lens_b_system(lang="auto"):
    return _sys(
        "You are Analyst B in the LOGOS engine: the GROUND-REALITY lens. You represent employees, customers, "
        "unions, suppliers, intermediaries, and the current market and consumer climate. You stress-test "
        "Analyst A.\n"
        "Task: in at most 350 words, list (a) where Analyst A's plan is unrealistic or ignores people and "
        "execution, (b) what the market and consumers actually do right now, (c) what must be added or changed.",
        lang)


SYNTH_FORMAT = """
OUTPUT FORMAT (markdown, concise, no emojis)
# LOGOS // STRATEGIC STABILIZATION & DEVELOPMENT MEMO
(Input inconsistency note only if the DATA WARNINGS require it.)
## 1. Core Insight
The root of the problem beyond the figures, 3 to 5 sentences.
## 2. Diagnosis
Runway, shortfall, debt multiple and liquidity ratio exactly as in the facts, interpreted for this industry. Address any WATCH item.
## 3. Phase 1: Stabilization (Day 1 to 30)
(In CRISIS mode start with "First 72 hours".) Subsections "Financial defense" and "Organizational stability". Each action as:
- Action: ...
- Owner and timing: role, Day or Week
- Rationale: ...
- Key assumption: ...
- Main risk: ...
- Likelihood: Low/Medium/High, with a short reason
- Success signal: observable, no invented numbers
## 4. Revenue recovery and new demand
Only if Rule 11 applies; otherwise omit this section.
## 5. Phase 2: Future Development (Day 31 onward)
Gate condition, strategic repositioning, industry-specific growth levers (same action format), capabilities to build, leading indicators to monitor (names only).
## 6. Scenarios
Downside, Base, Upside: one short paragraph each, with the trigger event. No probabilities.
## 7. Problem coverage
A list: each problem from the description and the action that addresses it (or why it is not addressable).
## 8. What We Do Not Know
Missing data that could change the advice.
## 9. Bottom Line
Two sentences maximum, then: "This memo is decision support, not legal or financial advice. Confirm with qualified restructuring counsel." (translate this sentence if the memo language is not English)
"""


def synth_system(lang="auto"):
    return _sys(
        "You are the synthesizer of the LOGOS engine, a senior restructuring and strategy analyst. Tone: "
        "direct, precise, institutional. Combine Analyst A and Analyst B into one decision memo. Where they "
        "disagree, decide and say why.", lang) + SYNTH_FORMAT


# --------------------------------------------------------------------
# LLM wrapper (google-genai SDK)
# --------------------------------------------------------------------
def ask(client, model, system, user, temperature=0.3, retries=2):
    from google.genai import types
    last = None
    for attempt in range(retries + 1):
        try:
            resp = client.models.generate_content(
                model=model, contents=user,
                config=types.GenerateContentConfig(system_instruction=system,
                                                   temperature=temperature))
            return resp.text or ""
        except Exception as e:  # rate limits, network, etc.
            last = e
            time.sleep(3 * (attempt + 1))
    raise last


def user_block(facts, description):
    return f"{facts}\n\nBUSINESS SITUATION (user-written):\n{description}"
