"""Build library.db from scratch.

Steps: delete any old library.db, create the tables and rules, load the catalog
from clean/, check that every book has an author, then add made-up sample data
(copies, patrons, loans, holds, fines) as of a fixed "today".

Run:  python3 build_db.py
"""
import csv
import datetime as dt
import os
import random
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "library.db")
CLEAN_DIR = os.path.join(HERE, "clean")

# Fixed "today" for all sample data, so overdue results don't change from day to day.
TODAY = dt.date(2026, 10, 26)
# Fixed random seed, so every build makes exactly the same made-up data.
SEED = 2026

# ---------------------------------------------------------------------------
# Schema: tables, then indexes, then triggers.
# Each rule is labeled with the section of CLAUDE_CODE_PROMPT.md it enforces.
# ---------------------------------------------------------------------------
SCHEMA = """
-- 8. Library policies: one row per setting, read by the triggers below.
CREATE TABLE policies (
    policy_key  TEXT PRIMARY KEY,
    value       REAL NOT NULL CHECK (value >= 0),
    description TEXT NOT NULL
);

-- 1. Books: the titles in the catalog.
CREATE TABLE books (
    book_id           INTEGER PRIMARY KEY,               -- unique
    title             TEXT NOT NULL
                      CONSTRAINT title_not_blank CHECK (trim(title) <> ''),
    full_title        TEXT,
    original_title    TEXT,
    series_name       TEXT,
    series_number     TEXT,
    isbn10            TEXT UNIQUE,                       -- optional, unique when present
    isbn13            TEXT UNIQUE,                       -- optional, unique when present
    publication_year  INTEGER,                           -- negative = BC; blank allowed
    language_code     TEXT,
    average_rating    REAL,
    ratings_count     INTEGER,
    goodreads_book_id INTEGER,
    goodreads_work_id INTEGER,
    image_url         TEXT,
    format            TEXT NOT NULL
                      CONSTRAINT valid_format CHECK (format IN ('hardcover', 'paperback', 'audiobook', 'DVD')),
    audience          TEXT NOT NULL
                      CONSTRAINT valid_audience CHECK (audience IN ('adult', 'teen', 'children')),
    shelf_code        TEXT,
    publisher         TEXT,
    genre             TEXT
);

-- 2. Authors: one full name per person, unique (ignoring upper/lower case).
CREATE TABLE authors (
    author_id INTEGER PRIMARY KEY,
    name      TEXT NOT NULL UNIQUE COLLATE NOCASE
              CONSTRAINT author_name_not_blank CHECK (trim(name) <> '')
);

-- 2. Who wrote what: many authors per book, many books per author.
CREATE TABLE book_authors (
    book_id      INTEGER NOT NULL REFERENCES books (book_id),
    author_id    INTEGER NOT NULL REFERENCES authors (author_id),
    author_order INTEGER NOT NULL
                 CONSTRAINT author_order_positive CHECK (author_order >= 1),
    PRIMARY KEY (book_id, author_id),       -- same person can't be listed twice on a book
    UNIQUE (book_id, author_order)          -- two people can't share a position on a book
);

-- 3. Copies: the physical items on the shelf.
CREATE TABLE copies (
    copy_id       INTEGER PRIMARY KEY,
    book_id       INTEGER NOT NULL REFERENCES books (book_id),
    barcode       TEXT NOT NULL UNIQUE,
    status        TEXT NOT NULL DEFAULT 'available'
                  CONSTRAINT valid_copy_status CHECK (status IN
                      ('available', 'checked_out', 'on_hold_shelf', 'lost', 'damaged', 'retired')),
    acquired_date TEXT NOT NULL CHECK (acquired_date = date(acquired_date)),
    cost          REAL NOT NULL CONSTRAINT cost_not_negative CHECK (cost >= 0),
    is_reference  INTEGER NOT NULL DEFAULT 0 CHECK (is_reference IN (0, 1))
);

-- 4. Patrons: people who borrow.
CREATE TABLE patrons (
    patron_id    INTEGER PRIMARY KEY,
    name         TEXT NOT NULL CONSTRAINT patron_name_not_blank CHECK (trim(name) <> ''),
    card_number  TEXT NOT NULL UNIQUE,
    email        TEXT,
    phone        TEXT,
    address      TEXT,
    patron_type  TEXT NOT NULL
                 CONSTRAINT valid_patron_type CHECK (patron_type IN ('adult', 'child', 'senior', 'staff')),
    joined_date  TEXT NOT NULL CHECK (joined_date = date(joined_date)),
    card_expires TEXT NOT NULL CHECK (card_expires = date(card_expires)),
    standing     TEXT NOT NULL DEFAULT 'active'
                 CONSTRAINT valid_standing CHECK (standing IN ('active', 'expired', 'blocked')),
    guardian_id  INTEGER REFERENCES patrons (patron_id),
    CONSTRAINT patron_has_contact
        CHECK (trim(coalesce(email, '')) <> '' OR trim(coalesce(phone, '')) <> ''),
    CONSTRAINT child_has_guardian CHECK (patron_type <> 'child' OR guardian_id IS NOT NULL),
    CONSTRAINT guardian_is_someone_else CHECK (guardian_id IS NULL OR guardian_id <> patron_id),
    CONSTRAINT expires_after_joined CHECK (card_expires > joined_date)
);

-- 5. Loans: every checkout, kept forever.
CREATE TABLE loans (
    loan_id       INTEGER PRIMARY KEY,
    copy_id       INTEGER NOT NULL REFERENCES copies (copy_id),
    patron_id     INTEGER NOT NULL REFERENCES patrons (patron_id),
    checkout_date TEXT NOT NULL CHECK (checkout_date = date(checkout_date)),
    due_date      TEXT NOT NULL CHECK (due_date = date(due_date)),
    return_date   TEXT CHECK (return_date IS NULL OR return_date = date(return_date)),
    renewal_count INTEGER NOT NULL DEFAULT 0 CHECK (renewal_count >= 0),
    CONSTRAINT due_after_checkout CHECK (due_date > checkout_date),
    CONSTRAINT return_not_before_checkout CHECK (return_date IS NULL OR return_date >= checkout_date)
);

-- 6. Holds: reservations for a book (not a specific copy).
CREATE TABLE holds (
    hold_id         INTEGER PRIMARY KEY,
    book_id         INTEGER NOT NULL REFERENCES books (book_id),
    patron_id       INTEGER NOT NULL REFERENCES patrons (patron_id),
    placed_at       TEXT NOT NULL CHECK (placed_at = datetime(placed_at)),
    status          TEXT NOT NULL DEFAULT 'waiting'
                    CONSTRAINT valid_hold_status CHECK (status IN
                        ('waiting', 'ready', 'picked_up', 'cancelled', 'expired')),
    pickup_deadline TEXT CHECK (pickup_deadline IS NULL OR pickup_deadline = date(pickup_deadline)),
    CONSTRAINT ready_hold_has_deadline CHECK (status <> 'ready' OR pickup_deadline IS NOT NULL)
);

-- 7. Fines.
CREATE TABLE fines (
    fine_id      INTEGER PRIMARY KEY,
    patron_id    INTEGER NOT NULL REFERENCES patrons (patron_id),
    loan_id      INTEGER NOT NULL REFERENCES loans (loan_id),
    amount       REAL NOT NULL CONSTRAINT fine_not_negative CHECK (amount >= 0),
    reason       TEXT NOT NULL CONSTRAINT valid_fine_reason CHECK (reason IN ('late', 'lost', 'damaged')),
    charged_date TEXT NOT NULL CHECK (charged_date = date(charged_date)),
    paid_date    TEXT CHECK (paid_date IS NULL OR (paid_date = date(paid_date) AND paid_date >= charged_date))
);

-- Indexes: speed up common lookups, and enforce two "only one at a time" rules.
CREATE INDEX book_authors_by_author ON book_authors (author_id);
CREATE INDEX copies_by_book ON copies (book_id);
CREATE INDEX loans_by_patron ON loans (patron_id);
CREATE INDEX fines_by_patron ON fines (patron_id);
-- 5. A copy can't be checked out to two people at once.
CREATE UNIQUE INDEX loans_one_open_per_copy ON loans (copy_id) WHERE return_date IS NULL;
-- 6. A patron can't have two active holds on the same book.
CREATE UNIQUE INDEX holds_one_active_per_patron_book ON holds (patron_id, book_id)
    WHERE status IN ('waiting', 'ready');

-- 1. The year can't be in the future (checked against the real calendar).
CREATE TRIGGER books_year_not_future_insert
BEFORE INSERT ON books
WHEN NEW.publication_year > CAST(strftime('%Y', 'now') AS INTEGER)
BEGIN
    SELECT RAISE(ABORT, 'publication_year cannot be in the future');
END;

CREATE TRIGGER books_year_not_future_update
BEFORE UPDATE OF publication_year ON books
WHEN NEW.publication_year > CAST(strftime('%Y', 'now') AS INTEGER)
BEGIN
    SELECT RAISE(ABORT, 'publication_year cannot be in the future');
END;

-- 5 + 7. A blocked or expired patron can't borrow, and neither can a patron
-- whose unpaid fines are over the blocking limit.
CREATE TRIGGER loans_patron_in_good_standing
BEFORE INSERT ON loans
BEGIN
    SELECT RAISE(ABORT, 'Patron cannot borrow: card is blocked or expired')
    WHERE EXISTS (SELECT 1 FROM patrons
                  WHERE patron_id = NEW.patron_id
                    AND (standing <> 'active' OR card_expires < NEW.checkout_date));
    SELECT RAISE(ABORT, 'Patron cannot borrow: unpaid fines are over the blocking limit')
    WHERE (SELECT coalesce(sum(amount), 0) FROM fines
           WHERE patron_id = NEW.patron_id AND paid_date IS NULL)
        > (SELECT value FROM policies WHERE policy_key = 'block_limit');
END;

-- 5. A patron can't go over their checkout limit (limit depends on patron type).
CREATE TRIGGER loans_within_checkout_limit
BEFORE INSERT ON loans
WHEN NEW.return_date IS NULL
BEGIN
    SELECT RAISE(ABORT, 'Patron is at their checkout limit')
    WHERE (SELECT count(*) FROM loans
           WHERE patron_id = NEW.patron_id AND return_date IS NULL)
       >= (SELECT pol.value FROM policies pol
           JOIN patrons p ON pol.policy_key = 'checkout_limit_' || p.patron_type
           WHERE p.patron_id = NEW.patron_id);
END;

-- 5. A reference-only copy can't be loaned (nor a lost, damaged or retired one).
CREATE TRIGGER loans_copy_can_circulate
BEFORE INSERT ON loans
BEGIN
    SELECT RAISE(ABORT, 'Reference-only copies cannot be loaned')
    WHERE (SELECT is_reference FROM copies WHERE copy_id = NEW.copy_id) = 1;
    SELECT RAISE(ABORT, 'Copy is lost, damaged or retired and cannot be loaned')
    WHERE (SELECT status FROM copies WHERE copy_id = NEW.copy_id) IN ('lost', 'damaged', 'retired');
END;

-- 8. Renewals can't go over the maximum-renewals policy.
CREATE TRIGGER loans_renewal_limit_insert
BEFORE INSERT ON loans
WHEN NEW.renewal_count > (SELECT value FROM policies WHERE policy_key = 'max_renewals')
BEGIN
    SELECT RAISE(ABORT, 'Renewal count is over the maximum renewals policy');
END;

CREATE TRIGGER loans_renewal_limit_update
BEFORE UPDATE OF renewal_count ON loans
WHEN NEW.renewal_count > (SELECT value FROM policies WHERE policy_key = 'max_renewals')
BEGIN
    SELECT RAISE(ABORT, 'Renewal count is over the maximum renewals policy');
END;

-- 5. Old loans are never deleted.
CREATE TRIGGER loans_never_deleted
BEFORE DELETE ON loans
BEGIN
    SELECT RAISE(ABORT, 'Loans are never deleted; they are the library''s history');
END;

-- 5. Keep copy status in step with loans: out means checked_out, back means available.
CREATE TRIGGER loans_mark_copy_out
AFTER INSERT ON loans
WHEN NEW.return_date IS NULL
BEGIN
    UPDATE copies SET status = 'checked_out' WHERE copy_id = NEW.copy_id;
END;

CREATE TRIGGER loans_mark_copy_back
AFTER UPDATE OF return_date ON loans
WHEN OLD.return_date IS NULL AND NEW.return_date IS NOT NULL
BEGIN
    UPDATE copies SET status = 'available'
    WHERE copy_id = NEW.copy_id AND status = 'checked_out';
END;

-- 6. A patron can't hold a book they currently have checked out.
CREATE TRIGGER holds_not_on_book_already_out
BEFORE INSERT ON holds
BEGIN
    SELECT RAISE(ABORT, 'Patron already has this book checked out')
    WHERE EXISTS (SELECT 1 FROM loans l JOIN copies c ON c.copy_id = l.copy_id
                  WHERE l.patron_id = NEW.patron_id
                    AND c.book_id = NEW.book_id
                    AND l.return_date IS NULL);
END;

-- 7. A fine goes to the patron who had the loan.
CREATE TRIGGER fines_patron_matches_loan
BEFORE INSERT ON fines
WHEN NEW.patron_id <> (SELECT patron_id FROM loans WHERE loan_id = NEW.loan_id)
BEGIN
    SELECT RAISE(ABORT, 'Fine must be charged to the patron who had the loan');
END;
"""

