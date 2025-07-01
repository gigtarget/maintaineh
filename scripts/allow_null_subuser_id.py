import os
from sqlalchemy import create_engine, text

DATABASE_URL = os.getenv('DATABASE_URL')
if not DATABASE_URL:
    raise SystemExit('DATABASE_URL environment variable not set')

def main():
    engine = create_engine(DATABASE_URL)
    with engine.begin() as conn:
        conn.execute(text('ALTER TABLE sub_user_action ALTER COLUMN subuser_id DROP NOT NULL;'))
    print('sub_user_action.subuser_id column altered to allow NULL values')

if __name__ == '__main__':
    main()
