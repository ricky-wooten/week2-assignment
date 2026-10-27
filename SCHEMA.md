# Library database: what's in it and what it enforces

`library.db` is a SQLite database: one file that holds several **tables**, which are like spreadsheet tabs. Each table has **columns** (the kinds of information) and **rows** (one item each).

The database doesn't just store data. It also holds the library to its rules. If anyone tries to save something that breaks a rule, the database refuses and says which rule was broken. It enforces rules in five ways:

| Kind of rule | What it means in plain English |
|---|---|
| **Required** | This column can't be left empty. |
| **Unique** | No two rows can have the same value here. |
| **Allowed values / check** | The value must pass a test, like "one of these words" or "not negative." Checks have names (like `cost_not_negative`) so error messages say exactly which rule was broken. |
| **Must point to something real** | The value is an ID from another table, and that row must exist. You can't lend a copy that doesn't exist. (Programmers call this a *foreign key*.) |
| **Automatic check (trigger)** | A small rule the database runs by itself every time something is added or changed, for rules that need to look at other tables, like "is this patron blocked?" |

Section numbers below (§1–§8) match `CLAUDE_CODE_PROMPT.md`.

Dates are stored as text in `YYYY-MM-DD` form (for example `2026-10-26`). Each date column checks that it holds a real date in that form.

---

## `books`: the titles in our catalog (§1)

10,000 rows, loaded from `clean/books.csv`. A *book* here is a title, not a physical item; the physical items are in `copies`.

| Column | What it holds | Rules |
|---|---|---|
| `book_id` | The book's ID number, from the data | Unique; identifies the book everywhere else |
| `title` | Title without the series part | **Required**, and can't be just spaces (`title_not_blank`) |
| `full_title` | Title as originally given, e.g. "Twilight (Twilight, #1)" | |
| `original_title` | Title in its original language | |
| `series_name`, `series_number` | Series, if any. The number is text because some are like "1-4 + 3.5" | |
| `isbn10`, `isbn13` | Standard book numbers | Optional, but **unique** when present (many books may have none) |
| `publication_year` | Year first published. Negative = BC (The Odyssey is -720) | Optional. **Can't be in the future** (automatic check against the real calendar, when added or changed) |
| `language_code` | e.g. `eng` | |
| `average_rating`, `ratings_count` | Goodreads rating and number of ratings | Kept as facts; `ratings_count` decided which books we stock |
| `goodreads_book_id`, `goodreads_work_id`, `image_url` | Links back to the source data | |
| `format` | hardcover, paperback, audiobook or DVD (made up) | **Required**, one of those four (`valid_format`). Decides the loan length |
| `audience` | adult, teen or children (made up) | **Required**, one of those three (`valid_audience`) |
| `shelf_code` | Where it sits, e.g. "FIC COL": FIC plus the first three letters of the first author's surname | Built from the author; see "Decisions" |
| `publisher`, `genre` | Not filled in yet | |

## `authors`: people (§2)

5,833 rows from `clean/authors.csv`.

| Column | What it holds | Rules |
|---|---|---|
| `author_id` | ID number | Unique |
| `name` | Full name as one piece ("Homer", "Kurt Vonnegut Jr.") | **Required** and **unique**, ignoring upper/lower case ("Stephen King" and "stephen king" count as the same) |

Names are never split into first and last names, because many don't fit that pattern.

## `book_authors`: who wrote what (§2)

13,209 rows from `clean/book_authors.csv`. This table connects authors to books, so one author can have many books and one book can have many authors.

| Column | What it holds | Rules |
|---|---|---|
| `book_id` | The book | **Must point to a real book** |
| `author_id` | The person | **Must point to a real author** |
| `author_order` | Position in the list; 1 = first listed | 1 or more |

- The same person can't be listed twice on one book (each book-and-author pair is **unique**).
- Two people can't share the same position on one book (each book-and-position pair is **unique**).
- **Every book must have at least one author.** This is checked by `build_db.py` right after loading. If any book has none, the build stops with an error and no database is left behind.

## `copies`: the physical items on our shelves (§3)

