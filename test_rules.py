"""Try to break every rule in library.db and confirm the database refuses.

Works on an in-memory copy, so library.db itself is never changed.
Each attempt must be refused for the *right* reason (the error has to name
the rule being tested); a refusal for any other reason counts as FAIL.

Run:  python3 build_db.py && python3 test_rules.py
"""
import os
import sqlite3
import sys

import build_db

T = build_db.TODAY.isoformat()          # '2026-10-26'
DUE = "2026-11-16"

disk = sqlite3.connect(build_db.DB_PATH)
conn = sqlite3.connect(":memory:", isolation_level=None)   # we manage transactions ourselves
disk.backup(conn)
disk.close()
conn.execute("PRAGMA foreign_keys = ON")

results = []


def one(sql, *params):
    return conn.execute(sql, params).fetchone()[0]


def report(section, rule, ok, detail):
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  [{section}] {rule}")
    print(f"        {detail}")


def attempt(setup, sql, params):
    """Run setup statements then the attempt inside a savepoint, always undoing it.
    Returns None if the attempt was accepted, or the error message."""
    conn.execute("SAVEPOINT t")
    try:
        for s, p in setup:
            conn.execute(s, p)
        conn.execute(sql, params)
        return None
    except sqlite3.Error as e:
        return str(e)
    finally:
        conn.execute("ROLLBACK TO t")
        conn.execute("RELEASE t")


def expect_refused(section, rule, sql, params=(), expect="", setup=()):
    error = attempt(setup, sql, params)
    if error is None:
        report(section, rule, False, "database ACCEPTED it")
    elif expect in error:
        report(section, rule, True, f"refused: {error}")
    else:
        report(section, rule, False, f"refused for the wrong reason: {error}")


def expect_allowed(section, rule, sql, params=(), setup=()):
    error = attempt(setup, sql, params)
    report(section, rule, error is None, "accepted" if error is None else f"wrongly refused: {error}")


# --- People and items the tests use, looked up from the built data ---------
FREE_PATRON = """SELECT patron_id FROM patrons p
    WHERE standing = 'active' AND patron_type = ? AND card_expires >= ?
      AND NOT EXISTS (SELECT 1 FROM fines f WHERE f.patron_id = p.patron_id AND f.paid_date IS NULL)
      AND NOT EXISTS (SELECT 1 FROM loans l WHERE l.patron_id = p.patron_id AND l.return_date IS NULL)
    ORDER BY patron_id LIMIT 1"""
adult = one(FREE_PATRON, "adult", T)
child = one(FREE_PATRON, "child", T)
blocked = one("SELECT patron_id FROM patrons WHERE standing = 'blocked'")
expired = one("SELECT patron_id FROM patrons WHERE standing = 'expired'")
over_limit_active = one("""SELECT patron_id FROM fines JOIN patrons USING (patron_id)
    WHERE paid_date IS NULL AND standing = 'active'
    GROUP BY patron_id HAVING sum(amount) > 10 LIMIT 1""")
free_copies = [r[0] for r in conn.execute(
    "SELECT copy_id FROM copies WHERE status = 'available' AND is_reference = 0 ORDER BY copy_id LIMIT 6")]
reference_copy = one("SELECT copy_id FROM copies WHERE is_reference = 1 LIMIT 1")
damaged_copy = one("SELECT copy_id FROM copies WHERE status = 'damaged' LIMIT 1")
open_loan_id, out_copy, out_patron, out_book = conn.execute(
    """SELECT l.loan_id, l.copy_id, l.patron_id, c.book_id FROM loans l JOIN copies c USING (copy_id)
       WHERE l.return_date IS NULL AND c.status = 'checked_out' LIMIT 1""").fetchone()
first_author_of_book1 = one("SELECT author_id FROM book_authors WHERE book_id = 1 AND author_order = 1")
other_author = one("SELECT author_id FROM authors WHERE author_id NOT IN"
                   " (SELECT author_id FROM book_authors WHERE book_id = 1) LIMIT 1")

