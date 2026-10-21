from app import config
import os
import re
import json
import time
import hashlib
from urllib.parse import urljoin, parse_qs, urlparse
import requests
from bs4 import BeautifulSoup
from slugify import slugify

# === НАЛАШТУВАННЯ ===
BASE_URL = "http://ir.polissiauniver.edu.ua"
SEARCH_QUERY_URL = (
    "http://ir.polissiauniver.edu.ua/simple-search"
    "?query=%D1%80%D0%BE%D1%81%D0%BB%D0%B8%D0%BD%D0%BD%D0%B8%D1%86%D1%82%D0%B2%D0%BE+"
    "%D0%B0%D0%B3%D1%80%D0%BE%D0%BD%D0%BE%D0%BC%D1%96%D1%8F+%D2%91%D1%80%D1%83%D0%BD%D1%82%D0%B8+"
    "%D1%81%D0%BE%D1%8F%2C+%D0%BA%D1%83%D0%BA%D1%83%D1%80%D1%83%D0%B4%D0%B7%D0%B0%2C+"
    "%D0%B7%D0%B0%D1%85%D0%B8%D1%81%D1%82+%D1%80%D0%BE%D1%81%D0%BB%D0%B8%D0%BD%2C+%D0%B4%D0%BE%D0%B1%D1%80%D0%B8%D0%B2%D0%B0"
)

MIN_YEAR = 2018  # Фільтр: завантажувати лише актуальні матеріали (2018-2026)
OUTPUT_DIR = config.PDF_DIR
CATALOG_FILE = config.DATA / "catalog.jsonl"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

os.makedirs(OUTPUT_DIR, exist_ok=True)

