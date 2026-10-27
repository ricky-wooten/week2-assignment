-- queries.sql: a typical day at the library, one query (or small group) per question.
--
-- "Today" is fixed at '2026-10-26' to match the sample data. For real daily use,
-- replace '2026-10-26' with date('now').
--
-- Some of these change data (sign-ups, checkouts, returns). To try them without
-- changing library.db, run them on a copy:
--   cp library.db practice.db && sqlite3 -header -column practice.db < queries.sql

PRAGMA foreign_keys = ON;   -- turn on the "must point to something real" rules for this session


-- Q1. Someone signs up for a card.
INSERT INTO patrons (name, card_number, email, phone, address, patron_type,
                     joined_date, card_expires)
VALUES ('Nova Newcard', 'CARD-0031', 'nova.newcard@example.com', '615-555-0131',
        '131 Example Street, Sampletown', 'adult', '2026-10-26', '2029-10-26');

SELECT name, card_number, patron_type, standing, card_expires
FROM patrons WHERE card_number = 'CARD-0031';


-- Q2. Someone checks out three books (scanned barcodes), respecting every rule.
-- The due date comes from the policies table based on each item's format, and the
-- triggers check the patron's standing, fines and checkout limit, and that no copy
-- is already out or reference-only. If any rule is broken, none of the three go out.
INSERT INTO loans (copy_id, patron_id, checkout_date, due_date)
SELECT c.copy_id, p.patron_id, '2026-10-26',
       date('2026-10-26', '+' || CAST(pol.value AS INTEGER) || ' days')
FROM copies c
JOIN books b    ON b.book_id = c.book_id
JOIN policies pol ON pol.policy_key = CASE b.format
                                          WHEN 'DVD'       THEN 'loan_days_dvd'
                                          WHEN 'audiobook' THEN 'loan_days_audiobook'
                                          ELSE 'loan_days_book'
                                      END
JOIN patrons p  ON p.card_number = 'CARD-0031'
WHERE c.barcode IN ('LIB-000004', 'LIB-000034', 'LIB-000043');

SELECT c.barcode, b.title, b.format, l.checkout_date, l.due_date, c.status
FROM loans l
JOIN copies c  ON c.copy_id = l.copy_id
JOIN books b   ON b.book_id = c.book_id
JOIN patrons p ON p.patron_id = l.patron_id
WHERE p.card_number = 'CARD-0031'
ORDER BY l.due_date;


-- Q3. Someone returns a book, and someone else was waiting for it: who's next?
-- Step 1: check the copy in (the copy's status flips back to available automatically).
UPDATE loans SET return_date = '2026-10-26'
WHERE return_date IS NULL
  AND copy_id = (SELECT copy_id FROM copies WHERE barcode = 'LIB-000001');

-- Step 2: who's next in the queue? (earliest waiting hold on that book)
SELECT p.name, p.card_number, p.email, p.phone, h.placed_at
FROM holds h
JOIN patrons p ON p.patron_id = h.patron_id
WHERE h.book_id = (SELECT book_id FROM copies WHERE barcode = 'LIB-000001')
  AND h.status = 'waiting'
ORDER BY h.placed_at, h.hold_id
LIMIT 1;

-- Step 3: set the copy aside for them, with a pickup deadline from the policies table.
UPDATE holds
SET status = 'ready',
    pickup_deadline = date('2026-10-26', '+' ||
        (SELECT CAST(value AS INTEGER) FROM policies WHERE policy_key = 'hold_pickup_days') || ' days')
WHERE hold_id = (SELECT hold_id FROM holds
                 WHERE book_id = (SELECT book_id FROM copies WHERE barcode = 'LIB-000001')
                   AND status = 'waiting'
                 ORDER BY placed_at, hold_id
                 LIMIT 1);
UPDATE copies SET status = 'on_hold_shelf' WHERE barcode = 'LIB-000001';


-- Q4. "Do you have anything by Stephen King, and is it in?"
-- Titles we own, with how many copies can go home today.
SELECT b.title,
       count(c.copy_id) AS copies_owned,
       sum(c.status = 'available' AND c.is_reference = 0) AS available_now
FROM authors a
JOIN book_authors ba ON ba.author_id = a.author_id
JOIN books b         ON b.book_id = ba.book_id
JOIN copies c        ON c.book_id = b.book_id
WHERE a.name = 'Stephen King'
GROUP BY b.book_id
ORDER BY available_now DESC, b.title;


-- Q5. At closing: everything overdue, with patron name, contact, title and days late.
-- copy_status shows 'lost' for items more than 45 days late that were written off.
SELECT p.name, p.email, p.phone, b.title, c.barcode, l.due_date,
       CAST(julianday('2026-10-26') - julianday(l.due_date) AS INTEGER) AS days_late,
       c.status AS copy_status
FROM loans l
JOIN copies c  ON c.copy_id = l.copy_id
JOIN books b   ON b.book_id = c.book_id
JOIN patrons p ON p.patron_id = l.patron_id
WHERE l.return_date IS NULL
  AND l.due_date < '2026-10-26'
ORDER BY days_late DESC;


-- Q6. A new shipment arrives: two more copies of Harry Potter and the Sorcerer's Stone
-- (book_id 2). Each new barcode is the next number after the highest one in use.
INSERT INTO copies (book_id, barcode, acquired_date, cost)
SELECT 2, printf('LIB-%06d', max(CAST(substr(barcode, 5) AS INTEGER)) + 1), '2026-10-26', 12.99
FROM copies;
INSERT INTO copies (book_id, barcode, acquired_date, cost)
SELECT 2, printf('LIB-%06d', max(CAST(substr(barcode, 5) AS INTEGER)) + 1), '2026-10-26', 12.99
FROM copies;

SELECT barcode, status, acquired_date, cost FROM copies WHERE book_id = 2 ORDER BY barcode;


-- Q7. A book comes back with a torn cover: check it in, then mark the copy damaged.
-- (A damaged copy can no longer be loaned. To charge for it, add a fine with reason 'damaged'.)
UPDATE loans SET return_date = '2026-10-26'
WHERE return_date IS NULL
  AND copy_id = (SELECT copy_id FROM copies WHERE barcode = 'LIB-000031');
UPDATE copies SET status = 'damaged' WHERE barcode = 'LIB-000031';

SELECT c.barcode, b.title, c.status
FROM copies c JOIN books b ON b.book_id = c.book_id
WHERE c.barcode = 'LIB-000031';


-- Q8. Someone asks how much they owe (card CARD-0008): total, then the details.
SELECT p.name, p.standing,
       count(f.fine_id) AS unpaid_fines,
       coalesce(sum(f.amount), 0) AS amount_owed
FROM patrons p
LEFT JOIN fines f ON f.patron_id = p.patron_id AND f.paid_date IS NULL
WHERE p.card_number = 'CARD-0008'
GROUP BY p.patron_id;

SELECT f.reason, b.title, f.charged_date, f.amount
FROM fines f
JOIN patrons p ON p.patron_id = f.patron_id
JOIN loans l   ON l.loan_id = f.loan_id
JOIN copies c  ON c.copy_id = l.copy_id
JOIN books b   ON b.book_id = c.book_id
WHERE p.card_number = 'CARD-0008' AND f.paid_date IS NULL
ORDER BY f.charged_date;


-- Q9. Our 10 most-borrowed books (all loans ever, returned or not).
SELECT b.title, count(*) AS times_borrowed
FROM loans l
JOIN copies c ON c.copy_id = l.copy_id
JOIN books b  ON b.book_id = c.book_id
GROUP BY b.book_id
ORDER BY times_borrowed DESC, b.title
LIMIT 10;
