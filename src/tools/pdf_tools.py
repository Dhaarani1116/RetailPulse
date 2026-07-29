import fitz  # PyMuPDF
import pdfplumber

def read_pdf(file_path: str) -> str:
    """
    Extract all raw text content from a PDF file using pdfplumber, falling back to PyMuPDF.
    """
    text = ""
    # Try pdfplumber first
    try:
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
    except Exception:
        # Fallback to PyMuPDF (fitz)
        try:
            doc = fitz.open(file_path)
            for page in doc:
                text += page.get_text() + "\n"
        except Exception as e:
            text = f"Error reading PDF: {str(e)}"
            
    return text.strip()