LOAN = "INSERT INTO loans (copy_id, patron_id, checkout_date, due_date) VALUES (?, ?, ?, ?)"
BOOK = "INSERT INTO books (book_id, title, format, audience, publication_year, isbn10) VALUES (?, ?, ?, ?, ?, ?)"
COPY = "INSERT INTO copies (book_id, barcode, status, acquired_date, cost) VALUES (?, ?, ?, ?, ?)"
HOLD = "INSERT INTO holds (book_id, patron_id, placed_at, status, pickup_deadline) VALUES (?, ?, ?, ?, ?)"
FINE = "INSERT INTO fines (patron_id, loan_id, amount, reason, charged_date) VALUES (?, ?, ?, ?, ?)"


def patron(**changes):
    """An INSERT for a valid new patron, with some fields changed to break a rule."""
    p = {"name": "Test Person", "card_number": "CARD-TEST", "email": "test.person@example.com",
         "phone": None, "patron_type": "adult", "joined_date": T, "card_expires": "2029-10-26",
         "guardian_id": None, "standing": "active"}
    p.update(changes)
    cols = ", ".join(p)
    return f"INSERT INTO patrons ({cols}) VALUES ({', '.join('?' * len(p))})", tuple(p.values())


print(f"Testing rules on an in-memory copy of {os.path.basename(build_db.DB_PATH)}\n")

# 1. Books
s = "1 Books"
expect_refused(s, "Every book must have a title (missing)", BOOK,
               (900001, None, "paperback", "adult", 2000, None), "NOT NULL constraint failed: books.title")
expect_refused(s, "Every book must have a title (blank)", BOOK,
               (900001, "   ", "paperback", "adult", 2000, None), "title_not_blank")
expect_refused(s, "book_id is unique", BOOK,
               (1, "Copycat", "paperback", "adult", 2000, None), "UNIQUE constraint failed: books.book_id")
expect_refused(s, "ISBN-10 is unique when present", BOOK,
               (900001, "Copycat", "paperback", "adult", 2000, one("SELECT isbn10 FROM books WHERE book_id = 1")),
               "UNIQUE constraint failed: books.isbn10")
expect_refused(s, "ISBN-13 is unique when present",
               "INSERT INTO books (book_id, title, format, audience, isbn13) VALUES (?, ?, ?, ?, ?)",
               (900001, "Copycat", "paperback", "adult", one("SELECT isbn13 FROM books WHERE book_id = 1")),
               "UNIQUE constraint failed: books.isbn13")
expect_refused(s, "Year can't be in the future (new book)", BOOK,
               (900001, "From the Future", "paperback", "adult", 2999, None), "cannot be in the future")
expect_refused(s, "Year can't be in the future (changed later)",
               "UPDATE books SET publication_year = 2999 WHERE book_id = 1", (), "cannot be in the future")
expect_allowed(s, "ALLOWED: BC year, blank year, and two books with no ISBN",
               "INSERT INTO books (book_id, title, format, audience, publication_year) VALUES"
               " (900002, 'Ancient Test', 'paperback', 'adult', -720),"
               " (900003, 'Undated Test', 'paperback', 'adult', NULL)")
expect_refused(s, "Format must be hardcover, paperback, audiobook or DVD", BOOK,
               (900001, "Odd Format", "scroll", "adult", 2000, None), "valid_format")
expect_refused(s, "Audience must be adult, teen or children", BOOK,
               (900001, "Odd Audience", "paperback", "robots", 2000, None), "valid_audience")

# 2. Authors and who wrote what
s = "2 Authors"
expect_refused(s, "Author names are unique (even in different case)",
               "INSERT INTO authors (name) VALUES ('suzanne collins')", (), "UNIQUE constraint failed: authors.name")
expect_refused(s, "A book can't list the same person twice",
               "INSERT INTO book_authors VALUES (1, ?, 5)", (first_author_of_book1,),
               "UNIQUE constraint failed: book_authors.book_id, book_authors.author_id")
expect_refused(s, "Two people can't share a position on one book",
               "INSERT INTO book_authors VALUES (1, ?, 1)", (other_author,),
               "UNIQUE constraint failed: book_authors.book_id, book_authors.author_order")
