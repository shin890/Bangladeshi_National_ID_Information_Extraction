import os
import json
import requests
import streamlit as st
from PIL import Image

# Page Configuration
st.set_page_config(
    page_title="Bangladeshi NID Extractor",
    page_icon="💳",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom Premium Styling (Vanilla CSS)
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
    }
    
    /* Header styling */
    .main-header {
        background: linear-gradient(135deg, #1e3c72 0%, #2a5298 100%);
        color: white;
        padding: 2rem 2.5rem;
        border-radius: 12px;
        margin-bottom: 2rem;
        box-shadow: 0 4px 15px rgba(30, 60, 114, 0.2);
    }
    
    .main-header h1 {
        margin: 0;
        font-size: 2.2rem;
        font-weight: 700;
        letter-spacing: -0.5px;
    }
    
    .main-header p {
        margin: 0.5rem 0 0 0;
        font-size: 1.1rem;
        opacity: 0.9;
        font-weight: 300;
    }
    
    /* Card design */
    .info-card {
        background-color: #ffffff;
        border: 1px solid #eef2f6;
        border-radius: 10px;
        padding: 1.5rem;
        margin-bottom: 1rem;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.02);
        transition: transform 0.2s ease, box-shadow 0.2s ease;
    }
    
    .info-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 8px 16px rgba(0, 0, 0, 0.05);
    }
    
    .card-label {
        font-size: 0.85rem;
        font-weight: 600;
        text-transform: uppercase;
        color: #718096;
        margin-bottom: 0.3rem;
        letter-spacing: 0.5px;
    }
    
    .card-value {
        font-size: 1.15rem;
        font-weight: 500;
        color: #2d3748;
    }
    
    .card-value-highlight {
        font-size: 1.3rem;
        font-weight: 700;
        color: #1a365d;
    }

    
    /* Sidebar adjustments */
    .sidebar .sidebar-content {
        background-color: #f7fafc;
    }
</style>
""", unsafe_allow_html=True)

# Backend API URL
API_URL = os.getenv("BACKEND_API_URL", "http://127.0.0.1:8000")

# Sidebar
with st.sidebar:
    st.markdown(
        """
        <div style="text-align:center; margin-bottom: 0.5rem;">
            <svg width="64" height="64" viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">
                <rect x="4" y="12" width="56" height="40" rx="6" fill="#2a5298"/>
                <rect x="4" y="12" width="56" height="40" rx="6" fill="none" stroke="#1e3c72" stroke-width="2"/>
                <circle cx="20" cy="30" r="7" fill="#ffffff"/>
                <path d="M10 46c0-6 6-9 10-9s10 3 10 9" fill="#ffffff"/>
                <rect x="36" y="24" width="18" height="3" rx="1.5" fill="#ffffff"/>
                <rect x="36" y="31" width="18" height="3" rx="1.5" fill="#ffffff" opacity="0.8"/>
                <rect x="36" y="38" width="12" height="3" rx="1.5" fill="#ffffff" opacity="0.6"/>
            </svg>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown("### Configuration")
    
    # API Key Handling
    api_key_env = os.getenv("GEMINI_API_KEY", "")
    api_key_input = st.text_input(
        "Gemini API Key",
        value=api_key_env if api_key_env else "",
        type="password",
        help="Provide your Gemini API key. If configured in the server's .env file, you can leave this blank."
    )
    
    st.markdown("---")
    st.markdown("""
    ### About
    This tool extracts structured details from **Bangladeshi National Identity (NID)** cards:
    * **OCR Engine:** Local EasyOCR
    * **Processing Engine:** Google Gemini (cleaning, structuring, and phonetic transliteration)
    * **Duplicate Check:** Verified against history database
    """)
    st.info("💡 Make sure to upload clear, high-resolution front and back images for the best results.")

    st.markdown(
    """
    <div style="text-align:center; margin-top: 2rem; font-size: 0.9rem; color: #718096;">
        🧑‍💻 Developed by <b>Shuva Podder</b><br>
        📧 <a href="mailto:shuva.podder.kuet@outlook.com">shuva.podder.kuet@outlook.com</a><br>
        📧 <a href="mailto:letters429@gmail.com">letters429@gmail.com</a>
    </div>
    """,
    unsafe_allow_html=True
)


