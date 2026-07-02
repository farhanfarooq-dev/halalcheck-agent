"""SQLite database setup for the AI HalalCheck Agent project."""

from __future__ import annotations

import csv
import hashlib
import re
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Iterable


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "halalcheck.db"
INGREDIENT_RULES_CSV = DATA_DIR / "ingredient_rules.csv"
SAMPLE_PRODUCTS_CSV = DATA_DIR / "sample_products.csv"


SCHEMA_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        barcode TEXT UNIQUE,
        name TEXT NOT NULL,
        brand TEXT,
        ingredients TEXT,
        manual_product_hash TEXT,
        manufacturer_email TEXT,
        source TEXT NOT NULL DEFAULT 'manual',
        official_certificate_available INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS ingredient_rules (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        term TEXT NOT NULL UNIQUE,
        language TEXT NOT NULL DEFAULT 'both',
        category TEXT NOT NULL,
        halal_classification TEXT NOT NULL,
        explanation_en TEXT NOT NULL,
        explanation_de TEXT NOT NULL,
        source_required INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS product_checks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id INTEGER NOT NULL,
        user_email TEXT,
        language TEXT NOT NULL DEFAULT 'en',
        final_status TEXT NOT NULL,
        result_source TEXT,
        explanation TEXT,
        detected_concerns_json TEXT NOT NULL DEFAULT '[]',
        checked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (product_id) REFERENCES products (id)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS manufacturer_inquiries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id INTEGER NOT NULL,
        ingredient_term TEXT NOT NULL,
        requested_ingredients_json TEXT,
        manufacturer_email TEXT,
        verified_manufacturer_email TEXT,
        email_status TEXT NOT NULL DEFAULT 'draft',
        gmail_message_id TEXT,
        gmail_thread_id TEXT,
        reply_received_at TEXT,
        send_error TEXT,
        email_subject TEXT NOT NULL,
        email_body TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'draft',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        sent_at TEXT,
        FOREIGN KEY (product_id) REFERENCES products (id)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS manufacturer_contacts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        brand TEXT,
        product_id INTEGER,
        email TEXT NOT NULL,
        verification_status TEXT NOT NULL DEFAULT 'needs human verification',
        source TEXT NOT NULL DEFAULT 'human',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (product_id) REFERENCES products (id)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS manufacturer_responses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        inquiry_id INTEGER NOT NULL,
        response_text TEXT NOT NULL,
        analyzed_status TEXT NOT NULL,
        analysis_notes TEXT,
        ingredients_text TEXT,
        doubtful_ingredient TEXT,
        confirmed_ingredients_json TEXT,
        unresolved_ingredients_json TEXT,
        verification_source TEXT NOT NULL DEFAULT 'manufacturer_response',
        response_date TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        verification_expiry_date TEXT,
        recheck_required INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (inquiry_id) REFERENCES manufacturer_inquiries (id)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS user_notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id INTEGER NOT NULL,
        user_email TEXT NOT NULL,
        subject TEXT NOT NULL,
        message TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'draft',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        sent_at TEXT,
        FOREIGN KEY (product_id) REFERENCES products (id)
    );
    """,
)


def get_connection(db_path: Path = DB_PATH) -> sqlite3.Connection:
    """Return a SQLite connection with foreign-key checks enabled."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON;")
    return connection


def create_tables(connection: sqlite3.Connection) -> None:
    """Create all database tables required by the MVP."""
    for statement in SCHEMA_STATEMENTS:
        connection.execute(statement)
    _add_missing_columns(connection)
    connection.commit()


