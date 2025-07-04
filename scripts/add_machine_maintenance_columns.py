import os
from sqlalchemy import create_engine, text

DATABASE_URL = os.getenv('DATABASE_URL')
if not DATABASE_URL:
    raise SystemExit('DATABASE_URL environment variable not set')


def main():
    engine = create_engine(DATABASE_URL)
    with engine.begin() as conn:
        conn.execute(
            text(
                "ALTER TABLE machine ADD COLUMN IF NOT EXISTS oil_interval_hours INTEGER DEFAULT 24;"
            )
        )
        print("oil_interval_hours column added or already exists")

        conn.execute(
            text(
                "ALTER TABLE machine ADD COLUMN IF NOT EXISTS lube_interval_days INTEGER DEFAULT 7;"
            )
        )
        print("lube_interval_days column added or already exists")

        conn.execute(
            text(
                "ALTER TABLE machine ADD COLUMN IF NOT EXISTS grease_interval_months INTEGER DEFAULT 3;"
            )
        )
        print("grease_interval_months column added or already exists")


if __name__ == "__main__":
    main()