425 rows. We stock the 300 most-rated books: 3 copies each of the top 25, 2 each of the next 75, and 1 each of the other 200.

| Column | What it holds | Rules |
|---|---|---|
| `copy_id` | ID number | Unique |
| `book_id` | Which book this is a copy of | **Required**, **must point to a real book** |
| `barcode` | Label on the item, e.g. `LIB-000001` | **Required** and **unique** |
| `status` | available, checked_out, on_hold_shelf, lost, damaged or retired | **Required**, one of those six (`valid_copy_status`). Kept in step with loans automatically (see `loans`) |
| `acquired_date` | Date we bought it | **Required** |
| `cost` | What we paid, in dollars ($8–$35 in the sample data) | **Required**, **can't be negative** (`cost_not_negative`) |
| `is_reference` | 1 = reference-only (can't leave the building), 0 = can be borrowed | 0 or 1. 10 copies are reference-only |

## `patrons`: people who borrow (§4)

35 made-up patrons, all with `example.com` email addresses and 555 phone numbers:

- **30 with obviously fictional names.** They include 4 children with guardians, one expired card (Otto Fakename) and one blocked patron (Hal Dummydata).
- **5 Harry Potter characters** (cards `CARD-0901` to `CARD-0905`), with hand-picked borrowing histories:
  - Hermione returns everything early.
  - Harry and Luna each have a book out.
  - Ron's *Charlotte's Web* is overdue.
  - Draco has never borrowed anything.

| Column | What it holds | Rules |
|---|---|---|
| `patron_id` | ID number | Unique |
| `name` | Full name | **Required**, can't be just spaces |
| `card_number` | Library card number, e.g. `CARD-0001` | **Required** and **unique** |
| `email`, `phone` | How to reach them | **At least one is required** (`patron_has_contact`) |
| `address` | Home address | Optional |
| `patron_type` | adult, child, senior or staff | **Required**, one of those four (`valid_patron_type`). Decides the checkout limit |
| `joined_date` | When they signed up | **Required** |
| `card_expires` | When the card runs out | **Required**, must be after `joined_date` |
| `standing` | active, expired or blocked | **Required**, one of those three (`valid_standing`) |
| `guardian_id` | For a child: the patron who is their guardian | **Required for children** (`child_has_guardian`), **must point to a real patron**, and can't be the child themselves |

## `loans`: every checkout, ever (§5)

162 made-up loans over the past year, 12 of them by the Harry Potter members: 137 returned, 16 out and on time, 7 overdue, and 2 lost (more than 45 days overdue).

| Column | What it holds | Rules |
|---|---|---|
| `loan_id` | ID number | Unique |
| `copy_id` | Which copy went out | **Required**, **must point to a real copy** |
| `patron_id` | Who borrowed it | **Required**, **must point to a real patron** |
| `checkout_date` | When it went out | **Required** |
| `due_date` | When it's due back | **Required**, **must be after the checkout date** (`due_after_checkout`) |
| `return_date` | When it came back. Empty while it's still out | **Can't be before the checkout date** (`return_not_before_checkout`) |
| `renewal_count` | Times renewed | Can't be negative or above the `max_renewals` policy (automatic check) |

Rules that look at more than one table:

- **A copy can't be out to two people at once.** Among loans that haven't been returned, each copy can appear only once (a unique index on `copy_id` for unreturned loans).
- **Blocked or expired patrons can't borrow.** An automatic check refuses the loan if the patron's standing isn't `active`, or their card expired before the checkout date.
- **Patrons over the fine limit can't borrow (§7).** The same automatic check adds up the patron's unpaid fines and refuses if the total is over the `block_limit` policy.
- **No going over the checkout limit.** An automatic check counts the patron's unreturned loans and refuses if they're already at the limit for their type (from the policies table).
- **Reference-only copies can't be loaned.** Neither can copies marked lost, damaged or retired.
- **Old loans are never deleted.** Any attempt to delete a loan is refused.
- **Copy status matches loans.** When a loan is added, the copy is marked `checked_out` automatically. When the return date is filled in, it goes back to `available`.

## `holds`: reservations (§6)

10 made-up holds, including a queue of 3 people waiting for *The Hunger Games*, whose copies are all out.

| Column | What it holds | Rules |
|---|---|---|
| `hold_id` | ID number | Unique |
| `book_id` | Which book (any copy will do) | **Required**, **must point to a real book** |
| `patron_id` | Who wants it | **Required**, **must point to a real patron** |
| `placed_at` | Date and time the hold was placed. Earliest goes first in the queue | **Required** |
| `status` | waiting, ready, picked_up, cancelled or expired | **Required**, one of those five (`valid_hold_status`) |
| `pickup_deadline` | Last day to collect a ready hold | **Required when the status is `ready`** (`ready_hold_has_deadline`) |

- **No two active holds on the same book.** A patron can have only one `waiting` or `ready` hold per book. Old cancelled or finished holds don't count.
- **You can't hold a book you already have.** An automatic check refuses a hold if the patron currently has a copy of that book checked out.

## `fines` (§7)

43 made-up fines: late fines for items returned late or still overdue, two lost-item fines, and one damaged-item fine. Some are paid and some aren't. The blocked patron owes $22.46.

| Column | What it holds | Rules |
|---|---|---|
| `fine_id` | ID number | Unique |
| `patron_id` | Who owes it | **Required**, **must point to a real patron**, and must be the patron who had the loan (automatic check) |
| `loan_id` | Which loan it's for | **Required**, **must point to a real loan** |
| `amount` | Dollars | **Required**, **can't be negative** (`fine_not_negative`) |
| `reason` | late, lost or damaged | **Required**, one of those three (`valid_fine_reason`) |
| `charged_date` | When it was charged | **Required** |
| `paid_date` | When it was paid. Empty means unpaid | Can't be before `charged_date` |

## `policies`: settings you can change (§8)

One row per setting. The automatic checks read these values, so you can change a setting here without touching any code.

| `policy_key` | `value` | Meaning |
|---|---|---|
| `loan_days_book` | 21 | Loan length (days) for hardcovers and paperbacks |
| `loan_days_dvd` | 7 | Loan length for DVDs |
| `loan_days_audiobook` | 14 | Loan length for audiobooks |
| `checkout_limit_adult` | 10 | Most items out at once, adults |
| `checkout_limit_senior` | 10 | …seniors |
| `checkout_limit_staff` | 10 | …staff |
| `checkout_limit_child` | 5 | …children |
| `max_renewals` | 2 | Most renewals per loan |
| `late_fine_per_day` | 0.25 | Dollars per day late, capped at the copy's cost |
| `block_limit` | 10.00 | Unpaid fines above this stop borrowing |
| `lost_after_days` | 45 | Days overdue before an item counts as lost |
| `hold_pickup_days` | 7 | Days to collect a ready hold |

Each value must be zero or more. For example, to let children borrow 8 items, change `checkout_limit_child` to 8. The checkout-limit rule picks it up immediately.

---

## Decisions not covered by the original instructions

- **Shelf codes skip name suffixes and punctuation.** "Kurt Vonnegut Jr." gets `FIC VON` (not `FIC JR.`), and "Patrick O'Brian" gets `FIC OBR`. Short surnames give short codes: Marie Lu → `FIC LU`.
- **"Year can't be in the future" uses the real calendar,** not the fixed sample date, so it stays correct in future years.
- **"Expired" means either standing `expired` or a card past its expiration date.** A card that has run out can't borrow even if nobody has updated its standing yet.
- **Lost items stay on loan.** A lost item's loan is never given a return date (it never came back), and its copy is marked `lost` instead of `checked_out`.
- **Lost, damaged and retired copies can't be loaned,** in addition to reference-only copies.
- **Fines go to the right person.** A fine must be charged to the patron who had that loan.
- **Author names are unique regardless of capitalization.**
- **Money is stored in dollars with cents** (e.g. 12.99), not as whole cents.
- **The sample data is the same every time** the database is rebuilt (fixed starting point for the random choices), so query results don't change between builds.
- **Holds don't record which copy was set aside.** A ready hold's copy is the one marked `on_hold_shelf`.
