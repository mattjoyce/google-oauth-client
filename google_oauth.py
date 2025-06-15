import os
import time
import sqlite3
import logging
import requests
import secrets
import json
import urllib.parse
from fastapi import FastAPI, Request, Query, HTTPException, status
from fastapi.responses import JSONResponse
from dotenv import load_dotenv

# Load environment variables
load_dotenv(".env")

# Configuration from environment variables
BASE_DIR = os.getenv("BASE_DIR", os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.getenv("LOG_DIR", os.path.join(BASE_DIR, "log"))
DB_PATH = os.getenv("DB_PATH", os.path.join(BASE_DIR, "google_oauth.db"))
MAX_TOKEN_RECORDS = int(os.getenv("MAX_TOKEN_RECORDS", "10"))

# Set up logging
LOG_FILE = os.path.join(LOG_DIR, "google_oauth.log")

if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

# Required environment variables
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI")
GOOGLE_SCOPES_RAW = os.getenv("GOOGLE_SCOPES", "https://www.googleapis.com/auth/userinfo.email")
GOOGLE_SCOPES = GOOGLE_SCOPES_RAW.strip()

# Validate required environment variables
required_vars = {
    "GOOGLE_CLIENT_ID": GOOGLE_CLIENT_ID,
    "GOOGLE_CLIENT_SECRET": GOOGLE_CLIENT_SECRET,
    "GOOGLE_REDIRECT_URI": GOOGLE_REDIRECT_URI,
}

missing_vars = [var for var, value in required_vars.items() if not value]
if missing_vars:
    raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")

# Store for OAuth state parameter
# In a production environment with multiple users, this should be in Redis or another shared storage
STATE_STORE = {}

def init_db():
    """Initialize the database if it does not exist or is missing tables."""
    try:
        # Check if database file exists
        db_exists = os.path.exists(DB_PATH)
        
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        # Check if the tokens table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tokens';")
        table_exists = cursor.fetchone() is not None

        if not db_exists or not table_exists:
            logging.info("🛠 Database or table missing, initializing schema...")

            # Create tokens table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS tokens (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    access_token TEXT NOT NULL,
                    refresh_token TEXT NOT NULL,
                    expires_at INTEGER NOT NULL,
                    scope TEXT NOT NULL,
                    token_type TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_active INTEGER DEFAULT 1
                )
            """)

            # Create states table for CSRF protection
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS oauth_states (
                    state TEXT PRIMARY KEY,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            conn.commit()
            logging.info("✅ Database initialized successfully")
        else:
            logging.info("ℹ️ Database and tables already exist. Skipping initialization.")

        conn.close()

    except sqlite3.Error as e:
        logging.error(f"❌ Database initialization failed: {e}")
        raise

def save_state(state):
    """Save OAuth state parameter to database."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Delete old states (older than 10 minutes)
        cursor.execute("""
            DELETE FROM oauth_states
            WHERE datetime(created_at, '+10 minutes') < datetime('now')
        """)
        
        # Insert new state
        cursor.execute(
            "INSERT INTO oauth_states (state) VALUES (?)",
            (state,)
        )
        
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logging.error(f"❌ Failed to save state: {e}")
        return False

def verify_state(state):
    """Verify that the state exists in the database and delete it if it does."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("SELECT state FROM oauth_states WHERE state = ?", (state,))
        result = cursor.fetchone()
        
        if result:
            # State exists, delete it
            cursor.execute("DELETE FROM oauth_states WHERE state = ?", (state,))
            conn.commit()
            conn.close()
            return True
        
        conn.close()
        return False
    except Exception as e:
        logging.error(f"❌ Failed to verify state: {e}")
        return False

def save_tokens(access_token, refresh_token, expires_in, scope, token_type):
    """Save tokens to the database using an upsert pattern."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Calculate when the token will expire
        expires_at = int(time.time()) + expires_in
        
        # First, check if we have an active token with the same refresh_token
        cursor.execute(
            "SELECT id FROM tokens WHERE refresh_token = ? AND is_active = 1",
            (refresh_token,)
        )
        
        existing_token = cursor.fetchone()
        
        if existing_token:
            # Update the existing token
            cursor.execute(
                """
                UPDATE tokens 
                SET access_token = ?, expires_at = ?, scope = ?, token_type = ?
                WHERE id = ?
                """,
                (access_token, expires_at, scope, token_type, existing_token[0])
            )
            logging.info(f"✅ Updated existing token (ID: {existing_token[0]})")
        else:
            # Insert a new token
            cursor.execute(
                """
                INSERT INTO tokens 
                (access_token, refresh_token, expires_at, scope, token_type) 
                VALUES (?, ?, ?, ?, ?)
                """,
                (access_token, refresh_token, expires_at, scope, token_type)
            )
            logging.info("✅ Inserted new token")
            
            # Clean up old tokens if we have more than MAX_TOKEN_RECORDS
            cursor.execute(
                """
                UPDATE tokens
                SET is_active = 0
                WHERE id NOT IN (
                    SELECT id FROM tokens
                    ORDER BY id DESC
                    LIMIT ?
                )
                """, 
                (MAX_TOKEN_RECORDS,)
            )
            
            # Log how many old tokens were marked as inactive
            if cursor.rowcount > 0:
                logging.info(f"🧹 Marked {cursor.rowcount} old tokens as inactive")
        
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logging.error(f"❌ Failed to save tokens: {e}")
        return False