def _add_missing_columns(connection: sqlite3.Connection) -> None:
    """Add new columns when an existing SQLite database is upgraded."""
    product_columns = {
        row["name"] for row in connection.execute("PRAGMA table_info(products);")
    }
    if "manual_product_hash" not in product_columns:
        connection.execute("ALTER TABLE products ADD COLUMN manual_product_hash TEXT;")

    check_columns = {
        row["name"] for row in connection.execute("PRAGMA table_info(product_checks);")
    }
    if "result_source" not in check_columns:
        connection.execute("ALTER TABLE product_checks ADD COLUMN result_source TEXT;")

    inquiry_columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(manufacturer_inquiries);")
    }
    inquiry_columns_to_add = {
        "requested_ingredients_json": "TEXT",
        "verified_manufacturer_email": "TEXT",
        "email_status": "TEXT NOT NULL DEFAULT 'draft'",
        "gmail_message_id": "TEXT",
        "gmail_thread_id": "TEXT",
        "reply_received_at": "TEXT",
        "send_error": "TEXT",
    }
    for column_name, column_type in inquiry_columns_to_add.items():
        if column_name not in inquiry_columns:
            connection.execute(
                f"ALTER TABLE manufacturer_inquiries ADD COLUMN {column_name} {column_type};"
            )

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS manufacturer_contacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            brand TEXT,
            product_id INTEGER,
            email TEXT NOT NULL,
            verification_status TEXT NOT NULL DEFAULT 'needs human verification',
            source TEXT NOT NULL DEFAULT 'human',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (product_id) REFERENCES products (id)
        );
        """
    )

    response_columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(manufacturer_responses);")
    }
    columns_to_add = {
        "ingredients_text": "TEXT",
        "doubtful_ingredient": "TEXT",
        "confirmed_ingredients_json": "TEXT",
        "unresolved_ingredients_json": "TEXT",
        "verification_source": "TEXT NOT NULL DEFAULT 'manufacturer_response'",
        "response_date": "TEXT",
        "verification_expiry_date": "TEXT",
        "recheck_required": "INTEGER NOT NULL DEFAULT 0",
    }
    for column_name, column_type in columns_to_add.items():
        if column_name not in response_columns:
            connection.execute(
                f"ALTER TABLE manufacturer_responses ADD COLUMN {column_name} {column_type};"
            )
    _backfill_manual_product_hashes(connection)



def _backfill_manual_product_hashes(connection: sqlite3.Connection) -> None:
    """Populate stable manual identities for existing rows."""
    rows = connection.execute(
        """
        SELECT id, name, brand, ingredients
        FROM products
        WHERE manual_product_hash IS NULL OR manual_product_hash = '';
        """
    ).fetchall()
    for row in rows:
        connection.execute(
            "UPDATE products SET manual_product_hash = ? WHERE id = ?;",
            (
                _manual_product_hash(
                    str(row["name"] or "Manual product"),
                    str(row["brand"] or ""),
                    str(row["ingredients"] or ""),
                ),
                row["id"],
            ),
        )


def _manual_product_hash(product_name: str, brand: str, ingredients: str) -> str:
    identity = "|".join(
        [
            _normalize_text(product_name),
            _normalize_text(brand),
            _normalize_text(ingredients),
        ]
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())

def seed_ingredient_rules(connection: sqlite3.Connection) -> None:
    """Load ingredient rules from CSV into SQLite if the table is empty."""
    existing_count = connection.execute(
        "SELECT COUNT(*) FROM ingredient_rules;"
    ).fetchone()[0]
    if existing_count > 0 or not INGREDIENT_RULES_CSV.exists():
        return

    with INGREDIENT_RULES_CSV.open("r", encoding="utf-8", newline="") as file:
        rows = csv.DictReader(file)
        connection.executemany(
            """
            INSERT INTO ingredient_rules (
                term,
                language,
                category,
                halal_classification,
                explanation_en,
                explanation_de,
                source_required
            )
            VALUES (
                :term,
                :language,
                :category,
                :halal_classification,
                :explanation_en,
                :explanation_de,
                :source_required
            );
            """,
            _normalize_rule_rows(rows),
        )
    connection.commit()


def seed_sample_products(connection: sqlite3.Connection) -> None:
    """Load demo products from CSV into SQLite if no products exist."""
    existing_count = connection.execute("SELECT COUNT(*) FROM products;").fetchone()[0]
    if existing_count > 0 or not SAMPLE_PRODUCTS_CSV.exists():
        return

    with SAMPLE_PRODUCTS_CSV.open("r", encoding="utf-8", newline="") as file:
        rows = csv.DictReader(file)
        connection.executemany(
            """
            INSERT INTO products (
                barcode,
                name,
                brand,
                ingredients,
                manufacturer_email,
                source,
                official_certificate_available
            )
            VALUES (
                :barcode,
                :name,
                :brand,
                :ingredients,
                :manufacturer_email,
                'sample',
                :official_certificate_available
            );
            """,
            _normalize_product_rows(rows),
        )
    connection.commit()


def _normalize_rule_rows(rows: Iterable[dict[str, str]]) -> list[dict[str, object]]:
    normalized_rows: list[dict[str, object]] = []
    for row in rows:
        normalized_rows.append(
            {
                **row,
                "source_required": int(row.get("source_required", "0") or 0),
            }
        )
    return normalized_rows


def _normalize_product_rows(rows: Iterable[dict[str, str]]) -> list[dict[str, object]]:
    normalized_rows: list[dict[str, object]] = []
    for row in rows:
        normalized_rows.append(
            {
                **row,
                "official_certificate_available": int(
                    row.get("official_certificate_available", "0") or 0
                ),
            }
        )
    return normalized_rows


def initialize_database(db_path: Path = DB_PATH) -> Path:
    """Create the database and seed starter data."""
    with closing(get_connection(db_path)) as connection:
        create_tables(connection)
        seed_ingredient_rules(connection)
        seed_sample_products(connection)
        _backfill_manual_product_hashes(connection)
        connection.commit()
    return db_path


if __name__ == "__main__":
    created_path = initialize_database()
    print(f"Database initialized at: {created_path}")
