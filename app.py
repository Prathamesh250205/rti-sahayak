"""Streamlit entry point: conversational RTI application drafting assistant."""
import streamlit as st

import llm.client as llm_client
from agent.drafter import compose_letter, gather_grounding, understand_request
from agent.intake import IntakeState, is_complete, next_question, process_reply
from export.pdf_writer import build_pdf
from rag.retriever import RetrieverError
from rag.retriever import warm_up as warm_up_retriever

CSS_STYLES = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Source+Serif+4:wght@400;600&display=swap');

html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

.block-container { padding-top: 1.6rem; padding-bottom: 6rem; max-width: 920px; }
[data-testid="stVerticalBlock"] { gap: 0.5rem; }

[data-testid="stChatMessage"] {
    border-radius: 10px; border: 1px solid #E4DDD0; padding: 0.7rem 1rem;
    margin-bottom: 0.4rem; background: #FFFFFF;
    box-shadow: 0 1px 3px rgba(27, 58, 92, 0.06);
}
[data-testid="stSidebar"] { background-color: #EDE7DD; }
[data-testid="stSidebar"] .block-container { padding-top: 1.5rem; }
.stButton > button { border-radius: 8px; border: 1px solid #D8D2C4; }
.stDownloadButton > button {
    background-color: #1B3A5C; color: #FFFFFF; border-radius: 8px;
    border: none; padding: 0.6rem 1.4rem; font-weight: 600; width: 100%;
}
.stDownloadButton > button:hover { background-color: #14293F; color: #FFFFFF; }
[data-testid="stTextArea"] textarea {
    font-family: 'Source Serif 4', Georgia, serif; font-size: 0.95rem; line-height: 1.6;
}
.disclaimer-box {
    background: #FFF6E5; border: 1px solid #E8C97A; border-radius: 10px;
    padding: 0.65rem 0.85rem; font-size: 0.82rem; color: #5C4A1E; line-height: 1.4;
}
.card {
    border: 1px solid #D8D2C4; border-radius: 10px; padding: 0.9rem 1rem;
    background: #FFFFFF; box-shadow: 0 1px 4px rgba(27, 58, 92, 0.07);
}
.field-done { color: #1B3A5C; font-weight: 500; }
.field-missing { color: #A7A196; }
.provider-badge {
    display: inline-block; background: #E3ECF3; color: #1B3A5C;
    border-radius: 20px; padding: 0.15rem 0.7rem; font-size: 0.8rem; font-weight: 600;
}
.check-box {
    display: inline-block; width: 10px; height: 10px; margin-right: 8px;
    border: 1.5px solid #A7A196; border-radius: 2px; vertical-align: middle;
}
.check-box.done { background: #1B3A5C; border-color: #1B3A5C; }
.authority-note { color: #6B6558; font-size: 0.78rem; }
.stepper-step {
    text-align: center; padding: 0.35rem 0.2rem 0.4rem; border-bottom: 3px solid #D8D2C4;
    font-size: 0.8rem; font-weight: 500; color: #A7A196;
}
.stepper-step.stepper-done { border-bottom-color: #1B3A5C; color: #1B3A5C; }
.stepper-step.stepper-current { border-bottom-color: #1B3A5C; color: #1B3A5C; font-weight: 700; }
</style>
"""

FIELD_LABELS = {
    "full_name": "Full name",
    "address": "Address",
    "locality": "Locality / area",
    "timeframe": "Time period",
}

STEPPER_STAGES = ["Understand", "Authority", "Details", "Draft", "Export"]

EXAMPLE_PROMPTS = [
    "The streetlight on my road has been broken for 4 months and no one responds.",
    "My ration card renewal has been pending for over 3 months with no update.",
    "I complained about an overflowing drain outside my house 2 months ago and nothing has happened.",
]

DISCLAIMER = (
    "This is an informational drafting aid, not legal advice. Every procedural claim is grounded "
    "in retrieved RTI Act, 2005 text and cited by section — always verify the correct public "
    "authority and current fee before submitting."
)


def init_state():
    defaults = {
        "messages": [],
        "intake_state": None,
        "information_sought": None,
        "likely_authority": None,
        "draft_result": None,
        "last_provider": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def handle_user_message(text: str):
    st.session_state.messages.append({"role": "user", "content": text})

    if st.session_state.intake_state is None:
        st.session_state.intake_state = IntakeState(problem_description=text)

        try:
            with st.status("Reading your problem...", expanded=True) as status:
                status.write("Identifying what to ask for and the likely authority...")
                stream_area = st.empty()
                streamed = []

                def _on_chunk(chunk: str):
                    streamed.append(chunk)
                    stream_area.caption("".join(streamed))

                information_sought, likely_authority = understand_request(text, on_chunk=_on_chunk)
                stream_area.empty()
                st.session_state.information_sought = information_sought
                st.session_state.likely_authority = likely_authority
                st.session_state.last_provider = llm_client.LAST_PROVIDER_USED
                status.update(label="Authority identified", state="complete", expanded=False)
        except Exception:
            # Non-fatal - drafting can still proceed with a generic authority note.
            st.session_state.information_sought = []
            st.session_state.likely_authority = "Unknown — could not determine automatically"

        question = next_question(st.session_state.intake_state)
        st.session_state.messages.append(
            {
                "role": "assistant",
                "content": (
                    f"Thanks — I can help you draft an RTI application for that. Likely authority: "
                    f"**{st.session_state.likely_authority}** (best guess — please confirm the correct "
                    f"Public Information Officer and address before filing). "
                    f"A few details first: {question}"
                ),
            }
        )
        return

    state = st.session_state.intake_state

    if not is_complete(state):
        # Direct field assignment — no LLM call, so no spinner needed here.
        process_reply(state, text)

        if not is_complete(state):
            st.session_state.messages.append({"role": "assistant", "content": next_question(state)})
            return

    if st.session_state.draft_result is None:
        try:
            with st.status("Preparing your application...", expanded=True) as status:
                status.write("Retrieving relevant RTI Act sections...")
                grounding_chunks = gather_grounding()
                status.write(
                    f"Found {len(grounding_chunks)} relevant section(s)."
                    if grounding_chunks
                    else "No relevant sections found."
                )

                status.write("Drafting your application...")
                result = compose_letter(
                    state,
                    st.session_state.information_sought or [],
                    st.session_state.likely_authority or "Unknown — could not determine automatically",
                    grounding_chunks,
                )

                status.update(label="Application ready", state="complete", expanded=False)
        except Exception as e:
            st.session_state.messages.append(
                {"role": "assistant", "content": f"Sorry, I couldn't draft the application: {e}"}
            )
            return

        st.session_state.draft_result = result
        st.session_state.messages.append(
            {"role": "assistant", "content": "Your RTI application is ready below — review it, then download the PDF."}
        )
    else:
        st.session_state.messages.append(
            {"role": "assistant", "content": "Your application is already drafted below. Click **Start over** in the sidebar to draft a new one."}
        )


def render_stepper():
    state = st.session_state.intake_state
    completed = [
        state is not None,
        bool(st.session_state.likely_authority),
        state is not None and is_complete(state),
        st.session_state.draft_result is not None,
        st.session_state.draft_result is not None,
    ]
    current_idx = next((i for i, c in enumerate(completed) if not c), len(STEPPER_STAGES) - 1)
    cols = st.columns(len(STEPPER_STAGES))
    for i, (col, label) in enumerate(zip(cols, STEPPER_STAGES)):
        if completed[i]:
            css_class = "stepper-done"
        elif i == current_idx:
            css_class = "stepper-current"
        else:
            css_class = ""
        col.markdown(f'<div class="stepper-step {css_class}">{label}</div>', unsafe_allow_html=True)


def render_sidebar():
    with st.sidebar:
        st.markdown("### Application details")
        state = st.session_state.intake_state
        filled_count = sum(1 for f in FIELD_LABELS if state and state.slots.get(f, "").strip())
        st.progress(filled_count / len(FIELD_LABELS), text=f"{filled_count} of {len(FIELD_LABELS)} complete")
        for field, label in FIELD_LABELS.items():
            value = state.slots.get(field, "") if state else ""
            if value:
                st.markdown(
                    f'<span class="check-box done"></span><span class="field-done">{label}: {value}</span>',
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    f'<span class="check-box"></span><span class="field-missing">{label}</span>',
                    unsafe_allow_html=True,
                )

        authority = st.session_state.likely_authority
        if authority:
            st.markdown("### Identified authority")
            st.markdown(
                f'<div class="card"><strong>{authority}</strong><br>'
                f'<span class="authority-note">Best guess — please confirm the correct Public Information '
                f'Officer and address before filing.</span></div>',
                unsafe_allow_html=True,
            )

        st.markdown("### Sources")
        with st.expander("RTI Act sections used", expanded=False):
            result = st.session_state.draft_result
            if result is None:
                st.caption("Sources will appear here once your application is drafted.")
            elif not result.grounding_chunks:
                st.caption("No relevant RTI Act sections were retrieved for this draft.")
            else:
                for chunk in result.grounding_chunks:
                    st.markdown(f"**{chunk.section}** (p.{chunk.page})")
                    st.caption(chunk.text[:160].strip() + "...")

        provider = st.session_state.last_provider
        if provider:
            st.markdown(f'<span class="provider-badge">Served by: {provider.title()}</span>', unsafe_allow_html=True)

        st.markdown("---")
        if st.button("Start over", use_container_width=True):
            st.session_state.clear()
            st.rerun()

        st.markdown("---")
        st.markdown(f'<div class="disclaimer-box">{DISCLAIMER}</div>', unsafe_allow_html=True)


def render_draft():
    result = st.session_state.draft_result
    if result is None:
        return

    for warning in result.warnings:
        st.warning(warning)

    tab_application, tab_sections, tab_plain = st.tabs(["Application", "Cited sections", "Plain text"])

    with tab_application:
        edited_text = st.text_area(
            "Edit before exporting:",
            value=result.application_text,
            height=420,
            key="draft_text_area",
        )

    with tab_sections:
        if not result.grounding_chunks:
            st.caption("No relevant RTI Act sections were retrieved for this draft.")
        else:
            for chunk in result.grounding_chunks:
                st.markdown(f"**{chunk.section}** — {chunk.source}, p.{chunk.page}")
                st.caption(chunk.text)
                st.markdown("---")

    with tab_plain:
        st.code(edited_text, language=None, wrap_lines=True)

    try:
        pdf_bytes = build_pdf(edited_text)
        filename = f"RTI_Application_{(result.department_guess or 'draft')[:20].replace(' ', '_')}.pdf"
        st.download_button(
            "Download PDF",
            data=pdf_bytes,
            file_name=filename,
            mime="application/pdf",
            use_container_width=True,
        )
    except Exception as e:
        st.error(f"Couldn't generate the PDF ({e}). You can still copy the text above.")


def main():
    st.set_page_config(
        page_title="RTI Assistant",
        page_icon=None,
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.markdown(CSS_STYLES, unsafe_allow_html=True)
    init_state()

    # Pre-warm the cached embedding model/collection at startup (spinner shows
    # only on the very first call, process-wide) so the ~20s one-time load
    # never happens mid-conversation during a demo.
    try:
        warm_up_retriever()
    except RetrieverError:
        pass  # surfaced normally when retrieval is actually attempted later

    render_sidebar()

    st.markdown("## RTI Assistant")
    st.caption(
        "Describe a problem in plain language — I'll help you draft a formal RTI application, "
        "grounded in the RTI Act, 2005."
    )

    render_stepper()

    if not st.session_state.messages:
        st.markdown("**Try an example:**")
        cols = st.columns(3)
        for col, prompt in zip(cols, EXAMPLE_PROMPTS):
            if col.button(prompt, use_container_width=True):
                handle_user_message(prompt)
                st.rerun()

    for message in st.session_state.messages:
        is_assistant = message["role"] == "assistant"
        label = "Assistant" if is_assistant else "You"
        # A non-magic chat_message name (not "user"/"assistant"/"ai"/"human")
        # avoids Streamlit's built-in pictograph avatars entirely.
        chat_name = "rti-assistant-message" if is_assistant else "applicant-message"
        with st.chat_message(chat_name, avatar=None):
            st.markdown(f"**{label}**  \n{message['content']}")

    if st.session_state.draft_result is not None:
        render_draft()

    user_text = st.chat_input("Describe your problem, or answer the question above...")
    if user_text:
        handle_user_message(user_text)
        st.rerun()


if __name__ == "__main__":
    main()
