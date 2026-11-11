import streamlit as st
from google import genai

import logos_core as core

MODEL = gemini-3.5-flash-lite  # check the current model name in Google AI Studio

st.set_page_config(page_title="LOGOS Q-OPE v4.0", layout="wide")
st.title("LOGOS Q-OPE v4.0")
st.caption("Deterministic calculations in code, AI analysis with enforced rules, automatic output check.")

# ---- API key: Streamlit Secrets first, sidebar as fallback ----
api_key = None
try:
    api_key = st.secrets.get("GEMINI_API_KEY")
except Exception:
    pass
if not api_key:
    api_key = st.sidebar.text_input("Gemini API key (Google AI Studio):", type="password")
st.sidebar.warning("Do not enter real client data on a free API tier. Check the provider's data-use terms.")

# ---- inputs ----
c1, c2 = st.columns(2)
with c1:
    industry = st.text_input("Industry", "Commercial Aviation & Hospitality Logistics")
    entity_type = st.text_input("Entity type", "Airline / Conglomerate")
    currency = st.text_input("Currency", "EUR")
    liquidity = st.number_input("Current liquidity", value=8_000_000.0, step=1.0, format="%.0f")
    monthly_expenses = st.number_input("Monthly fixed expenses", value=72_000_000.0, step=1.0, format="%.0f")
    total_debt = st.number_input("Total debts and liabilities", value=1_200_000_000.0, step=1.0, format="%.0f")
with c2:
    fcf = st.number_input("Free cash flow (monthly, negative = burn)", value=-64_000_000.0, step=1.0, format="%.0f")
    net_margin = st.number_input("Net profit margin (%)", value=-18.4)
    liquidity_ratio = st.number_input("Current liquidity ratio", value=0.08)
    retention = st.number_input("Customer retention rate (%)", value=31.0)

description = st.text_area("Describe the business situation and main bottlenecks (be specific)", height=160)

if st.button("Run analysis", type="primary"):
    result = core.build_facts(industry, entity_type, description, currency, liquidity,
                              monthly_expenses, total_debt, fcf, net_margin,
                              liquidity_ratio, retention)

    if result["status"] == "STOP":
        st.error(result["error"])
        st.stop()
    if not api_key:
        st.error("Missing Gemini API key.")
        st.stop()

    facts, mode = result["facts"], result["mode"]
    for w in result["warnings"]:
        if w.startswith("INCONSISTENT"):
            st.warning(w)
    st.info(f"Computed by code. Mode: {mode}")

    client = genai.Client(api_key=api_key)
    block = core.user_block(facts, description)

    try:
        with st.spinner("Step 1/3: structural analysis..."):
            a = core.ask(client, MODEL, core.LENS_A_SYSTEM, f"OPERATING MODE: {mode}\n\n{block}")
        with st.spinner("Step 2/3: ground-reality stress test..."):
            b = core.ask(client, MODEL, core.LENS_B_SYSTEM,
                         f"OPERATING MODE: {mode}\n\n{block}\n\nANALYST A:\n{a}")
        with st.spinner("Step 3/3: synthesis..."):
            synth_user = (f"OPERATING MODE: {mode}\n\n{block}\n\n"
                          f"ANALYST A (structural):\n{a}\n\nANALYST B (ground reality):\n{b}")
            final = core.ask(client, MODEL, core.SYNTH_SYSTEM, synth_user)

        violations = core.find_violations(final, facts, description)
        retried = False
        if violations:
            retried = True
            with st.spinner("Output check found unsupported numbers, regenerating once..."):
                fix = (synth_user + "\n\nYOUR PREVIOUS DRAFT USED THESE NUMBERS THAT ARE NOT IN THE "
                       f"FACTS: {', '.join(violations)}. Rewrite the memo without them (use words or "
                       "'Not determinable from the provided data').")
                final = core.ask(client, MODEL, core.SYNTH_SYSTEM, fix)
                violations = core.find_violations(final, facts, description)
    except Exception as e:
        st.error(f"AI call failed (often a rate limit on the free tier). Wait a minute and retry. Details: {e}")
        st.stop()

    if violations:
        st.warning("Output check: these numbers are not backed by your input, treat them as unverified: "
                   + ", ".join(violations))
    else:
        st.success("Output check passed: no numbers beyond your input and the computed figures"
                   + (" (after one regeneration)." if retried else "."))

    st.markdown("---")
    st.markdown(final)

    with st.expander("Audit trail (inputs, computed facts, intermediate analyses)"):
        st.subheader("Computed facts (code)")
        st.code(facts)
        st.subheader("Analyst A: structural lens (AI-generated text)")
        st.write(a)
        st.subheader("Analyst B: ground-reality lens (AI-generated text)")
        st.write(b)
