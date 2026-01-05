"""CV PDF parsing service."""
import logging
from typing import Optional
from PyPDF2 import PdfReader
from io import BytesIO

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def parse_pdf(file_content: bytes) -> str:
    """
    Parse PDF file and extract text content.
    
    Args:
        file_content: PDF file content as bytes
        
    Returns:
        Extracted text from the PDF
        
    Raises:
        ValueError: If PDF cannot be parsed or is invalid
    """
    try:
        logger.info(f"📄 Parsing PDF: {len(file_content)} bytes")
        
        # Create PDF reader from bytes
        pdf_file = BytesIO(file_content)
        reader = PdfReader(pdf_file)
        
        # Extract text from all pages
        text_parts = []
        for page_num, page in enumerate(reader.pages, start=1):
            try:
                page_text = page.extract_text()
                if page_text.strip():
                    text_parts.append(page_text)
                    logger.debug(f"Extracted {len(page_text)} characters from page {page_num}")
            except Exception as e:
                logger.warning(f"Error extracting text from page {page_num}: {e}")
                continue
        
        if not text_parts:
            raise ValueError("No text content found in PDF")
        
        # Combine all pages
        full_text = "\n\n".join(text_parts)
        logger.info(f"✅ Successfully parsed PDF: {len(full_text)} characters extracted")
        
        # Log preview of parsed content (first 500 characters)
        preview = full_text[:500].replace('\n', ' ')
        logger.info(f"📄 Parsed CV preview: {preview}...")
        
        return full_text
        
    except Exception as e:
        logger.error(f"❌ Error parsing PDF: {e}")
        raise ValueError(f"Failed to parse PDF: {str(e)}")


def validate_pdf(file_content: bytes, max_size_mb: int = 10) -> bool:
    """
    Validate PDF file before parsing.
    
    Args:
        file_content: PDF file content as bytes
        max_size_mb: Maximum file size in MB
        
    Returns:
        True if valid, False otherwise
    """
    # Check file size
    max_size_bytes = max_size_mb * 1024 * 1024
    if len(file_content) > max_size_bytes:
        logger.warning(f"PDF file too large: {len(file_content)} bytes (max: {max_size_bytes})")
        return False
    
    # Check if file starts with PDF magic bytes
    if not file_content.startswith(b'%PDF'):
        logger.warning("File does not appear to be a valid PDF")
        return False
    
    return True
