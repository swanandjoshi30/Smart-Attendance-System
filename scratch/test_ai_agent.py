# scratch/test_ai_agent.py
"""
Automated unit and integration test suite for the Conversational AI Interface.
Runs verification on DB access, caching fallback, and agent routing logic.
"""

import sys
import os
import unittest
from datetime import datetime

# Adjust Python Path to find local project modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from ai_agent import ChatMemoryManager, get_sql_db, query_attendance_ai, get_llm

class TestConversationalAI(unittest.TestCase):

    def setUp(self):
        self.session_id = "test_verification_session_123"

    def test_01_memory_manager_fallback(self):
        """Verify memory cache fallback works when Redis is down or unavailable."""
        print("\n[TEST] Verifying Chat Memory Manager...")
        manager = ChatMemoryManager()
        
        # Ensure we can add messages
        manager.add_message(self.session_id, "user", "Was Atharva present yesterday?")
        manager.add_message(self.session_id, "assistant", "Yes, Atharva was marked present.")

        # Ensure we retrieve them in correct order
        history = manager.get_chat_history(self.session_id)
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["role"], "user")
        self.assertEqual(history[0]["content"], "Was Atharva present yesterday?")
        self.assertEqual(history[1]["role"], "assistant")
        self.assertEqual(history[1]["content"], "Yes, Atharva was marked present.")

        # Clear memory and assert empty
        manager.clear_history(self.session_id)
        history_after = manager.get_chat_history(self.session_id)
        self.assertEqual(len(history_after), 0)
        print("[OK] Chat Memory Manager caching verified successfully.")

    def test_02_database_connection(self):
        """Verify SQLAlchemy whitelisted DB connection reads from local tables."""
        print("\n[TEST] Verifying SQLAlchemy Database Connection...")
        try:
            db = get_sql_db()
            
            # Verify tables list (should be lowercase in postgres)
            usable_tables = db.get_usable_table_names()
            print(f" Usable Tables detected: {usable_tables}")
            
            # Assert some expected tables exist
            self.assertTrue("students" in usable_tables)
            self.assertTrue("classes" in usable_tables)
            self.assertTrue("subjects" in usable_tables)
            self.assertTrue("attendancelog" in usable_tables)
            
            # Assert users and faceencodings tables are hidden/excluded
            self.assertFalse("users" in usable_tables)
            self.assertFalse("faceencodings" in usable_tables)
            
            # Perform a test SELECT query on class count
            res = db.run("SELECT COUNT(*) FROM classes;")
            print(f" Test query output: {res}")
            self.assertTrue(len(res) > 0)
            print("[OK] SQLAlchemy whitelist connection verified successfully.")
        except Exception as e:
            self.fail(f"Database connection query failed: {e}")

    def test_03_llm_auto_selection(self):
        """Verify LLM selection handles empty environment variables gracefully without crashing."""
        print("\n[TEST] Verifying LLM selection behavior...")
        llm = get_llm()
        if llm is None:
            print(" No API keys configured in environment (normal for local bootstrap). Asserting query safety warning...")
            # Query agent and assert it returns the config guidance warning string
            res = query_attendance_ai("Was Atharva present yesterday?", self.session_id)
            self.assertIn("LLM API credentials are not configured", res)
        else:
            print(f" LLM Initialized: {llm.__class__.__name__}")
        print("[OK] LLM selection checks completed successfully.")

if __name__ == '__main__':
    unittest.main()
