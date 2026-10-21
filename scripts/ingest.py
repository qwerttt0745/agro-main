from app import config
import argparse
import hashlib
from pathlib import Path

MODEL = "intfloat/multilingual-e5-small"
CHUNK_SIZE = 700   # e5 бачить до 512 токенів, тож шматки можна довші
OVERLAP = 150


def split(text, size=CHUNK_SIZE, overlap=OVERLAP):
    if not 0 <= overlap < size // 2:
        raise ValueError("overlap must be less than half of size")
    chunks, start = [], 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            sp = text.rfind(" ", start, end)
            if sp > start + size // 2:
                end = sp
        chunks.append(text[start:end].strip())
        if end == len(text):
            break
        start = end - overlap
        sp = text.find(" ", start, end)
        if sp != -1:
            start = sp + 1
    return chunks


def ingest(pdf_path, col, model):
    from pypdf import PdfReader
    path = Path(pdf_path).resolve()
    source = str(path)
    version = hashlib.sha256(path.read_bytes()).hexdigest()
    source_id = hashlib.sha256(source.encode()).hexdigest()[:24]
    reader = PdfReader(path)
    chunks, ids, metas = [], [], []
    for page_num, page in enumerate(reader.pages, start=1):
        text = " ".join((page.extract_text() or "").split())
        for j, chunk in enumerate(split(text)):
            if len(chunk) > 60:
                chunks.append(chunk)
                ids.append(f"{source_id}-{version}-p{page_num}-{j}")
                metas.append({"source": source, "page": page_num, "sha256": version})
    if not chunks:
        raise ValueError(f"У {path.name} немає тексту для індексації. Можливо, потрібен OCR; старий індекс збережено.")
    # Finish extraction and embedding before changing the index.
    embeddings = model.encode(
        ["passage: " + chunk for chunk in chunks], batch_size=32,
        normalize_embeddings=True, show_progress_bar=True,
    )
    # Older versions stored relative paths. Match them before retiring old IDs.
    records = col.get(include=["metadatas"])
    previous = []
    for record_id, meta in zip(records["ids"], records["metadatas"]):
        old_source = (meta or {}).get("source")
        if not old_source:
            continue
        old_path = Path(old_source)
        if not old_path.is_absolute():
            old_path = config.ROOT / old_path
        if old_path.resolve() == path:
            previous.append(record_id)
    for i in range(0, len(chunks), 500):
        col.upsert(documents=chunks[i:i + 500],
                   embeddings=embeddings[i:i + 500].tolist(),
                   ids=ids[i:i + 500], metadatas=metas[i:i + 500])
    # Only retire obsolete chunks of this document after every batch succeeds.
    stale = sorted(set(previous) - set(ids))
    for i in range(0, len(stale), 500):
        col.delete(ids=stale[i:i + 500])
    return len(chunks)


def main():
    parser = argparse.ArgumentParser(description="Додати або оновити PDF без видалення інших книг")
    parser.add_argument("paths", nargs="+", type=Path, help="PDF-файли або папки з PDF")
    args = parser.parse_args()
    paths = sorted({p.resolve() for item in args.paths
                    for p in (item.rglob("*.pdf") if item.is_dir() else [item])})
    if not paths or any(not p.is_file() or p.suffix.lower() != ".pdf" for p in paths):
        parser.error("Потрібен принаймні один наявний PDF-файл")
    import chromadb
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(MODEL)
    client = chromadb.PersistentClient(path=str(config.CHROMA_DIR))
    col = client.get_or_create_collection("agro", embedding_function=None)
    for path in paths:
        print(f"{path.name}: додано/оновлено {ingest(path, col, model)} фрагментів")


if __name__ == "__main__":
    main()
