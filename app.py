import os
import json
import time
from io import BytesIO
from PIL import Image
import streamlit as st
from pypdf import PdfReader
from google import genai
from google.genai import types

st.set_page_config(page_title="AI Mock Test Engine", page_icon="⏱️", layout="wide")

# Check for API key in secrets, environment, or session state
API_KEY = st.secrets.get("GEMINI_API_KEY", os.environ.get("GEMINI_API_KEY", ""))

if "stage" not in st.session_state:
    st.session_state.stage = "upload"
if "questions" not in st.session_state:
    st.session_state.questions = []
if "user_answers" not in st.session_state:
    st.session_state.user_answers = {}
if "start_time" not in st.session_state:
    st.session_state.start_time = None
if "duration_secs" not in st.session_state:
    st.session_state.duration_secs = 600

def extract_questions_with_gemini(client, media_parts, raw_text_context=""):
    prompt = """
    Extract all multiple choice questions from this content.
    Ensure:
    1. Complete questions including equations, number/letter series, or statements.
    2. Exactly 4 clean choices/options per question without 'A)', 'B)' labels.
    3. The 0-based index of the correct answer (0 for A, 1 for B, 2 for C, 3 for D).
    4. A concise explanation of the solution.
    """
    
    contents = [prompt]
    if raw_text_context:
        contents.append(f"Document Text:\n{raw_text_context}")
    contents.extend(media_parts)

    response = client.models.generate_content(
        model="gemini-3.6-flash",
        contents=contents,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema={
                "type": "ARRAY",
                "items": {
                    "type": "OBJECT",
                    "properties": {
                        "question": {"type": "STRING"},
                        "options": {"type": "ARRAY", "items": {"type": "STRING"}},
                        "correct_answer": {"type": "INTEGER"},
                        "explanation": {"type": "STRING"}
                    },
                    "required": ["question", "options", "correct_answer"]
                }
            }
        )
    )
    return json.loads(response.text)

# -----------------------------------------------------------------------------
# STAGE 1: UPLOAD & EXTRACTION
# -----------------------------------------------------------------------------
if st.session_state.stage == "upload":
    st.title("📄 Image & PDF Question Paper to Mock Test")
    st.caption("Upload question paper files to convert them into structured text and launch a timed test.")

    active_key = API_KEY
    if not active_key:
        active_key = st.text_input("Gemini API Key:", type="password")

    uploaded_files = st.file_uploader(
        "Upload Question Papers (Images or PDF):", 
        type=["png", "jpg", "jpeg", "pdf"], 
        accept_multiple_files=True
    )

    if uploaded_files and st.button("🚀 Extract Questions & Build Mock"):
        if not active_key:
            st.error("Please provide a Gemini API Key to continue.")
        else:
            with st.spinner("Extracting questions, options, and solutions..."):
                try:
                    # Fix for AQ. keys requiring the explicit x-goog-api-key header
                    client = genai.Client(
                        api_key=active_key.strip(),
                        http_options={"headers": {"x-goog-api-key": active_key.strip()}}
                    )

                    media_parts = []
                    extracted_text = ""

                    for file in uploaded_files:
                        if file.type == "application/pdf":
                            pdf_reader = PdfReader(BytesIO(file.read()))
                            for page in pdf_reader.pages:
                                extracted_text += (page.extract_text() or "") + "\n"
                        else:
                            img = Image.open(file)
                            media_parts.append(img)

                    parsed_questions = extract_questions_with_gemini(client, media_parts, extracted_text)
                    if parsed_questions:
                        st.session_state.questions = parsed_questions
                        st.session_state.user_answers = {i: None for i in range(len(parsed_questions))}
                        st.session_state.stage = "configure"
                        st.rerun()
                    else:
                        st.error("No questions could be identified. Please try a clearer scan.")
                except Exception as e:
                    st.error(f"Error during extraction: {e}")

