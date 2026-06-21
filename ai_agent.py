# ai_agent.py
"""
LangChain SQL Database Agent configuration for Smart Attendance System.
Handles natural language queries to database and manages conversation memory.
"""

import os
import threading
import json
from datetime import datetime, timedelta
import calendar
import urllib.parse
from dotenv import load_dotenv

# Database and LangChain imports
from sqlalchemy import create_engine
from langchain_community.utilities import SQLDatabase
from langchain_community.agent_toolkits import create_sql_agent
from langchain_community.agent_toolkits.sql.toolkit import SQLDatabaseToolkit

# Configure environment
load_dotenv()

# =========================================================================
# 1. REDIS & IN-MEMORY CACHE FOR CONVERSATIONAL MEMORY
# =========================================================================
class ChatMemoryManager:
    """Manages chat conversation session cache using Redis or In-Memory fallback."""
    def __init__(self):
        self.redis_client = None
        self.is_redis_connected = False
        self.in_memory_db = {}
        self.lock = threading.Lock()

        # Redis connection configuration
        redis_host = os.getenv("REDIS_HOST", "localhost")
        redis_port = int(os.getenv("REDIS_PORT", "6379"))
        redis_password = os.getenv("REDIS_PASSWORD", None)

        try:
            import redis
            self.redis_client = redis.Redis(
                host=redis_host,
                port=redis_port,
                password=redis_password,
                socket_timeout=0.2,
                socket_connect_timeout=0.2,
                decode_responses=True
            )
            # Ping Redis to test connection
            self.redis_client.ping()
            self.is_redis_connected = True
            print("[OK] Connected to Redis server for AI chat memory caching.")
        except Exception as e:
            print(f"[WARN] Local Redis is offline or not installed ({e}). Falling back to thread-safe in-memory cache.")
            self.redis_client = None

    def get_chat_history(self, session_id: str, limit: int = 10) -> list:
        """Retrieve last N messages from memory store."""
        if self.is_redis_connected and self.redis_client:
            try:
                key = f"chat_session:{session_id}"
                messages_json = self.redis_client.lrange(key, -limit, -1)
                return [json.loads(msg) for msg in messages_json]
            except Exception as e:
                print(f"[ERROR] Redis read failure ({e}). Falling back to in-memory store.")
        
        with self.lock:
            history = self.in_memory_db.get(session_id, [])
            return history[-limit:]

    def add_message(self, session_id: str, role: str, content: str):
        """Append message to session chat history."""
        message = {"role": role, "content": content}
        if self.is_redis_connected and self.redis_client:
            try:
                key = f"chat_session:{session_id}"
                self.redis_client.rpush(key, json.dumps(message))
                self.redis_client.expire(key, 86400)  # TTL of 24 hours
                return
            except Exception as e:
                print(f"[ERROR] Redis write failure ({e}). Falling back to in-memory store.")
        
        with self.lock:
            if session_id not in self.in_memory_db:
                self.in_memory_db[session_id] = []
            self.in_memory_db[session_id].append(message)

    def clear_history(self, session_id: str):
        """Clear conversation history for a session."""
        if self.is_redis_connected and self.redis_client:
            try:
                key = f"chat_session:{session_id}"
                self.redis_client.delete(key)
                return
            except Exception as e:
                print(f"[ERROR] Redis delete failure ({e}). Clearing in-memory.")
        
        with self.lock:
            if session_id in self.in_memory_db:
                self.in_memory_db[session_id] = []


# Initialize global memory cache
memory_manager = ChatMemoryManager()

# =========================================================================
# 2. LLM INITIALIZATION AND AUTO-SELECTION
# =========================================================================
def get_llm():
    """Initializes the chat model based on credentials configured in .env."""
    # 1. Anthropic Claude (Sonnet 3.5)
    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    if anthropic_key and anthropic_key.strip():
        try:
            from langchain_anthropic import ChatAnthropic
            return ChatAnthropic(
                model="claude-3-5-sonnet-20241022",
                temperature=0.0,
                api_key=anthropic_key
            )
        except Exception as e:
            print(f"[ERROR] Failed to load ChatAnthropic: {e}")

    # 2. OpenAI GPT-4o
    openai_key = os.getenv("OPENAI_API_KEY")
    if openai_key and openai_key.strip():
        try:
            from langchain_openai import ChatOpenAI
            return ChatOpenAI(
                model="gpt-4o",
                temperature=0.0,
                api_key=openai_key
            )
        except Exception as e:
            print(f"[ERROR] Failed to load ChatOpenAI: {e}")

    # 3. Google Gemini (via Google GenAI)
    google_key = os.getenv("GOOGLE_API_KEY")
    if google_key and google_key.strip():
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI
            return ChatGoogleGenerativeAI(
                model="gemini-1.5-pro",
                temperature=0.0,
                api_key=google_key
            )
        except Exception as e:
            print(f"[ERROR] Failed to load ChatGoogleGenerativeAI: {e}")

    return None

