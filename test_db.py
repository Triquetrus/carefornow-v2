from sqlalchemy import create_engine, text

# Paste your EXACT connection string here
DATABASE_URL = "postgresql://postgres:YOUR_PASSWORD@aws-1-ap-south-1.pooler.supabase.com:5432/postgres?sslmode=require"

try:
    engine = create_engine(DATABASE_URL)
    with engine.connect() as conn:
        result = conn.execute(text("SELECT 1"))
        print("✅ Connected to Supabase successfully!")
except Exception as e:
    print("❌ Connection failed:")
    print(e)