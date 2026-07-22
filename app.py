import datetime
import os
import re
import uuid
from google import genai
import fitz  # PyMuPDF
from gtts import gTTS
import streamlit as st

# Configure the Streamlit Page
st.set_page_config(page_title="Uni Journal AI Reader", page_icon="📚", layout="wide")

st.title("📚 Uni Journal Article AI Reader & Summariser")
st.markdown(
    "Upload university PDF journal articles, generate instant study summaries via Gemini AI, and listen to smooth audio narrations."
)


# --- FEATURE 1: AUTOMATIC SERVER CLEANUP LOOP ---
def cleanup_old_audio_files(max_age_minutes=10):
    """Scans the local directory and deletes any generated audio files older than max_age_minutes."""
    now = datetime.datetime.now()
    current_dir = os.getcwd()

    for filename in os.listdir(current_dir):
        if filename.startswith("journal_audio_") and filename.endswith(".mp3"):
            file_path = os.path.join(current_dir, filename)
            try:
                file_time = datetime.datetime.fromtimestamp(
                    os.path.getmtime(file_path)
                )
                age = (now - file_time).total_seconds() / 60

                if age > max_age_minutes:
                    os.remove(file_path)
            except Exception:
                pass  # Avoid crashing if a file is currently being locked/read by a user


# Run the cleanup loop every time the app updates or a button is clicked
cleanup_old_audio_files(max_age_minutes=10)


# Function to cleanly extract and normalise text from academic PDFs
def extract_clean_text(pdf_file, start_page, end_page):
    doc = fitz.open(stream=pdf_file.read(), filetype="pdf")
    full_text = []

    s_idx = max(0, start_page - 1)
    e_idx = min(len(doc), end_page)

    for page_num in range(s_idx, e_idx):
        page = doc.load_page(page_num)
        blocks = page.get_text("blocks")
        for b in blocks:
            raw_text = b[4]  # Unpack the 5th element which holds the text string
            text = raw_text.strip()

            if (
                not text
                or text.isdigit()
                or "downloaded from" in text.lower()
                or "copyright" in text.lower()
            ):
                continue

            # Fix Broken Hyphenated Words and line breaks for flow
            text = re.sub(r"(\w+)-\s*\n+\s*(\w+)", r"\1\2", text)
            text = re.sub(r"(?<!\n)\n(?!\n)", " ", text)
            full_text.append(text)

    return "\n\n".join(full_text), len(doc)


# Function to automatically skip academic reference brackets
def skip_academic_references(text):
    parentheses_pattern = r"\([A-Za-z\s\.,&;-]+,\s*\d{4}[a-z]?\)"
    text = re.sub(parentheses_pattern, "", text)
    brackets_pattern = r"\[\d+(?:\s*,\s*\d+|\s*-\s*\d+)*\]"
    text = re.sub(brackets_pattern, "", text)
    text = re.sub(r" {2,}", " ", text)
    text = re.sub(r"\s+([,\.!;\?])", r"\1", text)
    return text.strip()


# --- FEATURE 2: BULLETPROOF GOOGLE TTS AUDIO GENERATION ---
def generate_speech(text, tts_lang, tts_accent, speed_fast=False):
    """Generates audio tracks via Google's official cloud endpoints."""
    unique_id = uuid.uuid4().hex[:8]
    output_filename = f"journal_audio_{unique_id}.mp3"

    # Compile the text using Google Text to Speech
    # tld parameter handles local accents (e.g., 'com.au' for Australian)
    tts = gTTS(text=text, lang=tts_lang, tld=tts_accent, slow=False)

    # Save the file down to the Streamlit local disk space
    tts.save(output_filename)

    # Note: gTTS doesn't support micro-slider speed adjustments (like +25%).
    # It has a standard "Normal" speed and an intentional "Slow" toggle for accessibility.
    return output_filename


# --- FEATURE 3: GEMINI AI SUMMARISATION ENGINE ---
def generate_gemini_summary(text, api_key):
    """Sends extracted text to Gemini to create structural, copy-pasteable university study notes."""
    try:
        client = genai.Client(api_key=api_key)

        prompt = (
            "You are an expert university research assistant in public health and epidemiology. Analyse the following text extracted from an academic journal article. "
            "Provide a highly structured summary tailored for university study notes. Your summary must include:\n"
            "1. **Core Objective**: What is the main thesis or purpose of this section?\n"
            "2. **Key Arguments / Findings**: Bullet points outlining the critical discoveries or arguments.\n"
            "3. **Methodology or Context** (if mentioned): How did they arrive at this?\n"
            "4. **Significance**: Why does this matter for broader research?\n\n"
            f"Here is the text to summarise:\n\n{text}"
        )

        response = client.models.generate_content(
            model="gemini-3.6-flash",
            contents=prompt,
        )
        return response.text
    except Exception as e:
        return f"⚠️ Summary Generation Failed: {str(e)}"