# =========================================================================
# 3. DATABASE CONNECTION & SQL ENGINE
# =========================================================================
def get_sql_db():
    """Builds a SQLAlchemy engine and returns a whitelisted SQLDatabase instance."""
    from attendance_config import DB_CONFIG
    
    user = DB_CONFIG['user']
    password = DB_CONFIG['password']
    host = DB_CONFIG['host']
    port = DB_CONFIG.get('port', 5432)
    database = DB_CONFIG['database']

    # URL escape password if it contains special characters
    escaped_password = urllib.parse.quote_plus(password)
    db_uri = f"postgresql+psycopg2://{user}:{escaped_password}@{host}:{port}/{database}"

    engine = create_engine(db_uri)
    
    # We restrict table access strictly to safe tables (hiding Users & FaceEncodings)
    db = SQLDatabase(
        engine,
        include_tables=[
            'classes', 
            'students', 
            'sessions', 
            'subjects', 
            'sessiondetections', 
            'attendancelog', 
            'cameras'
        ]
    )
    return db

# =========================================================================
# 4. CONVERSATIONAL AI QUERY EXECUTOR
# =========================================================================
def query_attendance_ai(user_message: str, session_id: str = "default_session") -> str:
    """
    Main interface function. Fetches session logs, builds dynamic system prompt,
    initializes the LangChain agent executor, queries the DB, saves memory logs, and returns the result.
    """
    llm = get_llm()
    if not llm:
        return (
            "LLM API credentials are not configured. Please add `OPENAI_API_KEY`, "
            "`ANTHROPIC_API_KEY`, or `GOOGLE_API_KEY` in your `.env` file to activate "
            "the Conversational AI Assistant."
        )

    # 1. Fetch chat history context
    history = memory_manager.get_chat_history(session_id, limit=10)
    history_str = ""
    if history:
        history_str = "\n".join([f"{msg['role'].capitalize()}: {msg['content']}" for msg in history])
    else:
        history_str = "No conversation history yet."

    # 2. Get dynamic date constraints
    now = datetime.now()
    day_of_week = calendar.day_name[now.weekday()]
    current_date = now.strftime("%Y-%m-%d")
    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")

    # 3. Formulate system guidelines prompt
    instructions = f"""You are a helpful SQL database assistant. Your goal is to answer questions about student attendance, classes, subjects, and cameras by generating SQL queries for the PostgreSQL database.

Current date/time: {now.strftime('%Y-%m-%d %H:%M:%S')} (Today is {day_of_week})

CRITICAL SCHEMA GUIDELINES:
- classes (class_id SERIAL PK, class_name VARCHAR UNIQUE)
- subjects (subject_id SERIAL PK, subject_name VARCHAR UNIQUE, subject_code VARCHAR UNIQUE, semester INTEGER)
- students (prn_no VARCHAR PK, class_id REFERENCES classes, roll_no INTEGER, name VARCHAR, email VARCHAR)
- sessions (session_id SERIAL PK, class_id REFERENCES classes, subject_id REFERENCES subjects, start_time TIMESTAMP, end_time TIMESTAMP, status VARCHAR)
- sessiondetections (detection_id SERIAL PK, session_id REFERENCES sessions, prn_no REFERENCES students, timestamp TIMESTAMP)
- attendancelog (log_id SERIAL PK, prn_no REFERENCES students, subject_id REFERENCES subjects, session_id REFERENCES sessions, timestamp TIMESTAMP, presence_percentage FLOAT, status VARCHAR)
- cameras (camera_id SERIAL PK, camera_name VARCHAR UNIQUE, rtsp_url VARCHAR, direction VARCHAR)

RULES FOR QUERY EXECUTION:
1. ONLY query the tables listed above. Do NOT query 'users' or 'faceencodings'.
2. All generated SQL statements MUST be strictly READ-ONLY SELECT queries.
3. Use case-insensitive matches (ILIKE) and wildcards (%) for student, subject, or class names to handle user typos (e.g. `s.name ILIKE '%Atharva%'`).
4. To check presence status: Use the 'attendancelog' table. If status is 'present' they were present; if 'absent' they were absent.
5. Relative dates:
   - Today is {current_date}.
   - Yesterday is {yesterday}.
   - E.g. For "yesterday", write SQL query referencing `DATE(timestamp) = '{yesterday}'` or `timestamp::date = '{yesterday}'`.
6. To list students in a class: join students with classes using class_id.
7. Keep responses concise, friendly, and natural. If a query returns tabular information (like a list of students or cameras), format it as a markdown table.
8. If the search returns no records, state that clearly instead of generating an empty table.
9. Refer to the conversation history below to resolve pronouns (e.g., "Was he present?" should refer to the student name in the previous query).

CONVERSATION HISTORY FOR CONTEXT:
{history_str}
"""

    # 4. Create SQL database wrapper & toolkit
    try:
        db = get_sql_db()
        toolkit = SQLDatabaseToolkit(db=db, llm=llm)

        # 5. Build agent executor. We use tool-calling or zero-shot-react-description if tool-calling is unsupported.
        try:
            agent_executor = create_sql_agent(
                llm=llm,
                toolkit=toolkit,
                db=db,
                agent_type="tool-calling",
                verbose=False,
                system_message=instructions
            )
        except Exception:
            # Fallback to standard Zero-Shot ReAct description
            agent_executor = create_sql_agent(
                llm=llm,
                toolkit=toolkit,
                db=db,
                agent_type="zero-shot-react-description",
                verbose=False,
                system_message=instructions
            )

        # 6. Execute user query
        response = agent_executor.invoke({"input": user_message})
        output = response.get("output", "I could not retrieve an answer for that query.")

        # 7. Update conversation memory
        memory_manager.add_message(session_id, "user", user_message)
        memory_manager.add_message(session_id, "assistant", output)

        return output

    except Exception as e:
        print(f"[ERROR] SQL Agent Execution failed: {e}")
        return f"An error occurred while executing the query: {str(e)}"
