import os
import io
import json
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any
import cv2
import easyocr
import numpy as np
from PIL import Image
from pydantic import BaseModel, Field, field_validator, ValidationError

# Upgraded to google-genai
from google import genai
from google.genai import types, errors
from dotenv import load_dotenv

from fastapi import FastAPI, File, UploadFile, Header, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware

# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nid-backend")

app = FastAPI(title="Bangladeshi NID Information Extraction API")

# Enable CORS for frontend integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global variables
DATA_DIR = "data"
DB_FILE = os.path.join(DATA_DIR, "processed_nids.json")
ocr_reader = None

# Ensure data directory exists
os.makedirs(DATA_DIR, exist_ok=True)
if not os.path.exists(DB_FILE):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump([], f, ensure_ascii=False, indent=4)

# Pydantic schema for Gemini output
class NIDDetails(BaseModel):
    name: str = Field(description="The English name printed on the NID directly. Keep exactly as printed.")
    fatherName: str = Field(description="English transliterated father's name from Bangla")
    motherName: str = Field(description="English transliterated mother's name from Bangla")
    dateOfBirth: str = Field(description="Date of birth in YYYY-MM-DD format")
    nidNumber: str = Field(description="National ID number (digits only, remove all spaces/hyphens)")
    presentAddress: str = Field(description="English transliterated present address from Bangla (labeled 'ঠিকানা)")
    permanentAddress: str = Field(description="English transliterated permanent address from Bangla. Sourced from a field labeled 'Place of Birth'. Must NEVER be a copy of presentAddress field — if no distinct source text exists, return an empty string.")

    @field_validator("nidNumber")
    @classmethod
    def validate_nid_length(cls, v: str) -> str:
        # Sanitize any accidental spaces or hyphens just in case
        clean_v = v.replace(" ", "").replace("-", "").strip()
        
        # Enforce exact Bangladeshi NID length standards (Old = 10 or 13, Smart Card = 17)
        if len(clean_v) not in (10, 13, 17):
            raise ValueError(f"NID number has an invalid length ({len(clean_v)} digits). It must be exactly 10, 13, or 17 digits.")
        return clean_v

# Response schema
class ExtractionResponse(BaseModel):
    data: NIDDetails
    already_processed: bool
    existing_data: Optional[NIDDetails] = None
    front_raw_text: str
    back_raw_text: str
    message: str
    warnings: List[str] = Field(default_factory=list)


class UpdateRequest(BaseModel):
    nidNumber: str = Field(description="NID number of the existing record to update (used to locate it)")
    updatedData: NIDDetails = Field(description="The new data to overwrite the existing record with")


class UpdateResponse(BaseModel):
    message: str
    data: NIDDetails

class UnreadableImageError(Exception):
    """Raised when an image can't be decoded, or OCR extracts no usable text from it."""


SUPPORTED_CONTENT_TYPES = {"image/jpeg", "image/jpg", "image/png"}
SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png"}


def validate_image_format(file: UploadFile, label: str) -> None:
    """
    Enforce the supported input formats: JPG, JPEG, PNG.
    """
    content_type_ok = (file.content_type or "").lower() in SUPPORTED_CONTENT_TYPES
    ext = os.path.splitext(file.filename or "")[1].lower()
    ext_ok = ext in SUPPORTED_EXTENSIONS

    if not (content_type_ok or ext_ok):
        ext_display = f", extension '{ext}'" if ext else ""
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"{label} image: unsupported file format "
                f"(content-type '{file.content_type or 'unknown'}'{ext_display}). "
                f"Supported formats: JPG, JPEG, PNG."
            )
        )

def image_preprocessing(image_bytes: bytes) -> bytes:
    """
    Decodes image bytes, applies Grayscale and CLAHE processing via OpenCV, 
    and re-encodes it back to bytes for downstream processing.
    """
    # 1. Convert raw bytes into a NumPy array format that OpenCV understands
    nparr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    
    if img is None:
        raise UnreadableImageError("OpenCV failed to decode the raw image bytes.")
        
    # 2. Apply your image enhancement pipeline
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
    clahe_img = clahe.apply(gray)
    
    # 3. Re-encode the processed frame back into JPEG bytes
    success, encoded_img = cv2.imencode(".jpg", clahe_img)
    if not success:
        raise UnreadableImageError("Failed to re-encode processed image matrix to bytes.")
        
    return encoded_img.tobytes()