def get_tokens():
    """Get the most recent active tokens from the database."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT access_token, refresh_token, expires_at, scope, token_type
            FROM tokens
            WHERE is_active = 1
            ORDER BY id DESC
            LIMIT 1
        """)
        
        result = cursor.fetchone()
        conn.close()
        
        if result:
            return {
                "access_token": result[0],
                "refresh_token": result[1],
                "expires_at": result[2],
                "scope": result[3],
                "token_type": result[4]
            }
        return None
    except Exception as e:
        logging.error(f"❌ Failed to load tokens: {e}")
        return None

def refresh_token(refresh_token_str):
    """Refresh the access token using the refresh token."""
    try:
        token_url = "https://oauth2.googleapis.com/token"
        data = {
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "refresh_token": refresh_token_str,
            "grant_type": "refresh_token"
        }
        
        response = requests.post(token_url, data=data)
        
        if response.status_code != 200:
            error_msg = f"Token refresh failed: HTTP {response.status_code}"
            try:
                error_data = response.json()
                error_msg += f" - {json.dumps(error_data)}"
            except:
                error_msg += f" - {response.text}"
                
            logging.error(f"❌ {error_msg}")
            return None
            
        token_data = response.json()
        
        # Note: Google doesn't return a new refresh token in refresh responses
        # So we keep using the same refresh token
        
        # Save the new access token
        save_tokens(
            token_data["access_token"],
            refresh_token_str,  # Use the same refresh token
            token_data["expires_in"],
            token_data.get("scope", GOOGLE_SCOPES),
            token_data["token_type"]
        )
        
        return token_data["access_token"]
    except Exception as e:
        logging.error(f"❌ Failed to refresh token: {e}", exc_info=True)
        return None

def get_valid_token():
    """Get a valid access token, refreshing if necessary."""
    tokens = get_tokens()
    
    if not tokens:
        logging.warning("⚠️ No tokens found in database")
        return None
        
    current_time = int(time.time())
    
    # If token expires in less than 5 minutes, refresh it
    if tokens["expires_at"] - current_time < 300:
        logging.info("🔄 Token expiring soon, refreshing...")
        new_token = refresh_token(tokens["refresh_token"])
        return new_token if new_token else tokens["access_token"]
        
    return tokens["access_token"]