POLICIES = [
    ("loan_days_book", 21, "Loan length in days for hardcovers and paperbacks"),
    ("loan_days_dvd", 7, "Loan length in days for DVDs"),
    ("loan_days_audiobook", 14, "Loan length in days for audiobooks"),
    ("checkout_limit_adult", 10, "Most items an adult can have out at once"),
    ("checkout_limit_senior", 10, "Most items a senior can have out at once"),
    ("checkout_limit_staff", 10, "Most items a staff member can have out at once"),
    ("checkout_limit_child", 5, "Most items a child can have out at once"),
    ("max_renewals", 2, "Most times one loan can be renewed"),
    ("late_fine_per_day", 0.25, "Late fine in dollars per day; total is capped at the copy's cost"),
    ("block_limit", 10.00, "Unpaid fines (dollars) above this amount stop a patron from borrowing"),
    ("lost_after_days", 45, "Days overdue after which an item is treated as lost"),
    ("hold_pickup_days", 7, "Days a patron has to pick up a ready hold"),
]

FORMATS = ["paperback", "hardcover", "audiobook", "DVD"]
FORMAT_WEIGHTS = [50, 35, 10, 5]
AUDIENCES = ["adult", "teen", "children"]
AUDIENCE_WEIGHTS = [70, 20, 10]
NAME_SUFFIXES = {"jr", "jr.", "sr", "sr.", "ii", "iii", "iv"}


