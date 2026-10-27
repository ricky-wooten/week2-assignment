# Cleaning notes: Goodbooks-10k books.csv

The original `books.csv` is left exactly as downloaded. `clean_books.py` reads it and writes three tables to `clean/`.

## Output tables

| File | Rows | One row per… |
|---|---|---|
| `clean/books.csv` | 10,000 | book (title) |
| `clean/authors.csv` | 5,833 | person |
| `clean/book_authors.csv` | 13,209 | person listed on a book |

`book_authors.author_order` keeps the original order; `1` is the first person listed, usually the main author.

## What was fixed

| Problem in the original | Fix |
|---|---|
| Several people in one `authors` cell ("J.K. Rowling, Mary GrandPré") | Split into `authors` + `book_authors` |
| Extra spaces made one person look like two ("William  Gibson") | Collapsed spaces; 8 duplicate people merged |
| Same name twice on one book ("Louis Sachar, Louis Sachar") | Repeat dropped (7 books) |
| ISBNs lost leading zeros ("61120081") | Padded back to 10 characters (6,601 ISBNs) |
| `isbn13` in scientific notation, last digits lost (9.78043902348e+12) | Rebuilt from the ISBN-10 (9,277 books) |
| Years stored as decimals ("2008.0") | Whole numbers; negative years are BC and kept (e.g. *The Odyssey*, -720) |
| Two language code systems ("eng" vs "en-US", "en-GB", "en-CA", "en") | All English → `eng`; `nl` → `dut` (2,390 books) |
| Series inside the title ("Twilight (Twilight, #1)") | Split into `title`, `series_name`, `series_number` (4,439 books); original kept in `full_title` |
| Extra spaces in titles | Collapsed |
| "No photo" placeholder cover links | Blank |

## Columns dropped

`best_book_id`, `books_count`, `work_ratings_count`, `work_text_reviews_count`, `ratings_1`–`ratings_5`, `small_image_url`. These describe Goodreads activity, not our library. `average_rating` and `ratings_count` are kept as facts about the book.

## Left blank on purpose (not guessed)

- 700 books have no ISBN.
- 23 ISBNs fail the ISBN check-digit test. They're kept as given, but no ISBN-13 was built for them.
- 21 books have no publication year.
- 1,084 books have no language code.
- 590 books have no original title.

## Not fixed (decisions for later)

- **Roles:** translators, illustrators and editors are still listed as authors (e.g. Robert Fagles on *The Odyssey*). The data doesn't say who did what.
- **Pen names:** Nora Roberts and J.D. Robb are separate authors.
- **Placeholder authors:** "Anonymous", "Unknown", "Various" and "Better Homes and Gardens" are kept as authors.
- **Series numbers** are text, not numbers, because some are ranges or parts ("1-4 + 3.5", "3: Part 2 of 2").

## Re-run

```
python3 clean_books.py
```
