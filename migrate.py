"""
One-time migration script.
Run once: python migrate.py
Safe to run multiple times — uses IF NOT EXISTS / checks before altering.
"""
import psycopg2

SUPABASE_URI = "postgresql://postgres.ixvgwrgggedzurleeucv:CareForNow2026@aws-1-ap-south-1.pooler.supabase.com:5432/postgres"

migrations = [
    # 1. Add amount_received to cases table
    """
    ALTER TABLE cases
    ADD COLUMN IF NOT EXISTS amount_received INTEGER NOT NULL DEFAULT 0;
    """,

    # 2. Create case_documents table
    """
    CREATE TABLE IF NOT EXISTS case_documents (
        id            VARCHAR(50)  PRIMARY KEY,
        case_id       VARCHAR(50)  NOT NULL REFERENCES cases(id),
        user_id       VARCHAR(50)  NOT NULL REFERENCES users(id),
        doc_type      VARCHAR(100) NOT NULL,
        file_path     VARCHAR(500) NOT NULL,
        original_name VARCHAR(300),
        uploaded_at   TIMESTAMP DEFAULT NOW()
    );
    """,

    # 3. Create funder_profiles table
    """
    CREATE TABLE IF NOT EXISTS funder_profiles (
        id                VARCHAR(50)  PRIMARY KEY,
        user_id           VARCHAR(50)  NOT NULL UNIQUE REFERENCES users(id),
        organization_name VARCHAR(200) NOT NULL,
        location          VARCHAR(200),
        total_funds       BIGINT NOT NULL DEFAULT 0,
        remaining_funds   BIGINT NOT NULL DEFAULT 0,
        created_at        TIMESTAMP DEFAULT NOW(),
        updated_at        TIMESTAMP DEFAULT NOW()
    );
    """,

    # 4. Create fund_allocations table
    """
    CREATE TABLE IF NOT EXISTS fund_allocations (
        id                VARCHAR(50) PRIMARY KEY,
        funder_profile_id VARCHAR(50) NOT NULL REFERENCES funder_profiles(id),
        case_id           VARCHAR(50) NOT NULL REFERENCES cases(id),
        amount            BIGINT NOT NULL,
        note              TEXT,
        allocated_at      TIMESTAMP DEFAULT NOW()
    );
    """,
]

def run():
    conn = psycopg2.connect(SUPABASE_URI)
    conn.autocommit = True
    cur = conn.cursor()

    for i, sql in enumerate(migrations, 1):
        try:
            cur.execute(sql)
            print(f"[{i}] OK")
        except Exception as e:
            print(f"[{i}] SKIP / ERROR: {e}")

    cur.close()
    conn.close()
    print("\nMigration complete. You can now run the app.")

if __name__ == '__main__':
    run()