expect_refused(s, "Links must point to a real book",
               "INSERT INTO book_authors VALUES (999999, 1, 1)", (), "FOREIGN KEY constraint failed")

# Every book must have an author: this is checked by build_db.py after loading.
conn.execute("SAVEPOINT t")
conn.execute(BOOK, (900004, "Nobody Wrote This", "paperback", "adult", 2000, None))
try:
    build_db.check_every_book_has_author(conn)
    report(s, "Every book must have at least one author (build check)", False, "check did NOT stop the build")
except RuntimeError as e:
    report(s, "Every book must have at least one author (build check)", True, f"build stopped: {e}")
finally:
    conn.execute("ROLLBACK TO t")
    conn.execute("RELEASE t")

# 3. Copies
s = "3 Copies"
expect_refused(s, "Every copy must belong to a book we have", COPY,
               (999999, "LIB-TEST01", "available", T, 10), "FOREIGN KEY constraint failed")
expect_refused(s, "Barcodes are unique", COPY,
               (1, "LIB-000001", "available", T, 10), "UNIQUE constraint failed: copies.barcode")
expect_refused(s, "Status must be one of the six allowed values", COPY,
               (1, "LIB-TEST01", "borrowed", T, 10), "valid_copy_status")
expect_refused(s, "Cost can't be negative", COPY,
               (1, "LIB-TEST01", "available", T, -1), "cost_not_negative")

# 4. Patrons
s = "4 Patrons"
expect_refused(s, "Every patron must have a name", *patron(name=None),
               expect="NOT NULL constraint failed: patrons.name")
expect_refused(s, "Must have email or phone (both missing)", *patron(email=None, phone=None),
               expect="patron_has_contact")
expect_refused(s, "Must have email or phone (both blank)", *patron(email="", phone="  "),
               expect="patron_has_contact")
expect_refused(s, "A child must be linked to a guardian", *patron(patron_type="child"),
               expect="child_has_guardian")
expect_refused(s, "A guardian must be a real patron", *patron(patron_type="child", guardian_id=99999),
               expect="FOREIGN KEY constraint failed")
expect_refused(s, "Card numbers are unique", *patron(card_number="CARD-0001"),
               expect="UNIQUE constraint failed: patrons.card_number")
expect_refused(s, "Type must be adult, child, senior or staff", *patron(patron_type="robot"),
               expect="valid_patron_type")
expect_refused(s, "Standing must be active, expired or blocked", *patron(standing="vip"),
               expect="valid_standing")

# 5. Loans
s = "5 Loans"
expect_refused(s, "Due date must be after checkout date", LOAN,
               (free_copies[0], adult, T, T), "due_after_checkout")
expect_refused(s, "Return date can't be before checkout date",
               "INSERT INTO loans (copy_id, patron_id, checkout_date, due_date, return_date)"
               " VALUES (?, ?, ?, ?, '2026-10-01')", (free_copies[0], adult, T, DUE),
               "return_not_before_checkout")
expect_refused(s, "A copy can't be checked out to two people at once", LOAN,
               (out_copy, adult, T, DUE), "UNIQUE constraint failed: loans.copy_id")
expect_refused(s, "A blocked patron can't borrow", LOAN,
               (free_copies[0], blocked, T, DUE), "blocked or expired")
expect_refused(s, "An expired patron can't borrow", LOAN,
               (free_copies[0], expired, T, DUE), "blocked or expired")
expect_refused(s, "A card past its expiration date can't borrow (even if marked active)", LOAN,
               (free_copies[0], adult, T, DUE), "blocked or expired",
               setup=[("UPDATE patrons SET card_expires = '2026-10-01' WHERE patron_id = ?", (adult,))])
expect_refused(s, "Unpaid fines over the blocking limit stop borrowing", LOAN,
               (free_copies[0], over_limit_active, T, DUE), "unpaid fines are over the blocking limit")
