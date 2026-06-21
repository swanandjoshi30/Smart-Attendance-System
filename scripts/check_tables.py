import psycopg2
from attendance_config import DB_CONFIG

def main():
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public'")
    tables = cur.fetchall()
    print("Tables in Database:")
    for t in tables:
        print(f" - {t[0]}")
    conn.close()

if __name__ == '__main__':
    main()
