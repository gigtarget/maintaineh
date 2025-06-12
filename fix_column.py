import psycopg2

# Connect to your Railway PostgreSQL database
conn = psycopg2.connect(
    "postgresql://postgres:qysDdiSHdtDRcByOqfSElMsFeriKGjeB@shuttle.proxy.rlwy.net:55090/railway"
)

cur = conn.cursor()

# Drop the old column (if it exists)
cur.execute("ALTER TABLE servicelog DROP COLUMN IF EXISTS warranty_till;")

# Add a new warranty_till column with DATE type
cur.execute("ALTER TABLE servicelog ADD COLUMN warranty_till DATE;")

conn.commit()
cur.close()
conn.close()

print("✅ warranty_till column fixed successfully!")