# Sidebar Configuration
st.sidebar.header("🎛️ Audio Settings")

# Silently fetch your prepaid key from the backend environment
gemini_key = st.secrets.get("GEMINI_API_KEY", "")

# Google Accent Mapping
voices_dict = {
    "🇦🇺 Australian English": {"lang": "en", "tld": "com.au"},
    "🇬🇧 British English": {"lang": "en", "tld": "co.uk"},
    "🇺🇸 American English": {"lang": "en", "tld": "com"},
}
selected_voice = st.sidebar.selectbox("Choose AI Accent", list(voices_dict.keys()))
lang_code = voices_dict[selected_voice]["lang"]
tld_code = voices_dict[selected_voice]["tld"]

st.sidebar.markdown("---")
st.sidebar.header("📝 Text Filtering")
skip_refs = st.sidebar.checkbox("Enable Reference Skipper", value=True)

# Main Layout: File Uploader
uploaded_file = st.file_uploader(
    "Step 1: Upload your Journal Article (PDF)", type=["pdf"]
)

if uploaded_file:
    temp_doc = fitz.open(stream=uploaded_file.getvalue(), filetype="pdf")
    total_pages = len(temp_doc)
    temp_doc.close()

    st.success(f"Successfully loaded: {uploaded_file.name} ({total_pages} pages)")

    col1, col2 = st.columns(2)
    with col1:
        start_page = st.number_input(
            "Start Reading from Page", min_value=1, max_value=total_pages, value=1
        )
    with col2:
        end_page = st.number_input(
            "End Reading at Page",
            min_value=1,
            max_value=total_pages,
            value=min(2, total_pages),
        )

    if start_page > end_page:
        st.error("Error: Start page cannot be greater than the end page.")
    else:
        # Step 2: Extract Text
        if st.button("📝 Step 2: Extract & Clean Text"):
            uploaded_file.seek(0)
            with st.spinner("Parsing academic text layouts and fixing line wraps..."):
                extracted_text, _ = extract_clean_text(
                    uploaded_file, start_page, end_page
                )
                if skip_refs:
                    extracted_text = skip_academic_references(extracted_text)
                st.session_state["extracted_text"] = extracted_text

        # Display functional steps side-by-side once text exists
        if "extracted_text" in st.session_state and st.session_state["extracted_text"]:

            # Layout Split: Left for Summary, Right for Audio Playback
            left_col, right_col = st.columns(2)

            with left_col:
                st.subheader("💡 Option A: AI Study Summary")
                if not gemini_key:
                    st.info(
                        "ℹ️ Ensure your GEMINI_API_KEY is configured in your Streamlit Cloud Secrets dashboard."
                    )
                else:
                    if st.button("✨ Generate AI Study Notes"):
                        with st.spinner("Gemini is reading the text..."):
                            summary_result = generate_gemini_summary(
                                st.session_state["extracted_text"], gemini_key
                            )
                            st.session_state["ai_summary"] = summary_result

                if "ai_summary" in st.session_state:
                    st.markdown(st.session_state["ai_summary"])

            with right_col:
                st.subheader("🔊 Option B: Generate AI Audio narration")
                if st.button("🎬 Generate Audio Track"):
                    with st.spinner("Generating stable Google AI narration..."):
                        try:
                            # Generate speech via official Google endpoints
                            audio_file = generate_speech(
                                st.session_state["extracted_text"],
                                lang_code,
                                tld_code,
                            )

                            st.audio(audio_file, format="audio/mp3")

                            with open(audio_file, "rb") as f:
                                filename_base = os.path.splitext(uploaded_file.name)[0]
                                st.download_button(
                                    label="💾 Download MP3 to your Device",
                                    data=f,
                                    file_name=f"{filename_base}_narration.mp3",
                                    mime="audio/mp3",
                                )
                        except Exception as e:
                            st.error(f"Failed to generate speech: {str(e)}")

            # Collapsible Text Preview at the bottom
            st.markdown("---")
            with st.expander("📄 View Extracted Raw Text Preview"):
                st.text_area(
                    "Raw clean text block fed into AI models:",
                    st.session_state["extracted_text"],
                    height=200,
                )
