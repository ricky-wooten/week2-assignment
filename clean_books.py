"""
Clean Goodbooks-10k books.csv into tables a library database can use.

Reads:  books.csv (the original download, left unchanged)
Writes: clean/books.csv, clean/authors.csv, clean/book_authors.csv

Run:  python3 clean_books.py
"""
import csv
import os
import re

SRC = "books.csv"
OUT = "clean"

# Language codes in the raw data mix two systems ("eng" and "en-US").
# Everything is mapped to the three-letter codes most of the file already uses.
LANGUAGE_FIXES = {"en-US": "eng", "en-GB": "eng", "en-CA": "eng", "en": "eng", "nl": "dut"}

# Series info sits at the end of the title, e.g. "Twilight (Twilight, #1)".
SERIES_PATTERN = re.compile(r"^(?P<title>.*?)\s*\((?P<series>[^()]*(?:\([^()]*\))?[^()]*?),?\s*#(?P<number>[^()]+)\)\s*$")


def tidy(text):
    """Trim the ends and collapse runs of spaces into one space."""
    return re.sub(r"\s+", " ", text).strip()


def clean_isbn10(raw):
    """Restore leading zeros that were dropped when the ISBN was stored as a number."""
    raw = raw.strip()
    return raw.zfill(10) if raw else None


def isbn10_is_valid(isbn):
    total = sum((10 - i) * (10 if ch == "X" else int(ch)) for i, ch in enumerate(isbn))
    return total % 11 == 0


def isbn10_to_isbn13(isbn):
    """Rebuild the ISBN-13 from the ISBN-10. The raw isbn13 column is in scientific
    notation (9.78043902348e+12) and has lost its last digits, so it can't be used."""
    core = "978" + isbn[:9]
    total = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(core))
    return core + str((10 - total % 10) % 10)


def split_series(title):
    m = SERIES_PATTERN.match(title)
    if not m:
        return title, None, None
    return tidy(m["title"]), tidy(m["series"]).rstrip(",").strip(), tidy(m["number"])


def main():
    os.makedirs(OUT, exist_ok=True)
    with open(SRC, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))

    books, book_authors = [], []
    author_ids = {}  # cleaned name -> author_id
    report = {"isbn_padded": 0, "isbn_failed_check": 0, "isbn13_rebuilt": 0,
              "series_split": 0, "language_fixed": 0, "names_respaced": 0,
              "repeat_names_dropped": 0}

    for r in rows:
        book_id = int(r["book_id"])

        # --- ISBNs ---------------------------------------------------------
        isbn10 = clean_isbn10(r["isbn"])
        isbn13 = None
        if isbn10:
            if isbn10 != r["isbn"]:
                report["isbn_padded"] += 1
            if isbn10_is_valid(isbn10):
                isbn13 = isbn10_to_isbn13(isbn10)
                report["isbn13_rebuilt"] += 1
            else:
                report["isbn_failed_check"] += 1

        # --- Title and series --------------------------------------------
        full_title = tidy(r["title"])
        title, series, series_no = split_series(full_title)
        if series:
            report["series_split"] += 1

        # --- Year: "2008.0" -> 2008; negative years are BC and are kept ----
        year = int(float(r["original_publication_year"])) if r["original_publication_year"] else None

        # --- Language -----------------------------------------------------
        lang = r["language_code"].strip() or None
        if lang in LANGUAGE_FIXES:
            lang = LANGUAGE_FIXES[lang]
            report["language_fixed"] += 1

        books.append({
            "book_id": book_id,
            "title": title,
            "full_title": full_title,
            "original_title": tidy(r["original_title"]) or None,
            "series_name": series,
            "series_number": series_no,
            "isbn10": isbn10,
            "isbn13": isbn13,
            "publication_year": year,
            "language_code": lang,
            "average_rating": float(r["average_rating"]),
            "ratings_count": int(r["ratings_count"]),
            "goodreads_book_id": int(r["goodreads_book_id"]),
            "goodreads_work_id": int(r["work_id"]),
            "image_url": None if "nophoto" in r["image_url"] else r["image_url"],
        })

        # --- Authors: one cell with a list -> one row per person ----------
        seen = set()
        for raw_name in r["authors"].split(","):
            name = tidy(raw_name)
            if name != raw_name.strip():
                report["names_respaced"] += 1
            if not name:
                continue
            if name in seen:  # e.g. "Louis Sachar, Louis Sachar"
                report["repeat_names_dropped"] += 1
                continue
            seen.add(name)
            if name not in author_ids:
                author_ids[name] = len(author_ids) + 1
            book_authors.append({
                "book_id": book_id,
                "author_id": author_ids[name],
                "author_order": len(seen),  # 1 = first person listed, usually the main author
            })

    authors = [{"author_id": i, "name": n} for n, i in author_ids.items()]

    def write(name, data):
        with open(os.path.join(OUT, name), "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(data[0].keys()))
            w.writeheader()
            w.writerows(data)

    write("books.csv", books)
    write("authors.csv", authors)
    write("book_authors.csv", book_authors)

    print(f"books: {len(books)}  authors: {len(authors)}  book_authors: {len(book_authors)}")
    for k, v in report.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