def get_ocr_reader():
    """Lazy load EasyOCR reader to save memory and startup time."""
    global ocr_reader
    if ocr_reader is None:
        logger.info("Initializing EasyOCR reader for Bangla and English...")
        ocr_reader = easyocr.Reader(["en", "bn"])  # Set gpu=True if GPU is available
        logger.info("EasyOCR initialized successfully.")
    return ocr_reader

def run_easy_ocr(image_bytes: bytes) -> str:
    """
    Run OCR on the image bytes using EasyOCR and return raw text.
    """
    try:
        image = Image.open(io.BytesIO(image_bytes))
        image.verify()  
    except Exception as e:
        raise UnreadableImageError(f"Could not decode image: {str(e)}")

    try:
        image = Image.open(io.BytesIO(image_bytes))
        img_np = np.array(image)
        reader = get_ocr_reader()
        results = reader.readtext(img_np, detail=0)
    except UnreadableImageError:
        raise
    except Exception as e:
        logger.error(f"Error during OCR: {str(e)}")
        raise UnreadableImageError(f"OCR processing failed: {str(e)}")

    text = "\n".join(results).strip()
    if not text:
        raise UnreadableImageError("No readable text was found in the image.")
    return text

def load_db() -> List[Dict[str, Any]]:
    """Load processed NIDs database."""
    try:
        if not os.path.exists(DB_FILE):
            return []
        with open(DB_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error reading DB: {str(e)}")
        return []

def save_to_db(record: Dict[str, Any]):
    """Save a processed NID to the database."""
    try:
        db = load_db()
        record_to_save = record.copy()
        record_to_save["processedAt"] = datetime.now().isoformat()
        db.append(record_to_save)
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump(db, f, ensure_ascii=False, indent=4)
        logger.info(f"Successfully saved record for {record.get('name', 'Unknown')} to DB.")
    except Exception as e:
        logger.error(f"Error saving to DB: {str(e)}")

def check_duplicate(nid_number: str) -> Optional[Dict[str, Any]]:
    """Check if the NID combination is already in the database based strictly on NID Number."""
    db = load_db()
    clean_nid = nid_number.strip()
    for record in db:
        rec_nid = str(record.get("nidNumber", "")).strip()
        if rec_nid == clean_nid:
            return record
    return None

def update_record(nid_number: str, new_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Overwrite an existing record (matched strictly by NID number) with new_data.
    """
    db = load_db()
    clean_nid = nid_number.strip()
    for i, record in enumerate(db):
        rec_nid = str(record.get("nidNumber", "")).strip()
        if rec_nid == clean_nid:
            updated_record = new_data.copy()
            updated_record["processedAt"] = record.get("processedAt", datetime.now().isoformat())
            updated_record["updatedAt"] = datetime.now().isoformat()
            db[i] = updated_record
            with open(DB_FILE, "w", encoding="utf-8") as f:
                json.dump(db, f, ensure_ascii=False, indent=4)
            logger.info(f"Successfully updated record for NID: {nid_number}.")
            return updated_record
    raise ValueError(f"No existing record found for NID '{nid_number}' to update.")

def delete_record(nid_number: str) -> bool:
    """
    Filter out and remove a record from the JSON database file strictly by NID Number.
    """
    db = load_db()
    clean_nid = nid_number.strip()
    initial_length = len(db)
    
    # Rebuild the list, excluding the target NID number
    db = [record for record in db if str(record.get("nidNumber", "")).strip() != clean_nid]
    
    # If the list shrank, it means we successfully found and removed the entry
    if len(db) < initial_length:
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump(db, f, ensure_ascii=False, indent=4)
        logger.info(f"Successfully deleted record for NID: {nid_number}.")
        return True
        
    return False

@app.get("/api/history", response_model=List[Dict[str, Any]])
def get_history():
    """Retrieve history of processed NIDs."""
    return load_db()

@app.post("/api/update", response_model=UpdateResponse)
def update_nid_record(payload: UpdateRequest):
    """
    Overwrite an existing DB record with newly extracted data.
    """
    try:
        # FIX: Matches the streamlined signature using solely nidNumber 
        updated = update_record(payload.nidNumber, payload.updatedData.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    return UpdateResponse(message="Record updated successfully.", data=NIDDetails(**updated))

@app.delete("/api/delete/{nid_number}")
def delete_nid_record(nid_number: str):
    """
    Endpoint to erase an existing database record using its NID string.
    """
    try:
        if delete_record(nid_number):
            return {"message": "Record deleted successfully."}
        
        # Fallback if the user passes an NID that isn't actually in our JSON database
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail=f"No record matching NID '{nid_number}' exists in the history database."
        )
    except Exception as e:
        logger.error(f"Failed to execute database deletion block: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server database error during deletion."
        )
        
@app.post("/api/extract", response_model=ExtractionResponse)
async def extract_nid_info(
    front_image: UploadFile = File(None),
    back_image: UploadFile = File(None),
    x_gemini_api_key: Optional[str] = Header(None)
):
    if not front_image or not back_image:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Both Front and Back NID images are required."
        )

    validate_image_format(front_image, "Front")
    validate_image_format(back_image, "Back")

    # Resolve Gemini API Key
    api_key = x_gemini_api_key or os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Gemini API Key is missing. Please provide it in the X-Gemini-API-Key header or configure GEMINI_API_KEY on the server."
        )

    try:
        front_bytes = await front_image.read()
        back_bytes = await back_image.read()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Error reading uploaded images: {str(e)}"
        )

    # 2. Apply the updated image preprocessing directly to the bytes!
    try:
        front_bytes = image_preprocessing(front_bytes)
        # Only process back image bytes if they exist and don't match placeholders
        if back_bytes:
            try:
                back_bytes = image_preprocessing(back_bytes)
            except Exception as ocr_err:
                # If the optional back image processing fails, let it fallback gracefully
                logger.warning(f"Back image preprocessing failed: {str(ocr_err)}")
    except UnreadableImageError as preprocess_err:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Image enhancement preprocessing failed: {str(preprocess_err)}"
        )

    warnings: List[str] = []

    # --- Front OCR: Required
    logger.info("Running OCR on Front image...")
    try:
        front_text = run_easy_ocr(front_bytes)
    except UnreadableImageError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Front image is unreadable ({str(e)}). Please provide a clear, well-lit photo of the NID front."
        )

    # --- Back OCR: Optional
    logger.info("Running OCR on Back image...")
    back_text = ""
    try:
        back_text = run_easy_ocr(back_bytes)
    except UnreadableImageError as e:
        warning_msg = (
            f"Back image could not be read ({str(e)}). Returning front-side "
            f"data only — address fields may be missing or incomplete."
        )
        logger.warning(warning_msg)
        warnings.append(warning_msg)

    # Call Google GenAI Client
    try:
        client = genai.Client(api_key=api_key)

        back_section = (
            f"=== RAW OCR TEXT FROM NID BACK ===\n{back_text}"
            if back_text
            else "=== RAW OCR TEXT FROM NID BACK ===\n(Not available — the back image could not be read. "
                 "Leave presentAddress and permanentAddress as empty strings rather than guessing.)"
        )

        prompt = f"""
You are an expert Bangladeshi National Identity (NID) card parser.
Below is the raw, noisy OCR text extracted from the front and back of a Bangladeshi NID card using EasyOCR.

=== RAW OCR TEXT FROM NID FRONT ===
{front_text}

{back_section}

Your task:
1. Parse this text to find the owner's Name, Father's Name, Mother's Name, Date of Birth, NID Number, Present Address, and Permanent Address.
2. The NID FRONT has a "Name" field printed in English (labeled "Name") and Bangla (labeled "নাম"). No need to use the Bangla version. Name may contain Block Letters but ensure Title Case capitalization (e.g. "SWAPAN PODDER" -> "Swapan Podder").
3. The fields "Father's Name" (পিতা) and "Mother's Name" (মাতা) are written in Bangla. Perform phonetic transliteration from Bangla to English for these fields (e.g. "স্বপন পোদ্দার" -> "Swapan Podder", "আব্দুল করিম" -> "Abdul Karim").
4. Address fields - read this carefully, these are two DIFFERENT pieces of text on the card, never the same line:
   - 'presentAddress' comes from the field labeled "ঠিকানা".
   - 'permanentAddress' comes from a field labeled "Place of Birth" or "জন্মস্থান"।
   - 'presentAddress' must be transliterated Bangla-to-English the same way as names.
   - If "জন্মস্থান" in the OCR text, then phonetic transliteration is required for permanentAddress as well. 'Place of Birth' in OCR text is always in English, so no transliteration is needed for that.
   - Under NO circumstances copy the Present Address text into permanentAddress. They come from separate lines in the OCR text. If you genuinely cannot find distinct source text for permanentAddress (no Place of Birth label), return an empty string for it — do not fall back to reusing presentAddress.
5. The Date of Birth (labeled "Date of Birth") and NID Number (labeled "NID No" or "ID NO.") are already printed in English digits. Extract and format them (Date of Birth in YYYY-MM-DD format, NID Number with digits only, no spaces or hyphens).
6. Clean up any OCR spelling typos, fix word merges, split jammed text blocks, and apply standard Title Case capitalization to names and address structures to make them look professional.
7. If a field's source text is unavailable or you cannot confidently determine it, return an empty string for that field rather than guessing.
"""
        model_name = "gemini-3.1-flash-lite"
        logger.info(f"Calling Gemini model ({model_name}) for structuring & transliteration...")
        
        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=NIDDetails
            )
        )

        extracted_data_dict = json.loads(response.text)
        details = NIDDetails(**extracted_data_dict)

        # --- MANDATORY IDENTITY FIELD VALIDATION ---
        mandatory_fields = ["name", "fatherName", "motherName", "dateOfBirth", "nidNumber"]
        for field in mandatory_fields:
            val = getattr(details, field)
            if val is None or str(val).strip() == "":
                logger.error(f"Validation failed. Mandatory field '{field}' was returned as empty or None.")
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail="IMAGE_ERROR: The core information on the NID could not be parsed securely. Please upload a clearer image."
                )
        # -------------------------------------------

    except HTTPException:
        # Re-raise explicit field validation errors directly 
        raise

    except ValidationError as e:
        # Extract the exact string message from our Pydantic validator
        error_msg = e.errors()[0]["msg"]
        logger.error(f"Pydantic Validation failed: {error_msg}")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"NID Validation Error: {error_msg}"
        )

    except errors.APIError as e:
        if e.code == 429:
            logger.error(f"Gemini API quota/rate limit exceeded: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Gemini API rate limit or quota exceeded. Please wait a moment and try again."
            )
        elif e.code == 503:
            logger.error(f"Gemini API currently unavailable (high demand): {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="The AI model is currently experiencing high demand and is temporarily unavailable. Please try again in a few moments."
            )
        elif e.code in (401, 403):
            logger.error(f"Gemini API key rejected: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid Gemini API Key. Please check the key in the sidebar (or the server's GEMINI_API_KEY) and try again."
            )
        elif e.code == 400:
            if "api key" in str(e.message).lower() or "api key" in str(e).lower():
                logger.error(f"Gemini API key rejected: {str(e)}")
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid Gemini API Key. Please check the key in the sidebar (or the server's GEMINI_API_KEY) and try again."
                )
            logger.error(f"Gemini processing failed: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="IMAGE_ERROR: Please provide a clear Front and Back Image."
            )
        else:
            logger.error(f"Gemini processing failed: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="IMAGE_ERROR: Please provide a clear Front and Back Image."
            )

    except Exception as e:
        logger.error(f"Gemini processing failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="IMAGE_ERROR: Please provide a clear Front and Back Image."
        )

    # Check for duplicates strictly against the NID number
    existing_record = check_duplicate(details.nidNumber)

    if existing_record:
        logger.info(f"Duplicate found strictly for NID: {details.nidNumber}")
        
        # Safe structural dictionary parsing with default fallbacks
        existing_data = NIDDetails(
            name=existing_record.get("name", ""),
            fatherName=existing_record.get("fatherName", ""),
            motherName=existing_record.get("motherName", ""),
            dateOfBirth=existing_record.get("dateOfBirth", ""),
            nidNumber=existing_record.get("nidNumber", ""),
            presentAddress=existing_record.get("presentAddress", ""),
            permanentAddress=existing_record.get("permanentAddress", "")
        )
        return ExtractionResponse(
            data=details,
            already_processed=True,
            existing_data=existing_data,
            front_raw_text=front_text,
            back_raw_text=back_text,
            message="This NID is already in the database. Review the newly extracted data below and choose whether to update the existing record.",
            warnings=warnings
        )
    else:
        details_dict = details.model_dump()
        save_to_db(details_dict)
        success_message = (
            "NID front-side information processed and saved successfully. "
            "Back-side fields (address) are incomplete — see warnings below."
            if warnings else
            "NID information processed and saved successfully."
        )
        return ExtractionResponse(
            data=details,
            already_processed=False,
            existing_data=None,
            front_raw_text=front_text,
            back_raw_text=back_text,
            message=success_message,
            warnings=warnings
        )