def cleanup_old_records():
    """Cleanup old inactive records to prevent database bloat."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Delete inactive tokens older than 30 days
        cursor.execute("""
            DELETE FROM tokens
            WHERE is_active = 0 AND datetime(created_at, '+30 days') < datetime('now')
        """)
        
        if cursor.rowcount > 0:
            logging.info(f"🧹 Deleted {cursor.rowcount} old inactive tokens")
            
        # Delete old oauth states (older than 1 day, as a safety measure)
        cursor.execute("""
            DELETE FROM oauth_states
            WHERE datetime(created_at, '+1 day') < datetime('now')
        """)
        
        if cursor.rowcount > 0:
            logging.info(f"🧹 Deleted {cursor.rowcount} old OAuth states")
            
        conn.commit()
        conn.close()
        
        return True
    except Exception as e:
        logging.error(f"❌ Failed to clean up old records: {e}")
        return False

# FastAPI app creation and routes
app = FastAPI()

@app.on_event("startup")
async def startup_event():
    """Initialize database on startup"""
    init_db()
    cleanup_old_records()

@app.get("/oauth/google/callback")
async def google_callback(
    request: Request,
    code: str = Query(None),
    state: str = Query(None),
    error: str = Query(None)
):
    """Handle Google OAuth callback"""
    if error:
        error_msg = f"OAuth error: {error}"
        logging.error(f"❌ {error_msg}")
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": error_msg, "error_code": "oauth_error"}
        )
        
    if not code:
        error_msg = "Missing OAuth code"
        logging.warning(f"⚠️ {error_msg}")
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": error_msg, "error_code": "missing_code"}
        )
        
    if not state:
        error_msg = "Missing state parameter"
        logging.warning(f"⚠️ {error_msg}")
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": error_msg, "error_code": "missing_state"}
        )
    
    # Verify the state parameter to prevent CSRF attacks
    if not verify_state(state):
        error_msg = "Invalid state parameter"
        logging.warning(f"⚠️ {error_msg}")
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": error_msg, "error_code": "invalid_state"}
        )
    
    # Exchange code for access token
    token_url = "https://oauth2.googleapis.com/token"
    data = {
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": GOOGLE_REDIRECT_URI
    }

    try:
        response = requests.post(token_url, data=data)
        
        if response.status_code != 200:
            error_msg = f"Failed to exchange code for token: HTTP {response.status_code}"
            try:
                error_data = response.json()
                error_msg += f" - {json.dumps(error_data)}"
            except:
                error_msg += f" - {response.text}"
                
            logging.error(f"❌ {error_msg}")
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"error": "Failed to exchange code for token", "details": error_msg, "error_code": "token_exchange_failed"}
            )
        
        token_data = response.json()
        
        if "access_token" not in token_data or "refresh_token" not in token_data:
            error_msg = f"Invalid token response: {json.dumps(token_data)}"
            logging.error(f"❌ {error_msg}")
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"error": "Invalid token response from Google", "error_code": "invalid_token_response"}
            )
        
        # Save tokens to database
        save_tokens(
            token_data["access_token"],
            token_data["refresh_token"],
            token_data["expires_in"],
            token_data.get("scope", GOOGLE_SCOPES),
            token_data["token_type"]
        )
        
        logging.info("✅ OAuth flow completed successfully")
        return {"message": "OAuth successful!", "status": "success"}
        
    except requests.exceptions.RequestException as e:
        error_msg = f"Request to Google failed: {str(e)}"
        logging.error(f"❌ {error_msg}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"error": "Failed to communicate with Google API", "details": str(e), "error_code": "google_api_error"}
        )
    except Exception as e:
        error_msg = f"Unexpected error: {str(e)}"
        logging.error(f"❌ {error_msg}", exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"error": "An unexpected error occurred", "error_code": "internal_error"}
        )

@app.get("/oauth/google/start")
async def start_oauth(request: Request):
    """Generate the authorization URL for Google OAuth."""
    try:
        # Generate a random state parameter for CSRF protection
        state = secrets.token_urlsafe(32)
        
        # Save the state to the database
        if not save_state(state):
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={"error": "Failed to save state", "error_code": "state_save_failed"}
            )
        
        auth_url = "https://accounts.google.com/o/oauth2/v2/auth"
        params = {
            "client_id": GOOGLE_CLIENT_ID,
            "redirect_uri": GOOGLE_REDIRECT_URI,
            "response_type": "code",
            "scope": GOOGLE_SCOPES,
            "access_type": "offline",
            "prompt": "consent",  # Force to show consent screen to get refresh token
            "state": state  # Include state parameter for CSRF protection
        }
        
        # Convert params to URL query string
        query_string = urllib.parse.urlencode(params)
        authorization_url = f"{auth_url}?{query_string}"
        
        return {"authorization_url": authorization_url, "state": state}
    except Exception as e:
        error_msg = f"Failed to generate authorization URL: {str(e)}"
        logging.error(f"❌ {error_msg}", exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"error": error_msg, "error_code": "auth_url_generation_failed"}
        )

@app.get("/oauth/google/token")
async def get_access_token():
    """Get a valid access token."""
    try:
        token = get_valid_token()
        
        if token:
            return {"access_token": token, "status": "success"}
        else:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"error": "No valid token available", "error_code": "no_token"}
            )
    except Exception as e:
        error_msg = f"Failed to get token: {str(e)}"
        logging.error(f"❌ {error_msg}", exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"error": error_msg, "error_code": "token_retrieval_failed"}
        )

@app.get("/oauth/google/status")
async def get_token_status():
    """Get the status of the current token."""
    try:
        tokens = get_tokens()
        
        if not tokens:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"status": "no_token", "message": "No token found"}
            )
            
        current_time = int(time.time())
        expires_in = tokens["expires_at"] - current_time
        
        return {
            "status": "active" if expires_in > 0 else "expired",
            "expires_in_seconds": max(0, expires_in),
            "expires_in_minutes": max(0, expires_in // 60),
            "scope": tokens["scope"],
            "token_type": tokens["token_type"]
        }
    except Exception as e:
        error_msg = f"Failed to get token status: {str(e)}"
        logging.error(f"❌ {error_msg}", exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"error": error_msg, "error_code": "status_check_failed"}
        )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=9001)
