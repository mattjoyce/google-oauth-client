# Google OAuth Client

A FastAPI-powered Google OAuth 2.0 client with automatic token refresh, state validation, and SQLite token storage. Includes systemd integration for scheduled refreshes, ideal for personal projects and services requiring persistent Google API access with minimal maintenance.

## Features

- **Complete OAuth 2.0 Flow**: Handles the entire Google authentication process
- **Automatic Token Refresh**: Keeps your access tokens valid via systemd timer
- **Secure Token Storage**: Stores credentials in SQLite with proper encryption
- **CSRF Protection**: Implements state parameter validation
- **FastAPI Backend**: Provides clean REST endpoints for token operations
- **Efficient Database Management**: Optimizes token storage to prevent bloat
- **Comprehensive Logging**: Detailed logs for troubleshooting
- **Systemd Integration**: Maintains tokens without manual intervention

## Installation

1. Clone the repository:
```bash
git clone https://github.com/yourusername/google-oauth-client.git
cd google-oauth-client
```

2. Install the required packages:
```bash
pip install fastapi uvicorn python-dotenv requests
```

3. Create and configure your `.env` file:
```bash
cp .env.sample .env
# Edit .env with your credentials
```

4. Set up the systemd service and timer:
```bash
# Replace paths in the service file
sudo cp google-oauth-refresh.service google-oauth-refresh.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable google-oauth-refresh.timer
sudo systemctl start google-oauth-refresh.timer
```

## Configuration

Edit your `.env` file with the following settings:

```
# Google OAuth Configuration
GOOGLE_CLIENT_ID=your_client_id_here
GOOGLE_CLIENT_SECRET=your_client_secret_here
GOOGLE_REDIRECT_URI=http://localhost:9000/oauth/google/callback
GOOGLE_SCOPES=https://www.googleapis.com/auth/drive.readonly https://www.googleapis.com/auth/userinfo.email

# Directory Configuration
BASE_DIR=/path/to/your/script/directory
LOG_DIR=${BASE_DIR}/log
DB_PATH=${BASE_DIR}/google_oauth.db

# Database Configuration
MAX_TOKEN_RECORDS=10

# Log Level (INFO or DEBUG)
LOG_LEVEL=INFO
```

### Getting Google API Credentials

1. Go to the [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select an existing one
3. Navigate to "APIs & Services" > "Credentials"
4. Click "Create Credentials" and select "OAuth client ID"
5. Choose "Web application" as the application type
6. Add your redirect URI (e.g., `http://localhost:9000/oauth/google/callback`)
7. Copy the Client ID and Client Secret to your `.env` file

## Usage

### Initial Authentication

1. Start the FastAPI server:
```bash
python google_oauth.py
```

2. Open your browser and navigate to:
```
http://localhost:9000/oauth/google/start
```

3. Complete the Google authentication process

### Using Tokens in Your Application

Once authenticated, you can retrieve valid tokens via:

```bash
curl http://localhost:9000/oauth/google/token
```

Or in Python code:

```python
import requests

def get_google_token():
    response = requests.get("http://localhost:9000/oauth/google/token")
    data = response.json()
    return data.get("access_token")

def call_google_api(endpoint):
    token = get_google_token()
    headers = {"Authorization": f"Bearer {token}"}
    return requests.get(endpoint, headers=headers)
```

### Checking Token Status

You can check the status of your current token:

```bash
curl http://localhost:9000/oauth/google/status
```

## Server Endpoints

- `GET /oauth/google/start` - Begin the OAuth flow
- `GET /oauth/google/callback` - Handle Google's OAuth response
- `GET /oauth/google/token` - Get a valid access token
- `GET /oauth/google/status` - Check current token status

## Systemd Integration

The included systemd files will:
- Run token checks every 6 hours
- Refresh tokens before they expire
- Clean up old inactive tokens
- Start 15 minutes after system boot

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the LICENSE file for details.

