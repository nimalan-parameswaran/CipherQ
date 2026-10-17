"""
CipherQ Document Extraction and Chunking Service
Extracts text from decrypted plaintext in memory (PDFs, Markdown, Plaintext, JSON, CSV).
Partitions extracted text into overlapping passages with page metadata for grounded citations.
Zero content logging or disk persistence during extraction.
"""
import io
from dataclasses import dataclass
from typing import List, Tuple
from pathlib import Path
from pypdf import PdfReader
from pypdf.errors import PdfReadError


class ExtractionError(Exception):
    """Raised when document parsing or text extraction fails."""
    pass


class UnsupportedDocumentError(ExtractionError):
    """Raised when the document type is unsupported or binary executable."""
    pass


@dataclass
class ExtractedChunk:
    chunk_index: int
    page_number: int
    content: str
    char_count: int


# Whitelist of text-decodable extensions
TEXT_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".json", ".csv",
    ".log", ".xml", ".yaml", ".yml", ".ini", ".conf", ".py", ".sh"
}


class DocumentExtractor:
    """Extracts text from decrypted in-memory byte buffers."""

    def __init__(self, target_chunk_size: int = 500, overlap_size: int = 50):
        self.target_chunk_size = target_chunk_size
        self.overlap_size = overlap_size

    def extract_text_pages(self, raw_bytes: bytes, filename: str) -> List[Tuple[int, str]]:
        """
        Extracts text from raw bytes, returning a list of (page_number, text_content).
        For plaintext formats, returns [(1, full_text)].
        For PDFs, returns [(page_num, page_text), ...].
        """
        if not raw_bytes:
            raise ExtractionError("Document is empty (0 bytes).")

        ext = Path(filename).suffix.lower()

        # 1. PDF Extraction
        if ext == ".pdf":
            try:
                reader = PdfReader(io.BytesIO(raw_bytes))
                if reader.is_encrypted:
                    raise ExtractionError("Encrypted or password-protected PDFs are not supported for local AI search.")

                pages = []
                for idx, page in enumerate(reader.pages, start=1):
                    page_text = page.extract_text() or ""
                    cleaned = page_text.strip()
                    if cleaned:
                        pages.append((idx, cleaned))

                if not pages:
                    raise ExtractionError("No readable text could be extracted from PDF (may be scanned image or empty).")
                return pages

            except PdfReadError as e:
                raise ExtractionError(f"Malformed or corrupt PDF document: {e}") from e
            except Exception as e:
                if isinstance(e, ExtractionError):
                    raise
                raise ExtractionError(f"PDF extraction error: {e}") from e

        # 2. Plaintext / Markdown / JSON / CSV Extraction
        elif ext in TEXT_EXTENSIONS or ext == "":
            try:
                text = raw_bytes.decode("utf-8")
            except UnicodeDecodeError:
                try:
                    text = raw_bytes.decode("latin-1")
                except Exception as e:
                    raise UnsupportedDocumentError("File encoding not recognized as readable text.") from e

            # Filter binary files that happen to pass latin-1 decode
            if "\x00" in text[:1024]:
                raise UnsupportedDocumentError("Binary file detected; cannot extract text for indexing.")

            cleaned = text.strip()
            if not cleaned:
                raise ExtractionError("Document contains no textual content.")
            return [(1, cleaned)]

        else:
            raise UnsupportedDocumentError(
                f"File format '{ext}' is not supported for local AI indexing. "
                f"Supported formats: PDF, TXT, MD, CSV, JSON."
            )

    def chunk_pages(self, pages: List[Tuple[int, str]]) -> List[ExtractedChunk]:
        """
        Splits pages into overlapping chunks with preserved page metadata.
        """
        chunks = []
        global_index = 0

        for page_num, text in pages:
            # Normalize whitespace
            lines = [l.strip() for l in text.splitlines() if l.strip()]
            normalized_text = " ".join(lines)

            if len(normalized_text) <= self.target_chunk_size:
                chunks.append(ExtractedChunk(
                    chunk_index=global_index,
                    page_number=page_num,
                    content=normalized_text,
                    char_count=len(normalized_text)
                ))
                global_index += 1
                continue

            # Sliding window with overlap
            start = 0
            text_len = len(normalized_text)

            while start < text_len:
                end = min(start + self.target_chunk_size, text_len)
                
                # Try not to break in the middle of a word if possible
                if end < text_len:
                    last_space = normalized_text.rfind(" ", start, end)
                    if last_space > start + (self.target_chunk_size // 2):
                        end = last_space

                chunk_str = normalized_text[start:end].strip()
                if chunk_str:
                    chunks.append(ExtractedChunk(
                        chunk_index=global_index,
                        page_number=page_num,
                        content=chunk_str,
                        char_count=len(chunk_str)
                    ))
                    global_index += 1

                if end >= text_len:
                    break

                start = end - self.overlap_size

        return chunks

    def process_document(self, raw_bytes: bytes, filename: str) -> List[ExtractedChunk]:
        """Convenience method to extract and chunk in a single call."""
        pages = self.extract_text_pages(raw_bytes, filename)
        return self.chunk_pages(pages)


extractor_service = DocumentExtractor()