expect_refused(s, "A child can't go over the checkout limit (5)", LOAN,
               (free_copies[5], child, T, DUE), "checkout limit",
               setup=[(LOAN, (c, child, T, DUE)) for c in free_copies[:5]])
expect_refused(s, "Checkout limit comes from the policies table (adult limit set to 0)", LOAN,
               (free_copies[0], adult, T, DUE), "checkout limit",
               setup=[("UPDATE policies SET value = 0 WHERE policy_key = 'checkout_limit_adult'", ())])
expect_refused(s, "A reference-only copy can't be loaned", LOAN,
               (reference_copy, adult, T, DUE), "Reference-only")
expect_refused(s, "A damaged copy can't be loaned", LOAN,
               (damaged_copy, adult, T, DUE), "lost, damaged or retired")
expect_refused(s, "Renewals can't go over the maximum (2)",
               "UPDATE loans SET renewal_count = 3 WHERE loan_id = ?", (open_loan_id,), "maximum renewals")
expect_refused(s, "Old loans are never deleted",
               "DELETE FROM loans WHERE loan_id = 1", (), "never deleted")

# Copy status follows the loans: checked out on loan, available on return.
conn.execute("SAVEPOINT t")
cur = conn.execute(LOAN, (free_copies[0], adult, T, DUE))
after_out = one("SELECT status FROM copies WHERE copy_id = ?", free_copies[0])
conn.execute("UPDATE loans SET return_date = ? WHERE loan_id = ?", (T, cur.lastrowid))
after_back = one("SELECT status FROM copies WHERE copy_id = ?", free_copies[0])
conn.execute("ROLLBACK TO t")
conn.execute("RELEASE t")
report(s, "Copy status matches loans (out -> checked_out, back -> available)",
       (after_out, after_back) == ("checked_out", "available"),
       f"after checkout: {after_out}; after return: {after_back}")

# 6. Holds
s = "6 Holds"
waiting_patron, waiting_book = conn.execute(
    "SELECT patron_id, book_id FROM holds WHERE status = 'waiting' LIMIT 1").fetchone()
expect_refused(s, "No two active holds on the same book", HOLD,
               (waiting_book, waiting_patron, f"{T} 12:00:00", "waiting", None),
               "UNIQUE constraint failed: holds.patron_id, holds.book_id")
cancelled_patron, cancelled_book = conn.execute(
    "SELECT patron_id, book_id FROM holds WHERE status = 'cancelled' LIMIT 1").fetchone()
expect_allowed(s, "ALLOWED: a new hold after an old one was cancelled", HOLD,
               (cancelled_book, cancelled_patron, f"{T} 12:00:00", "waiting", None))
expect_refused(s, "Can't hold a book you currently have checked out", HOLD,
               (out_book, out_patron, f"{T} 12:00:00", "waiting", None), "already has this book checked out")
expect_refused(s, "Status must be one of the five allowed values", HOLD,
               (1, adult, f"{T} 12:00:00", "pending", None), "valid_hold_status")
expect_refused(s, "A ready hold must have a pickup deadline", HOLD,
               (1, adult, f"{T} 12:00:00", "ready", None), "ready_hold_has_deadline")

# 7. Fines
s = "7 Fines"
expect_refused(s, "Amount can't be negative", FINE,
               (out_patron, open_loan_id, -5, "late", T), "fine_not_negative")
expect_refused(s, "Reason must be late, lost or damaged", FINE,
               (out_patron, open_loan_id, 5, "rude", T), "valid_fine_reason")
expect_refused(s, "A fine goes to the patron who had the loan", FINE,
               (adult, open_loan_id, 5, "late", T), "patron who had the loan")

# 8. Policies
s = "8 Policies"
expected = {key for key, _, _ in build_db.POLICIES}
stored = {r[0] for r in conn.execute("SELECT policy_key FROM policies")}
report(s, "Every setting is stored in the policies table", stored == expected,
       f"{len(stored)} settings stored" + ("" if stored == expected else f"; missing {expected - stored}"))

passed = sum(results)
print(f"\n{passed} of {len(results)} passed, {len(results) - passed} failed")
sys.exit(0 if passed == len(results) else 1)