def get_existing_hashes():
    """Зчитує збережені sha256 з catalog.jsonl для уникнення дублікатів."""
    hashes = set()
    if os.path.exists(CATALOG_FILE):
        with open(CATALOG_FILE, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    try:
                        data = json.loads(line)
                        if "sha256" in data:
                            hashes.add(data["sha256"])
                    except json.JSONDecodeError:
                        continue
    return hashes

def extract_tags(title):
    """Автоматично витягує теги на основі клчових слів у назві."""
    keywords = ["соя", "кукурудза", "ячмінь", "пшениця", "картопля", "квасоля", "рижій", "добрива", "пестициди", "ґрунт", "захист"]
    title_lower = title.lower()
    tags = [kw for kw in keywords if kw in title_lower]
    return tags if tags else ["агрономія"]

def parse_item_page(item_url):
    """Парсить картку матеріалу: отримує метадані та посилання на PDF."""
    try:
        resp = requests.get(item_url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            return None
        
        soup = BeautifulSoup(resp.text, "html.parser")
        
        # Назва
        title_elem = soup.find("h2") or soup.find("td", class_="dcItemTitle")
        title = title_elem.text.strip() if title_elem else "Untitled"
        
        # Якщо це сторінка колекції чи розділу — пропускаємо
        if "коллекции этого раздела" in title.lower() or "колекції цього розділу" in title.lower() or "перегляд" in title.lower():
            return None
        
        # Автори
        authors = []
        author_elems = soup.find_all("td", class_="author") or soup.select('meta[name="DC.creator"]')
        for a in author_elems:
            name = a.get("content") if a.has_attr("content") else a.text.strip()
            if name:
                authors.append(name)
        
        # Рік випуску
        year = None
        date_elem = soup.select_one('meta[name="DCTERMS.issued"]') or soup.select_one('meta[name="DC.date"]')
        if date_elem and date_elem.get("content"):
            match = re.search(r'\b(19|20)\d{2}\b', date_elem["content"])
            if match:
                year = int(match.group(0))
        
        if not year:
            text = soup.get_text()
            matches = re.findall(r'\b(20[0-2][0-9])\b', text)
            if matches:
                year = int(matches[0])
            else:
                year = 2020  
                
        # Шукаємо посилання на PDF
        pdf_url = None
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if href.endswith(".pdf") or "bitstream" in href:
                pdf_url = urljoin(BASE_URL, href)
                break
                
        return {
            "title": title,
            "authors": authors,
            "year": year,
            "pdf_url": pdf_url,
            "source_url": item_url
        }
    except Exception as e:
        print(f"[!] Помилка обробки картки {item_url}: {e}")
        return None

def process_and_download(item_data, processed_hashes):
    """Завантажує PDF, вираховує sha256, формує ASCII-slug та дописує метадані."""
    pdf_url = item_data.get("pdf_url")
    if not pdf_url:
        print(f"[-] Не знайдено PDF для: {item_data['title']}")
        return

    # Фільтрація за актуальністю (роком)
    if item_data["year"] < MIN_YEAR:
        print(f"[SKIP] Застарілий матеріал ({item_data['year']} р.): {item_data['title']}")
        return

    try:
        pdf_resp = requests.get(pdf_url, headers=HEADERS, timeout=30)
        if pdf_resp.status_code != 200:
            print(f"[!] Помилка завантаження PDF: {pdf_url}")
            return
            
        content = pdf_resp.content
        sha256_hash = hashlib.sha256(content).hexdigest()
        
        if sha256_hash in processed_hashes:
            print(f"[SKIP] Дублікат (хеш вже існує): {item_data['title']}")
            return

        short_id = sha256_hash[:8]
        title_slug = slugify(item_data["title"], max_length=40) or "document"
        filename = f"{item_data['year']}_{title_slug}_{short_id}.pdf"
        file_path = os.path.join(OUTPUT_DIR, filename)

        # Зберігаємо файл
        with open(file_path, "wb") as f:
            f.write(content)

        tags = extract_tags(item_data["title"])

        # Формуємо запис для catalog.jsonl
        record = {
            "id": short_id,
            "title": item_data["title"],
            "authors": item_data["authors"],
            "year": item_data["year"],
            "source_url": item_data["source_url"],
            "file": filename,
            "sha256": sha256_hash,
            "lang": "uk",
            "tags": tags
        }

        # Дописуємо в JSONL
        with open(CATALOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

        processed_hashes.add(sha256_hash)
        print(f"[+] Успішно збережено: {filename}")

    except Exception as e:
        print(f"[!] Помилка під час збереження файлу {pdf_url}: {e}")

def run_parser():
    processed_hashes = get_existing_hashes()
    current_url = SEARCH_QUERY_URL
    page = 1

    print(f"=== Запуск парсера (мінімальний рік: {MIN_YEAR}) ===")

    while current_url:
        print(f"\n--- Парсинг сторінки результатів #{page} ---")
        try:
            resp = requests.get(current_url, headers=HEADERS, timeout=15)
            if resp.status_code != 200:
                print(f"[!] Не вдалося завантажити сторінку пошуку: {current_url}")
                break

            soup = BeautifulSoup(resp.text, "html.parser")
            
            # Шукаємо посилання на картки праць у таблиці результатів
            item_links = []
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if "/handle/123456789/" in href and not href.endswith("/browse"):
                    full_link = urljoin(BASE_URL, href)
                    if full_link not in item_links:
                        item_links.append(full_link)

            print(f"Знайдено посилань на матеріали: {len(item_links)}")

            for link in item_links:
                item_data = parse_item_page(link)
                if item_data:
                    process_and_download(item_data, processed_hashes)
                time.sleep(1)  # Пауза 1 сек між запитами

            # Пошук кнопки пагінації "Наступна сторінка"
            next_link = None
            for a in soup.find_all("a", href=True):
                if "next" in a.get_text().lower() or "наступна" in a.get_text().lower():
                    next_link = urljoin(BASE_URL, a["href"])
                    break
            
            # Спроба згенерувати посилання на наступну сторінку за відсутності прямої кнопки
            if not next_link:
                parsed_query = parse_qs(urlparse(current_url).query)
                start = int(parsed_query.get("start", [0])[0])
                if len(item_links) >= 10:  # Якщо сторінка була повною
                    next_start = start + 10
                    if "start=" in current_url:
                        next_link = re.sub(r'start=\d+', f'start={next_start}', current_url)
                    else:
                        next_link = f"{current_url}&start={next_start}"

            if next_link and next_link != current_url:
                current_url = next_link
                page += 1
                time.sleep(2)
            else:
                current_url = None

        except Exception as e:
            print(f"[!] Критична помилка під час парсингу сторінки: {e}")
            break

    print("\n=== Парсинг завершено! ===")

if __name__ == "__main__":
    run_parser()
