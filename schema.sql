-- schema.sql: the structure of library.db (tables, indexes and triggers).
--
-- Exported from library.db with SQLite's .schema command, so it matches the
-- submitted database exactly. It holds structure only, no data; build_db.py
-- creates this same structure and then loads the data.
--
-- To create an empty database with this structure:
--   sqlite3 empty.db < schema.sql

CREATE TABLE policies (
    policy_key  TEXT PRIMARY KEY,
    value       REAL NOT NULL CHECK (value >= 0),
    description TEXT NOT NULL
);
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
CREATE TABLE authors (
    author_id INTEGER PRIMARY KEY,
    name      TEXT NOT NULL UNIQUE COLLATE NOCASE
              CONSTRAINT author_name_not_blank CHECK (trim(name) <> '')
);
CREATE TABLE book_authors (
    book_id      INTEGER NOT NULL REFERENCES books (book_id),
    author_id    INTEGER NOT NULL REFERENCES authors (author_id),
    author_order INTEGER NOT NULL
                 CONSTRAINT author_order_positive CHECK (author_order >= 1),
    PRIMARY KEY (book_id, author_id),       -- same person can't be listed twice on a book
    UNIQUE (book_id, author_order)          -- two people can't share a position on a book
);
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
CREATE TABLE fines (
    fine_id      INTEGER PRIMARY KEY,
    patron_id    INTEGER NOT NULL REFERENCES patrons (patron_id),
    loan_id      INTEGER NOT NULL REFERENCES loans (loan_id),
    amount       REAL NOT NULL CONSTRAINT fine_not_negative CHECK (amount >= 0),
    reason       TEXT NOT NULL CONSTRAINT valid_fine_reason CHECK (reason IN ('late', 'lost', 'damaged')),
    charged_date TEXT NOT NULL CHECK (charged_date = date(charged_date)),
    paid_date    TEXT CHECK (paid_date IS NULL OR (paid_date = date(paid_date) AND paid_date >= charged_date))
);
CREATE INDEX book_authors_by_author ON book_authors (author_id);
CREATE INDEX copies_by_book ON copies (book_id);
CREATE INDEX loans_by_patron ON loans (patron_id);
CREATE INDEX fines_by_patron ON fines (patron_id);
CREATE UNIQUE INDEX loans_one_open_per_copy ON loans (copy_id) WHERE return_date IS NULL;
CREATE UNIQUE INDEX holds_one_active_per_patron_book ON holds (patron_id, book_id)
    WHERE status IN ('waiting', 'ready');
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
CREATE TRIGGER loans_copy_can_circulate
BEFORE INSERT ON loans
BEGIN
    SELECT RAISE(ABORT, 'Reference-only copies cannot be loaned')
    WHERE (SELECT is_reference FROM copies WHERE copy_id = NEW.copy_id) = 1;
    SELECT RAISE(ABORT, 'Copy is lost, damaged or retired and cannot be loaned')
    WHERE (SELECT status FROM copies WHERE copy_id = NEW.copy_id) IN ('lost', 'damaged', 'retired');
END;
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
CREATE TRIGGER loans_never_deleted
BEFORE DELETE ON loans
BEGIN
    SELECT RAISE(ABORT, 'Loans are never deleted; they are the library''s history');
END;
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
CREATE TRIGGER holds_not_on_book_already_out
BEFORE INSERT ON holds
BEGIN
    SELECT RAISE(ABORT, 'Patron already has this book checked out')
    WHERE EXISTS (SELECT 1 FROM loans l JOIN copies c ON c.copy_id = l.copy_id
                  WHERE l.patron_id = NEW.patron_id
                    AND c.book_id = NEW.book_id
                    AND l.return_date IS NULL);
END;
CREATE TRIGGER fines_patron_matches_loan
BEFORE INSERT ON fines
WHEN NEW.patron_id <> (SELECT patron_id FROM loans WHERE loan_id = NEW.loan_id)
BEGIN
    SELECT RAISE(ABORT, 'Fine must be charged to the patron who had the loan');
END;
