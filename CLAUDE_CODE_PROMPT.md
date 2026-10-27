Build a SQLite database for my library. I'm the owner of a small library that hasn't opened yet. I've decided what the library needs to track, and I want the database to hold me to those rules.

Work in this folder. Read CLEANING_NOTES.md first. It explains what the data in clean/ does and doesn't contain. Don't use the original books.csv; use only the files in clean/.

## Deliverables

1. `build_db.py`: a script that creates `library.db` from scratch every time it runs (delete the old file first). Use Python's built-in sqlite3 only, with `PRAGMA foreign_keys = ON`.
2. `library.db`: the database.
3. `queries.sql`: one query for each "typical day" question below, each with a comment saying which question it answers.
4. `test_rules.py`: tries to break each rule below and confirms the database refuses. Print PASS or FAIL for each rule.
5. `SCHEMA.md`: a plain-English description of every table and column, and which rule each constraint enforces. Write it for someone who doesn't know SQL.

Use a fixed "today" of 2026-10-26 for all sample data, so overdue results don't change from day to day.

## Tables and rules

### 1. Books (the titles we carry)
Load all 10,000 rows from clean/books.csv, keeping its columns and its `book_id` as the primary key.
- Every book must have a title.
- `book_id` is unique. ISBN-10 and ISBN-13 are optional (some books have none) but must be unique when present.
- The year can't be in the future. Negative years are BC and are allowed (The Odyssey is -720). The year can be blank.
- Add these columns, which the data doesn't have:
  - `format`: hardcover, paperback, audiobook or DVD. Fill with made-up values.
  - `audience`: adult, teen or children. Fill with made-up values.
  - `shelf_code`: e.g. "FIC COL" (FIC plus the first three letters of the first author's last word).
  - `publisher`: leave blank.
  - `genre`: leave blank for now.

### 2. Authors and who wrote what
- Load clean/authors.csv into `authors` and clean/book_authors.csv into `book_authors`.
- Store each author as one full name. Don't split names into first and last, because of names like "Homer", "Kurt Vonnegut Jr." and "Andre Dubus III".
- Author names are unique.
- One author can have many books, and one book can have many authors.
- Keep `author_order` (1 = first person listed). A book can't list the same person twice, and two people can't share the same position on one book.
- Every book must have at least one author. Check this after loading and stop with an error if any book has none.

### 3. Copies (the actual items on the shelf)
Our library only stocks some of the catalog. Create copies for the 300 books with the highest `ratings_count`: 3 copies for the top 25, 2 for the next 75, and 1 for the rest.
- Each copy has: which book it belongs to, a unique barcode (e.g. "LIB-000001"), a status, the date we bought it, what it cost, and whether it can leave the building.
- Status must be one of: available, checked_out, on_hold_shelf, lost, damaged, retired.
- Every copy must belong to a book we have.
- Cost can't be negative. Make up costs between $8 and $35.
- Mark about 10 copies as reference-only (can't leave the building).

### 4. Patrons (people who borrow)
Create about 30 made-up patrons. Use obviously fictional names and example.com email addresses.
- Each patron has: name, unique card number, email, phone, address, type (adult, child, senior or staff), date joined, card expiration date, and standing (active, expired or blocked).
- Every patron must have a name and at least one way to contact them (email or phone).
- A child's account must be linked to a guardian, who is another patron.
- Include a few children with guardians, one expired card and one blocked patron.

### 5. Loans (every time something is checked out)
Create about 150 made-up loans spread over the past year: mostly returned, about 20 currently out, and about 6 overdue.
- Each loan has: which copy, which patron, the checkout date, the due date, the return date (blank until it comes back) and the renewal count.
- The due date must be after the checkout date. The return date can't be before the checkout date.
- A copy can't be checked out to two people at once. Use a unique index on copy_id for loans that haven't been returned.
- A blocked or expired patron can't borrow. Enforce this with a trigger.
- A patron can't go over the checkout limit (see policies). Enforce this with a trigger.
- A reference-only copy can't be loaned.
- Old loans are never deleted.
- Make copy statuses match the loans: if a copy is out, its status is checked_out.

### 6. Holds (reservations)
Create about 10 made-up holds, including a queue of 3 patrons on one popular book.
- A hold is for a book (not a specific copy), and records which patron, when it was placed, its status (waiting, ready, picked_up, cancelled or expired) and the pickup deadline.
- A patron can't have two active holds on the same book.
- A patron can't hold a book they currently have checked out. Enforce this with a trigger.

### 7. Fines
Create made-up fines that match the overdue and lost loans. Include at least one unpaid and one paid fine, and get the blocked patron over the blocking limit.
- Each fine records which patron, which loan, the amount, the reason (late, lost or damaged), the date charged and the date paid (blank if unpaid).
- The amount can't be negative.
- A patron whose unpaid fines are over the blocking limit can't borrow. Enforce this in the same trigger as the patron-standing rule.

### 8. Library policies
Store these in a `policies` table (one row per setting), not hard-coded in triggers, so I can change them later:
- Loan length: 21 days for books, 7 for DVDs, 14 for audiobooks
- Checkout limit: 10 items for adults, seniors and staff; 5 for children
- Maximum renewals: 2
- Late fine: $0.25 per day, capped at the copy's cost
- Blocking limit: $10.00 in unpaid fines
- Lost after: 45 days overdue
- Hold pickup window: 7 days

## Typical day: queries.sql must answer each of these
1. Someone signs up for a card (an INSERT example).
2. Someone checks out three books (an INSERT example that respects every rule).
3. Someone returns a book, and someone else was waiting for it: who's next in the queue?
4. "Do you have anything by Stephen King, and is it in?" (titles, plus number of copies available)
5. At closing: everything overdue, with patron name, contact, title and days late.
6. A new shipment arrives (add copies of a book).
7. A book comes back with a torn cover (mark the copy damaged).
8. Someone asks how much they owe.
9. Our 10 most-borrowed books.

## When you're done
Run build_db.py, then test_rules.py, then every query in queries.sql. Show me the results, and tell me about anything you had to decide that this prompt didn't cover.