def read_csv(name):
    with open(os.path.join(CLEAN_DIR, name), newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def blank_to_none(value):
    return value if value != "" else None


def to_int(value):
    return int(value) if value != "" else None


def to_float(value):
    return float(value) if value != "" else None


def shelf_code(author_name):
    """'Suzanne Collins' -> 'FIC COL'. Skips suffixes like 'Jr.' and keeps letters only."""
    words = author_name.split()
    while len(words) > 1 and words[-1].lower() in NAME_SUFFIXES:
        words.pop()
    letters = "".join(ch for ch in words[-1] if ch.isalpha())
    return "FIC " + letters[:3].upper()


def check_every_book_has_author(conn):
    """2. Every book must have at least one author; stop with an error if not."""
    missing = conn.execute(
        "SELECT book_id, title FROM books"
        " WHERE book_id NOT IN (SELECT book_id FROM book_authors) ORDER BY book_id"
    ).fetchall()
    if missing:
        raise RuntimeError(f"{len(missing)} book(s) have no author, e.g. {missing[:5]}")


def load_catalog(conn, rng):
    """Load books, authors and book_authors from clean/."""
    books = read_csv("books.csv")
    authors = read_csv("authors.csv")
    links = read_csv("book_authors.csv")

    author_name = {int(a["author_id"]): a["name"] for a in authors}
    first_author = {int(l["book_id"]): int(l["author_id"]) for l in links if l["author_order"] == "1"}

    conn.executemany(
        "INSERT INTO authors (author_id, name) VALUES (?, ?)",
        [(int(a["author_id"]), a["name"]) for a in authors],
    )

    rows = []
    for b in books:
        book_id = int(b["book_id"])
        first = first_author.get(book_id)
        rows.append((
            book_id, blank_to_none(b["title"]), blank_to_none(b["full_title"]),
            blank_to_none(b["original_title"]), blank_to_none(b["series_name"]),
            blank_to_none(b["series_number"]), blank_to_none(b["isbn10"]),
            blank_to_none(b["isbn13"]), to_int(b["publication_year"]),
            blank_to_none(b["language_code"]), to_float(b["average_rating"]),
            to_int(b["ratings_count"]), to_int(b["goodreads_book_id"]),
            to_int(b["goodreads_work_id"]), blank_to_none(b["image_url"]),
            rng.choices(FORMATS, FORMAT_WEIGHTS)[0],
            rng.choices(AUDIENCES, AUDIENCE_WEIGHTS)[0],
            shelf_code(author_name[first]) if first else None,
        ))
    conn.executemany(
        """INSERT INTO books (book_id, title, full_title, original_title, series_name,
               series_number, isbn10, isbn13, publication_year, language_code,
               average_rating, ratings_count, goodreads_book_id, goodreads_work_id,
               image_url, format, audience, shelf_code)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        rows,
    )

    conn.executemany(
        "INSERT INTO book_authors (book_id, author_id, author_order) VALUES (?, ?, ?)",
        [(int(l["book_id"]), int(l["author_id"]), int(l["author_order"])) for l in links],
    )


def random_date(rng, start, end):
    return start + dt.timedelta(days=rng.randint(0, (end - start).days))


def add_copies(conn, rng):
    """3. Copies of the 300 most-rated books: 3 each for the top 25, 2 for the next 75, 1 for the rest."""
    top = conn.execute(
        "SELECT book_id, format FROM books ORDER BY ratings_count DESC, book_id LIMIT 300"
    ).fetchall()
    copies = []
    for rank, (book_id, fmt) in enumerate(top, start=1):
        count = 3 if rank <= 25 else 2 if rank <= 100 else 1
        for _ in range(count):
            copies.append({
                "barcode": f"LIB-{len(copies) + 1:06d}",
                "book_id": book_id,
                "format": fmt,
                "rank": rank,
                "acquired": random_date(rng, dt.date(2025, 8, 1), dt.date(2025, 10, 20)),
                "cost": round(rng.uniform(8, 35), 2),
                "is_reference": 0,
            })

    # About 10 reference-only copies, taken from books outside the top 25.
    for c in rng.sample([c for c in copies if c["rank"] > 25], 10):
        c["is_reference"] = 1

    for c in copies:
        cur = conn.execute(
            "INSERT INTO copies (book_id, barcode, acquired_date, cost, is_reference)"
            " VALUES (?, ?, ?, ?, ?)",
            (c["book_id"], c["barcode"], c["acquired"].isoformat(), c["cost"], c["is_reference"]),
        )
        c["copy_id"] = cur.lastrowid
    return copies


# 4. Made-up patrons: (name, type, guardian's name for children).
PATRONS = [
    ("Ada Placeholder", "adult", None), ("Bram Example", "adult", None),
    ("Cora Sampleton", "adult", None), ("Dex Fictitious", "adult", None),
    ("Edie Madeup", "adult", None), ("Finn Notreal", "adult", None),
    ("Gwen Testcase", "adult", None), ("Hal Dummydata", "adult", None),
    ("Iris Mockworth", "adult", None), ("Jules Pretendo", "adult", None),
    ("Kit Imaginary", "adult", None), ("Lena Hypothetical", "adult", None),
    ("Milo Faux", "adult", None), ("Nora Invented", "adult", None),
    ("Otto Fakename", "adult", None), ("Pia Standin", "adult", None),
    ("Quinn Lorem", "adult", None), ("Rory Ipsum", "adult", None),
    ("Sage Dolorsit", "adult", None), ("Tess Ametson", "adult", None),
    ("Vera Sampleworth", "senior", None), ("Walt Exemplar", "senior", None),
    ("Xena Fauxley", "senior", None),
    ("Yuri Shelver", "staff", None), ("Zara Catalog", "staff", None),
    ("Benny Barcode", "staff", None),
    ("Tiny Placeholder", "child", "Ada Placeholder"), ("Max Placeholder", "child", "Ada Placeholder"),
    ("Pip Example", "child", "Bram Example"), ("Lulu Sampleton", "child", "Cora Sampleton"),
]
PHONE_ONLY = "Finn Notreal"      # no email
EMAIL_ONLY = "Gwen Testcase"     # no phone
EXPIRED = "Otto Fakename"        # card ran out on 2026-08-15
BLOCKED = "Hal Dummydata"        # blocked, with unpaid fines over the limit
LOST_ITEM = "Milo Faux"          # lost an item; unpaid lost fine puts them over the limit


def add_patrons(conn, rng):
    patrons = {}
    for i, (name, ptype, guardian) in enumerate(PATRONS, start=1):
        if name == EXPIRED:
            joined = dt.date(2023, 8, 15)
        else:
            joined = random_date(rng, dt.date(2025, 9, 1), dt.date(2025, 10, 26))
        p = {
            "name": name,
            "type": ptype,
            "card": f"CARD-{i:04d}",
            "joined": joined,
            "expires": joined.replace(year=joined.year + 3),
            "guardian_id": None,
        }
        if guardian:
            g = patrons[guardian]
            p.update(email=None, phone=g["phone"], address=g["address"], guardian_id=g["patron_id"])
        else:
            p.update(
                email=None if name == PHONE_ONLY else name.lower().replace(" ", ".") + "@example.com",
                phone=None if name == EMAIL_ONLY else f"615-555-{100 + i:04d}",
                address=f"{100 + i} Example Street, Sampletown",
            )
        # Everyone starts active; standings are set after the loan history is loaded.
        cur = conn.execute(
            """INSERT INTO patrons (name, card_number, email, phone, address, patron_type,
                   joined_date, card_expires, guardian_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (name, p["card"], p["email"], p["phone"], p["address"], ptype,
             p["joined"].isoformat(), p["expires"].isoformat(), p["guardian_id"]),
        )
        p["patron_id"] = cur.lastrowid
        patrons[name] = p
    return patrons


def loan_days(fmt, policy):
    key = {"DVD": "loan_days_dvd", "audiobook": "loan_days_audiobook"}.get(fmt, "loan_days_book")
    return int(policy[key])


def add_activity(conn, rng, copies, patrons):
    """5-7. About 150 loans over the past year, then holds and fines that match them."""
    policy = dict(conn.execute("SELECT policy_key, value FROM policies"))
    start = TODAY - dt.timedelta(days=364)
    busy = {c["copy_id"]: [] for c in copies}   # copy_id -> [(checkout, return or None)]
    loans = []

    def is_free(copy, checkout, returned):
        end = returned or dt.date.max
        return all(checkout > (e or dt.date.max) or s > end for s, e in busy[copy["copy_id"]])

    def add_loan(copy, patron, checkout, due, returned, renewals=0, kind="returned"):
        busy[copy["copy_id"]].append((checkout, returned))
        loans.append({"copy": copy, "patron": patron, "checkout": checkout, "due": due,
                      "returned": returned, "renewals": renewals, "kind": kind})

    circulating = [c for c in copies if not c["is_reference"]]
    top_book = [c for c in circulating if c["rank"] == 1]          # 3 copies, all will be out
    others = [c for c in circulating if c["rank"] != 1]
    borrowers = [p for p in patrons.values() if p["name"] not in (EXPIRED, BLOCKED, LOST_ITEM)]

    # Open loans: 14 on time and 6 overdue (all three copies of the top book among them).
    open_copies = top_book + rng.sample(others, 17)
    open_patrons = rng.sample(borrowers, 20)
    for n, (copy, patron) in enumerate(zip(open_copies, open_patrons)):
        days = loan_days(copy["format"], policy)
        if n in (2, 3, 4, 5, 6, 7):             # overdue by 3-30 days (copy 2 is a top-book copy)
            due = TODAY - dt.timedelta(days=rng.randint(3, 30))
            add_loan(copy, patron, due - dt.timedelta(days=days), due, None, kind="overdue")
        else:                                   # on time: due after today
            checkout = TODAY - dt.timedelta(days=rng.randint(1, days - 1))
            add_loan(copy, patron, checkout, checkout + dt.timedelta(days=days), None, kind="out")

    # Lost: more than 45 days overdue, still unreturned. Copies costing $15+ so the
    # lost-item fine alone puts each patron over the $10 blocking limit.
    pricey = [c for c in others if c["cost"] >= 15 and not busy[c["copy_id"]]]
    for name, copy in zip((BLOCKED, LOST_ITEM), rng.sample(pricey, 2)):
        days = loan_days(copy["format"], policy)
        due = TODAY - dt.timedelta(days=rng.randint(50, 80))
        add_loan(copy, patrons[name], due - dt.timedelta(days=days), due, None, kind="lost")

    # Returned loans fill the rest of the year (128, for about 150 in total).
    everyone = list(patrons.values())
    returned_count = 0
    while returned_count < 128:
        copy = rng.choice(circulating)
        patron = rng.choice(everyone)
        renewals = rng.choices([0, 1, 2], [80, 15, 5])[0]
        period = loan_days(copy["format"], policy) * (1 + renewals)
        checkout = random_date(rng, start, TODAY - dt.timedelta(days=40))
        returned = checkout + dt.timedelta(days=rng.randint(2, period + 8))   # some come back late
        if (returned >= TODAY or checkout < copy["acquired"] or checkout < patron["joined"]
                or checkout > patron["expires"] or not is_free(copy, checkout, returned)):
            continue
        add_loan(copy, patron, checkout, checkout + dt.timedelta(days=period), returned, renewals)
        returned_count += 1

    # Insert in date order, through the triggers, so the rules check the history too.
    loans.sort(key=lambda l: l["checkout"])
    for l in loans:
        cur = conn.execute(
            """INSERT INTO loans (copy_id, patron_id, checkout_date, due_date, return_date, renewal_count)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (l["copy"]["copy_id"], l["patron"]["patron_id"], l["checkout"].isoformat(),
             l["due"].isoformat(), l["returned"] and l["returned"].isoformat(), l["renewals"]),
        )
        l["loan_id"] = cur.lastrowid

    # Copy statuses that loans alone don't set: lost, damaged and on the hold shelf.
    fines = []
    for l in loans:
        if l["kind"] == "lost":
            conn.execute("UPDATE copies SET status = 'lost' WHERE copy_id = ?", (l["copy"]["copy_id"],))
            charged = l["due"] + dt.timedelta(days=int(policy["lost_after_days"]))
            fines.append((l, l["copy"]["cost"], "lost", charged, None))

    def last_loan_of(copy):
        return max((l for l in loans if l["copy"] is copy), key=lambda l: l["checkout"], default=None)

    idle = [c for c in others
            if (last_loan_of(c) or {}).get("returned") is not None and c["rank"] > 25]
    damaged_copy, shelf_copy_pool = idle[0], idle[1:]
    conn.execute("UPDATE copies SET status = 'damaged' WHERE copy_id = ?", (damaged_copy["copy_id"],))
    damaged_loan = last_loan_of(damaged_copy)
    fines.append((damaged_loan, 5.00, "damaged", damaged_loan["returned"],
                  min(damaged_loan["returned"] + dt.timedelta(days=3), TODAY)))

    # Late fines: $0.25 a day, capped at the copy's cost.
    rate = policy["late_fine_per_day"]
    late_returns = [l for l in loans if l["returned"] and l["returned"] > l["due"]]
    unpaid_late = {id(l) for l in rng.sample(late_returns, 2)}
    for l in late_returns:
        amount = min(round((l["returned"] - l["due"]).days * rate, 2), l["copy"]["cost"])
        paid = None if id(l) in unpaid_late else min(l["returned"] + dt.timedelta(days=rng.randint(0, 14)), TODAY)
        fines.append((l, amount, "late", l["returned"], paid))
    for l in loans:
        if l["kind"] == "overdue":   # still out: charged as of today, unpaid
            amount = min(round((TODAY - l["due"]).days * rate, 2), l["copy"]["cost"])
            fines.append((l, amount, "late", TODAY, None))

    for l, amount, reason, charged, paid in fines:
        conn.execute(
            "INSERT INTO fines (patron_id, loan_id, amount, reason, charged_date, paid_date)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (l["patron"]["patron_id"], l["loan_id"], amount, reason, charged.isoformat(),
             paid and paid.isoformat()),
        )

    add_holds(conn, rng, loans, patrons, top_book, shelf_copy_pool, policy)

    conn.execute("UPDATE patrons SET standing = 'expired' WHERE name = ?", (EXPIRED,))
    conn.execute("UPDATE patrons SET standing = 'blocked' WHERE name = ?", (BLOCKED,))


def add_holds(conn, rng, loans, patrons, top_book, shelf_copy_pool, policy):
    """6. About 10 holds, including a queue of 3 on the most popular book."""
    def has_open(patron, book_id):
        return any(l["patron"] is patron and l["copy"]["book_id"] == book_id and l["returned"] is None
                   for l in loans)

    pool = [p for p in patrons.values() if p["name"] not in (EXPIRED, BLOCKED)]
    top_book_id = top_book[0]["book_id"]
    holds = []

    # Queue of 3 waiting on the top book (every copy is out).
    queue = [p for p in pool if not has_open(p, top_book_id)]
    for patron, placed in zip(rng.sample(queue, 3),
                              ["2026-10-10 09:15:00", "2026-10-14 16:40:00", "2026-10-20 11:05:00"]):
        holds.append((top_book_id, patron, placed, "waiting", None))

    # One ready on the hold shelf: a copy set aside, with a pickup deadline.
    shelf_copy = shelf_copy_pool[0]
    conn.execute("UPDATE copies SET status = 'on_hold_shelf' WHERE copy_id = ?", (shelf_copy["copy_id"],))
    ready_on = dt.date(2026, 10, 23)
    deadline = ready_on + dt.timedelta(days=int(policy["hold_pickup_days"]))
    holder = rng.choice([p for p in pool if not has_open(p, shelf_copy["book_id"])])
    holds.append((shelf_copy["book_id"], holder, "2026-10-19 10:30:00", "ready", deadline.isoformat()))

    # One waiting on a single-copy book that is out on time.
    single = next(l for l in loans if l["kind"] == "out" and l["copy"]["rank"] > 100)
    waiter = rng.choice([p for p in pool if p is not single["patron"]])
    holds.append((single["copy"]["book_id"], waiter, "2026-10-21 14:00:00", "waiting", None))

    # Two picked up: each matches a returned loan the patron collected.
    picked = [l for l in loans if l["kind"] == "returned" and l["patron"] in pool
              and not has_open(l["patron"], l["copy"]["book_id"])]
    for l in rng.sample(picked, 2):
        placed = l["checkout"] - dt.timedelta(days=3)
        holds.append((l["copy"]["book_id"], l["patron"], f"{placed.isoformat()} 12:00:00",
                      "picked_up", l["checkout"].isoformat()))

    # Two cancelled and one expired (never picked up before the deadline).
    for placed, status, deadline in [("2026-08-02 10:00:00", "cancelled", None),
                                     ("2026-09-01 15:30:00", "cancelled", None),
                                     ("2026-09-10 09:45:00", "expired", "2026-09-20")]:
        copy = rng.choice([l["copy"] for l in loans])
        patron = rng.choice([p for p in pool if not has_open(p, copy["book_id"])])
        holds.append((copy["book_id"], patron, placed, status, deadline))

    for book_id, patron, placed, status, deadline in holds:
        conn.execute(
            "INSERT INTO holds (book_id, patron_id, placed_at, status, pickup_deadline)"
            " VALUES (?, ?, ?, ?, ?)",
            (book_id, patron["patron_id"], placed, status, deadline),
        )


# Five Harry Potter members with hand-written borrowing histories. They are added
# after the random sample data, so they don't change any of it.
HOGWARTS_PATRONS = [
    # (name, card number, type, address)
    ("Hermione Granger", "CARD-0901", "staff", "The Library, Hogwarts Castle"),   # volunteers here
    ("Harry Potter", "CARD-0902", "adult", "4 Privet Drive, Little Whinging"),
    ("Ron Weasley", "CARD-0903", "adult", "The Burrow, Ottery St Catchpole"),
    ("Luna Lovegood", "CARD-0904", "adult", "The Lovegood House, Ottery St Catchpole"),
    ("Draco Malfoy", "CARD-0905", "adult", "Malfoy Manor, Wiltshire"),            # has never borrowed
]
HOGWARTS_LOANS = [
    # (member, book_id, checkout date, return date or None if still out)
    ("Hermione Granger", 10, "2025-11-03", "2025-11-17"),    # Pride and Prejudice
    ("Hermione Granger", 43, "2025-12-01", "2025-12-12"),    # Jane Eyre
    ("Hermione Granger", 79, "2026-01-05", "2026-01-19"),    # The Odyssey
    ("Hermione Granger", 71, "2026-02-09", "2026-02-20"),    # Frankenstein
    ("Hermione Granger", 125, "2026-09-14", "2026-09-25"),   # Hamlet
    ("Harry Potter", 7, "2026-03-02", "2026-03-20"),         # The Hobbit
    ("Harry Potter", 27, "2026-10-20", None),                # Half-Blood Prince: still out, on time
    ("Ron Weasley", 158, "2026-04-06", "2026-05-01"),        # Charlie and the Chocolate Factory: 4 days late
    ("Ron Weasley", 59, "2026-09-15", None),                 # Charlotte's Web: overdue (spiders)
    ("Luna Lovegood", 257, "2026-05-11", "2026-05-30"),      # Alice in Wonderland
    ("Luna Lovegood", 54, "2026-06-08", "2026-06-14"),       # The Hitchhiker's Guide to the Galaxy
    ("Luna Lovegood", 80, "2026-10-19", None),               # The Little Prince: still out, on time
]
# Copies used by the examples in queries.sql; the Hogwarts loans leave them alone.
QUERY_EXAMPLE_BARCODES = ("LIB-000001", "LIB-000004", "LIB-000031", "LIB-000034", "LIB-000043")


def add_hogwarts(conn):
    """Add the Hogwarts members and their loans (and late fines), through the usual rules."""
    policy = dict(conn.execute("SELECT policy_key, value FROM policies"))
    member_ids = {}
    for i, (name, card, ptype, address) in enumerate(HOGWARTS_PATRONS, start=1):
        cur = conn.execute(
            """INSERT INTO patrons (name, card_number, email, phone, address, patron_type,
                   joined_date, card_expires)
               VALUES (?, ?, ?, ?, ?, ?, '2025-09-01', '2028-09-01')""",
            (name, card, name.lower().replace(" ", ".") + "@example.com",
             f"615-555-{190 + i:04d}", address, ptype),
        )
        member_ids[name] = cur.lastrowid

    for name, book_id, checkout, returned in sorted(HOGWARTS_LOANS, key=lambda l: l[2]):
        fmt = conn.execute("SELECT format FROM books WHERE book_id = ?", (book_id,)).fetchone()[0]
        out = dt.date.fromisoformat(checkout)
        due = out + dt.timedelta(days=loan_days(fmt, policy))
        # First copy of the book that is free for the whole loan period.
        row = conn.execute(
            f"""SELECT copy_id, cost FROM copies c
                WHERE book_id = ? AND is_reference = 0
                  AND status IN ({"'available'" if returned is None else "'available', 'checked_out'"})
                  AND barcode NOT IN ({", ".join("?" * len(QUERY_EXAMPLE_BARCODES))})
                  AND NOT EXISTS (SELECT 1 FROM loans l WHERE l.copy_id = c.copy_id
                                  AND l.checkout_date <= ? AND coalesce(l.return_date, '9999-12-31') >= ?)
                ORDER BY copy_id LIMIT 1""",
            (book_id, *QUERY_EXAMPLE_BARCODES, returned or "9999-12-31", checkout),
        ).fetchone()
        if row is None:
            raise RuntimeError(f"No free copy of book {book_id} for {name} from {checkout}")
        copy_id, cost = row
        cur = conn.execute(
            "INSERT INTO loans (copy_id, patron_id, checkout_date, due_date, return_date)"
            " VALUES (?, ?, ?, ?, ?)",
            (copy_id, member_ids[name], checkout, due.isoformat(), returned),
        )

        # Late fines: paid on return if it came back late; unpaid, as of today, if still overdue.
        back = dt.date.fromisoformat(returned) if returned else None
        late_until, paid = (back, returned) if back else (TODAY, None)
        if late_until > due:
            amount = min(round((late_until - due).days * policy["late_fine_per_day"], 2), cost)
            conn.execute(
                "INSERT INTO fines (patron_id, loan_id, amount, reason, charged_date, paid_date)"
                " VALUES (?, ?, ?, 'late', ?, ?)",
                (member_ids[name], cur.lastrowid, amount, late_until.isoformat(), paid),
            )


def build(path):
    if os.path.exists(path):
        os.remove(path)
    rng = random.Random(SEED)
    conn = sqlite3.connect(path)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(SCHEMA)
        conn.executemany("INSERT INTO policies VALUES (?, ?, ?)", POLICIES)
        load_catalog(conn, rng)
        check_every_book_has_author(conn)
        copies = add_copies(conn, rng)
        patrons = add_patrons(conn, rng)
        add_activity(conn, rng, copies, patrons)
        add_hogwarts(conn)
        conn.commit()
    except Exception:
        conn.close()
        os.remove(path)   # never leave a half-built database behind
        raise
    return conn


def main():
    try:
        conn = build(DB_PATH)
    except (RuntimeError, sqlite3.Error) as e:
        sys.exit(f"Build failed: {e}")
    print(f"Built {DB_PATH} (today = {TODAY})")
    for table in ["policies", "books", "authors", "book_authors", "copies",
                  "patrons", "loans", "holds", "fines"]:
        count = conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        print(f"  {table:<13}{count:>6} rows")
    conn.close()


if __name__ == "__main__":
    main()