# App Header
st.markdown("""
<div class="main-header">
    <h1>Bangladeshi NID Information Extractor</h1>
    <p>Upload Front and Back NID card images to extract information in structured JSON format.</p>
</div>
""", unsafe_allow_html=True)

# Main Application Tabs
tab1, tab2 = st.tabs(["📤 Extract Information", "📜 History & Database"])

with tab1:
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("### 1. Upload NID Front Side")
        front_file = st.file_uploader("Upload NID Front Side", type=["jpg", "jpeg", "png"])
        if front_file:
            st.image(front_file, caption="NID Front Preview", width=320)

    with col2:
        st.markdown("### 2. Upload NID Back Side")
        back_file = st.file_uploader("Upload NID Back Side", type=["jpg", "jpeg", "png"])
        if back_file:
            st.image(back_file, caption="NID Back Preview", width=320)

    # Process Button
    st.markdown("---")
    extract_btn = st.button("🚀 Extract Information", use_container_width=True, type="primary")

    if extract_btn:
        # Front/Back image validation check
        if not front_file or not back_file:
            st.error("❌ Both Front and Back NID images are required to perform the extraction. Please upload both sides.")
        else:
            headers = {}
            if api_key_input:
                headers["X-Gemini-API-Key"] = api_key_input

            files = {
                "front_image": (front_file.name, front_file.getvalue(), front_file.type),
                "back_image": (back_file.name, back_file.getvalue(), back_file.type),
            }

            with st.spinner("🕵️‍♂️ Running local OCR and processing with Gemini... Please wait."):
                try:
                    response = requests.post(f"{API_URL}/api/extract", files=files, headers=headers)

                    if response.status_code == 200:
                        # Stored in session_state (not a local variable) so the result —
                        # and the Update button below — survive Streamlit's rerun on
                        # every subsequent interaction, instead of vanishing.
                        st.session_state["extraction_result"] = response.json()
                    elif response.status_code == 401:
                        st.session_state.pop("extraction_result", None)
                        st.error("🔑 Unauthorized: Gemini API Key is missing or invalid. Please check your config in the sidebar.")
                    else:
                        st.session_state.pop("extraction_result", None)
                        error_detail = response.json().get("detail", "Unknown backend error")
                        if isinstance(error_detail, str) and error_detail.startswith("IMAGE_ERROR"):
                            # Gemini couldn't make sense of the images (API error,
                            # safety block, malformed output, etc.) — shown as a
                            # warning, not a hard error, since re-uploading a
                            # clearer photo is a normal, expected next step.
                            st.warning("⚠️ Image Error: Please provide a clear Front and Back Image.")
                        else:
                            st.error(f"❌ {error_detail}")

                except requests.exceptions.ConnectionError:
                    st.session_state.pop("extraction_result", None)
                    st.error("🔌 Could not connect to the backend server. Make sure the FastAPI backend is running.")
                except Exception as e:
                    st.session_state.pop("extraction_result", None)
                    st.error(f"💥 An unexpected error occurred: {str(e)}")

    # Render whatever the most recent extraction produced. Reading from
    # session_state (rather than only right after the button click) is what
    # lets the Update button below keep working across reruns.
    result = st.session_state.get("extraction_result")

    if result:
        data = result["data"]
        already_processed = result["already_processed"]
        existing_data = result.get("existing_data")

        # Surface any graceful-degradation warnings (e.g. back image unreadable)
        for warning_msg in result.get("warnings", []):
            st.warning(f"⚠️ {warning_msg}")

        def render_info_cards(details: dict):
            st.markdown(f"""
            <div class="info-card">
                <div class="card-label">Full Name (English)</div>
                <div class="card-value-highlight">{details['name']}</div>
            </div>
            <div class="info-card">
                <div class="card-label">Father's Name (Transliterated)</div>
                <div class="card-value">{details['fatherName']}</div>
            </div>
            <div class="info-card">
                <div class="card-label">Mother's Name (Transliterated)</div>
                <div class="card-value">{details['motherName']}</div>
            </div>
            <div class="info-card">
                <div class="card-label">Date of Birth</div>
                <div class="card-value">{details['dateOfBirth']}</div>
            </div>
            <div class="info-card">
                <div class="card-label">National ID Number</div>
                <div class="card-value-highlight">{details['nidNumber']}</div>
            </div>
            <div class="info-card">
                <div class="card-label">Present Address (Transliterated)</div>
                <div class="card-value">{details['presentAddress']}</div>
            </div>
            <div class="info-card">
                <div class="card-label">Permanent Address (Transliterated)</div>
                <div class="card-value">{details['permanentAddress']}</div>
            </div>
            """, unsafe_allow_html=True)

        if already_processed:
            st.info(f"ℹ️ **This NID is already in the database:** {existing_data['name']} (ID: {existing_data['nidNumber']}).")

            res_col1, res_col2 = st.columns(2)
            with res_col1:
                st.markdown("### 📁 Existing Record (in database)")
                render_info_cards(existing_data)
            with res_col2:
                st.markdown("### 🆕 Newly Extracted Information")
                render_info_cards(data)

                update_btn = st.button("🔁 Update Existing Record with New Information", use_container_width=True, type="primary")
                if update_btn:
                    try:
                        update_resp = requests.post(
                            f"{API_URL}/api/update",
                            json={
                                "nidNumber": existing_data["nidNumber"],
                                "name": existing_data["name"],
                                "updatedData": data,
                            },
                        )
                        if update_resp.status_code == 200:
                            st.success("✅ Record updated successfully.")
                            # Reflect the update immediately: the DB now matches
                            # the newly extracted data, so treat it as such.
                            st.session_state["extraction_result"]["already_processed"] = False
                            st.session_state["extraction_result"]["existing_data"] = None
                            st.rerun()
                        else:
                            err = update_resp.json().get("detail", "Unknown error")
                            st.error(f"❌ Update failed: {err}")
                    except requests.exceptions.ConnectionError:
                        st.error("🔌 Could not connect to the backend server.")

            st.caption("If you don't click Update, the existing database record is left unchanged.")

            with st.expander("🔍 View Raw Front OCR Text"):
                st.text(result.get("front_raw_text", ""))
            with st.expander("🔍 View Raw Back OCR Text"):
                st.text(result.get("back_raw_text", ""))

        else:
            st.success("✅ NID extracted and saved to history successfully!")

            res_col1, res_col2 = st.columns([2, 1])
            with res_col1:
                st.markdown("### Extracted Information")
                render_info_cards(data)

            with res_col2:
                st.markdown("### Structured Output (JSON)")
                formatted_json = json.dumps(data, indent=4)
                st.code(formatted_json, language="json")

                st.download_button(
                    label="📥 Download JSON",
                    data=formatted_json,
                    file_name=f"nid_{data['nidNumber']}.json",
                    mime="application/json",
                    use_container_width=True
                )

                with st.expander("🔍 View Raw Front OCR Text"):
                    st.text(result.get("front_raw_text", ""))
                with st.expander("🔍 View Raw Back OCR Text"):
                    st.text(result.get("back_raw_text", ""))

