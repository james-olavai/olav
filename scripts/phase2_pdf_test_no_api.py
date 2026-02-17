#!/usr/bin/env python3
"""Phase 2: Test PDF Reading and Text Splitting (No API Key Needed)

- Read the uploaded CCNP PDF
- Split into chunks
- Display statistics
- (Full embedding will run after providing OPENAI_API_KEY)
"""

import logging
import sys
from pathlib import Path

from config.paths import AGENT_DIR
from src.olav.lib.kb_manager import KnowledgeBaseManager

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s: %(message)s"
)
logger = logging.getLogger(__name__)


def test_pdf_reading():
    """Phase 2 Test - PDF Reading & Chunking (No API Key Required)"""
    
    logger.info("=" * 70)
    logger.info("PHASE 2: PDF Reading & Text Splitting Test")
    logger.info("=" * 70)
    
    knowledge_dir = AGENT_DIR / "knowledge"
    
    # Step 1: Check files
    logger.info("\n[Step 1/3] Checking files to process...")
    supported = {'.pdf', '.md', '.markdown'}
    files = [
        f for f in knowledge_dir.glob('*')
        if f.is_file() and f.suffix.lower() in supported
    ]
    
    if not files:
        logger.error(f"❌ No PDF/Markdown files found in {knowledge_dir}")
        return False
    
    logger.info(f"✅ Found {len(files)} files:")
    for f in files:
        logger.info(f"   • {f.name} ({f.stat().st_size / 1024 / 1024:.1f} MB)")
    
    # Step 2: Read PDF and split
    logger.info("\n[Step 2/3] Reading and splitting PDF...")
    test_file = files[0]
    
    try:
        # Note: We bypass OpenAI requirement by testing PDF reading directly
        import PyPDF2
        
        with open(test_file, 'rb') as f:
            reader = PyPDF2.PdfReader(f)
            page_count = len(reader.pages)
            
            # Extract first 2 pages as sample
            sample_text = ""
            for i, page in enumerate(reader.pages[:2]):
                text = page.extract_text()
                sample_text += text
        
        logger.info(f"✅ PDF Reading Successful:")
        logger.info(f"   Total pages: {page_count}")
        logger.info(f"   Sample text (first 200 chars): {sample_text[:200]}")
        
        # Now test text splitting
        from langchain_text_splitters import RecursiveCharacterTextSplitter
        
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=200,
            separators=["\n\n", "\n", " ", ""]
        )
        
        # Split sample text
        chunks = splitter.split_text(sample_text)
        logger.info(f"\n✅ Text Splitting Successful:")
        logger.info(f"   Number of chunks (from 2 pages): {len(chunks)}")
        logger.info(f"   Avg chunk size: {len(sample_text) / len(chunks) if chunks else 0:.0f} chars")
        
        if chunks:
            logger.info(f"   First chunk preview: {chunks[0][:100]}...")
    
    except Exception as e:
        logger.error(f"❌ PDF processing failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    # Step 3: Summary and next steps
    logger.info("\n[Step 3/3] Configuration Check...")
    
    import os
    has_api_key = "OPENAI_API_KEY" in os.environ
    api_key_status = "✅ Set" if has_api_key else "❌ Not Set"
    
    logger.info(f"   OPENAI_API_KEY: {api_key_status}")
    
    logger.info("\n" + "=" * 70)
    logger.info("✅ Phase 2: PDF & Text Processing Complete!")
    logger.info("=" * 70)
    
    if not has_api_key:
        logger.info("\n⚠️  Next: Set up OPENAI_API_KEY for full embedding pipeline:")
        logger.info("   export OPENAI_API_KEY='sk-...'")
        logger.info("   uv run python scripts/phase2_full_embedding_test.py")
    else:
        logger.info("\n✅ API key is configured. Ready for full embedding:")
        logger.info("   uv run python scripts/phase2_full_embedding_test.py")
    
    logger.info("\n🎯 Phase 2 Deliverables:")
    logger.info("   ✅ PDF reading working")
    logger.info("   ✅ Text splitting working")
    logger.info("   ⏳ Embeddings (pending OPENAI_API_KEY)")
    
    return True


if __name__ == "__main__":
    success = test_pdf_reading()
    sys.exit(0 if success else 1)
