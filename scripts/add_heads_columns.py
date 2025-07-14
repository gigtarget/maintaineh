import os
from sqlalchemy import create_engine, text

DATABASE_URL = os.getenv('DATABASE_URL')
if not DATABASE_URL:
    raise SystemExit('DATABASE_URL environment variable not set')


def main():
    engine = create_engine(DATABASE_URL)
    with engine.begin() as conn:
        conn.execute(text('ALTER TABLE machine ADD COLUMN IF NOT EXISTS num_heads INTEGER DEFAULT 8'))
        conn.execute(text('ALTER TABLE machine ADD COLUMN IF NOT EXISTS needles_per_head INTEGER DEFAULT 15'))
    print('num_heads and needles_per_head columns added.')


if __name__ == '__main__':
    main()
