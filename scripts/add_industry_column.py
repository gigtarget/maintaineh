import os
from sqlalchemy import create_engine, text

DATABASE_URL = os.getenv('DATABASE_URL')
if not DATABASE_URL:
    raise SystemExit('DATABASE_URL environment variable not set')


def main():
    engine = create_engine(DATABASE_URL)
    with engine.begin() as conn:
        conn.execute(text('ALTER TABLE "user" ADD COLUMN IF NOT EXISTS industry VARCHAR(100)'))
    print('industry column added to user table')


if __name__ == '__main__':
    main()