with tab2:
    st.markdown("### Processed NID Database History")
    
    # Reload button
    refresh_btn = st.button("🔄 Refresh History", use_container_width=False)
    
    try:
        response = requests.get(f"{API_URL}/api/history")
        if response.status_code == 200:
            history_data = response.json()
            
            if not history_data:
                st.info("Empty database. Upload and process some NIDs first.")
            else:
                st.markdown(f"Total processed records: **{len(history_data)}**")
                
                # Display history entries in a clean table or cards
                for idx, record in enumerate(reversed(history_data)):
                    # Use unique key for the expander
                    with st.expander(f"💳 {record['name']} — ID: {record['nidNumber']} (Processed on {record.get('processedAt', 'N/A')[:10]})"):
                        col_h1, col_h2 = st.columns(2)
                        with col_h1:
                            st.markdown(f"**Father's Name:** {record['fatherName']}")
                            st.markdown(f"**Mother's Name:** {record['motherName']}")
                            st.markdown(f"**Date of Birth:** {record['dateOfBirth']}")
                        with col_h2:
                            st.markdown(f"**Present Address:** {record['presentAddress']}")
                            st.markdown(f"**Permanent Address:** {record['permanentAddress']}")
                            
                        # Raw JSON download for this item
                        st.markdown("---")
                        formatted_rec = json.dumps(record, indent=4)
                        st.code(formatted_rec, language="json")
                        
        else:
            st.error("Failed to load history from backend.")
    except requests.exceptions.ConnectionError:
        st.error("🔌 Backend server offline. Cannot fetch history.")
    except Exception as e:
        st.error(f"Error: {str(e)}")
