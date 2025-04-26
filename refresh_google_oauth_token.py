#!/usr/bin/env python3
import os
import logging
from dotenv import load_dotenv
from google_oauth import init_db, get_valid_token, cleanup_old_records, LOG_DIR

# Load environment variables
load_dotenv(".env")

# Ensure log directory exists
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)

# Configure logging specifically for the refresh script
logging.basicConfig(
    filename=os.path.join(LOG_DIR, "google_oauth_refresh.log"),
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

if __name__ == "__main__":
    logging.info("🔄 Running token refresh check via systemd timer...")
    try:
        # Initialize the database if needed
        init_db()
        
        # Get a valid token (will refresh if needed)
        token = get_valid_token()
        
        if token:
            logging.info("✅ Token is valid or has been refreshed.")
        else:
            logging.warning("⚠️ No valid token found after check.")
            
        # Clean up old records
        logging.info("🧹 Cleaning up old records...")
        if cleanup_old_records():
            logging.info("✅ Old records cleaned up successfully.")
        else:
            logging.warning("⚠️ Failed to clean up old records.")
            
    except Exception as e:
        logging.error(f"❌ Error during token refresh check: {e}", exc_info=True)