# -----------------------------------------------------------------------------
# STAGE 2: REVIEW & TEST SETTINGS
# -----------------------------------------------------------------------------
elif st.session_state.stage == "configure":
    st.title("⚙️ Configure Test Parameters")
    st.write(f"**Successfully extracted {len(st.session_state.questions)} questions.**")

    col1, col2, col3 = st.columns(3)
    with col1:
        duration_mins = st.number_input("Test Duration (minutes):", min_value=1, max_value=180, value=10)
    with col2:
        pos_marks = st.number_input("Marks for Correct (+):", min_value=1.0, value=2.0)
    with col3:
        neg_marks = st.number_input("Negative Marking (-):", min_value=0.0, value=0.5)

    st.session_state.pos_marks = pos_marks
    st.session_state.neg_marks = neg_marks

    with st.expander("Review / Edit Extracted Questions", expanded=False):
        for idx, q in enumerate(st.session_state.questions):
            st.markdown(f"**Q{idx+1}:** {q['question']}")
            for opt_idx, opt in enumerate(q['options']):
                st.write(f"- {chr(65+opt_idx)}. {opt}")
            st.write(f"*Correct:* Option {chr(65+q['correct_answer'])}")
            st.divider()

    if st.button("▶️ Begin Timed Exam"):
        st.session_state.duration_secs = duration_mins * 60
        st.session_state.start_time = time.time()
        st.session_state.stage = "test"
        st.rerun()

# -----------------------------------------------------------------------------
# STAGE 3: ACTIVE TIMED MOCK TEST
# -----------------------------------------------------------------------------
elif st.session_state.stage == "test":
    elapsed = time.time() - st.session_state.start_time
    remaining = int(st.session_state.duration_secs - elapsed)

    if remaining <= 0:
        st.warning("⏰ Time is up! Submitting your test automatically...")
        st.session_state.stage = "result"
        st.rerun()

    mins, secs = divmod(remaining, 60)
    
    col_title, col_time = st.columns([3, 1])
    with col_title:
        st.title("📝 Mock Test in Progress")
    with col_time:
        st.metric("⏳ Time Remaining", f"{mins:02d}:{secs:02d}")

    for idx, q in enumerate(st.session_state.questions):
        st.subheader(f"Q{idx + 1}. {q['question']}")
        selected_idx = st.radio(
            f"Select answer for Q{idx+1}:",
            options=range(len(q["options"])),
            format_func=lambda i, options=q["options"]: f"{chr(65+i)}. {options[i]}",
            key=f"q_{idx}",
            index=st.session_state.user_answers.get(idx)
        )
        st.session_state.user_answers[idx] = selected_idx
        st.divider()

    col_sub1, col_sub2 = st.columns([4, 1])
    with col_sub2:
        if st.button("🏁 Submit Test Final", type="primary"):
            st.session_state.stage = "result"
            st.rerun()

    time.sleep(1)
    st.rerun()

# -----------------------------------------------------------------------------
# STAGE 4: SCORECARD & EXPLANATIONS
# -----------------------------------------------------------------------------
elif st.session_state.stage == "result":
    st.title("📊 Examination Scorecard")

    correct = 0
    wrong = 0
    skipped = 0

    for idx, q in enumerate(st.session_state.questions):
        ans = st.session_state.user_answers.get(idx)
        if ans is None:
            skipped += 1
        elif ans == q["correct_answer"]:
            correct += 1
        else:
            wrong += 1

    total_score = (correct * st.session_state.pos_marks) - (wrong * st.session_state.neg_marks)
    max_score = len(st.session_state.questions) * st.session_state.pos_marks

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Final Score", f"{total_score:.2f} / {max_score}")
    c2.metric("Correct", f"{correct} (+{correct * st.session_state.pos_marks})")
    c3.metric("Wrong", f"{wrong} (-{wrong * st.session_state.neg_marks})")
    c4.metric("Unattempted", skipped)

    st.subheader("💡 Detailed Question Analysis")
    for idx, q in enumerate(st.session_state.questions):
        user_ans = st.session_state.user_answers.get(idx)
        is_correct = user_ans == q["correct_answer"]
        status_label = "✅ Correct" if is_correct else ("❌ Incorrect" if user_ans is not None else "⚪ Skipped")

        with st.expander(f"Q{idx+1}: {status_label} - {q['question'][:80]}..."):
            st.markdown(f"**Question:** {q['question']}")
            for opt_idx, opt in enumerate(q["options"]):
                prefix = f"{chr(65+opt_idx)}."
                if opt_idx == q["correct_answer"]:
                    st.success(f"{prefix} {opt} (Correct Answer)")
                elif opt_idx == user_ans:
                    st.error(f"{prefix} {opt} (Your Answer)")
                else:
                    st.write(f"{prefix} {opt}")
            
            if q.get("explanation"):
                st.info(f"**Explanation:** {q['explanation']}")

    if st.button("🔄 Retake or Upload New Paper"):
        st.session_state.stage = "upload"
        st.session_state.questions = []
        st.session_state.user_answers = {}
        st.rerun()
