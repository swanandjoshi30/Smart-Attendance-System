import time
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

print("Importing modules...")
from ai_agent import ChatMemoryManager, get_sql_db
print("Imports finished successfully!")

t0 = time.time()
print("Initializing ChatMemoryManager (which connects/pings Redis)...", end="", flush=True)
manager = ChatMemoryManager()
print(f" done ({time.time() - t0:.2f}s)", flush=True)

t0 = time.time()
print("Connecting to SQL Database via get_sql_db()...", end="", flush=True)
db = get_sql_db()
print(f" done ({time.time() - t0:.2f}s)", flush=True)

t0 = time.time()
print("Getting usable table names...", end="", flush=True)
tables = db.get_usable_table_names()
print(f" done ({time.time() - t0:.2f}s) -> Tables: {tables}", flush=True)

print("Diagnostic script finished!")
