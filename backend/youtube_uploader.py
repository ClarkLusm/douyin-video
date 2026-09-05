
import os, json
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
TOKEN_FILE = "token.json"
CLIENT_SECRET_FILE = "client_secret.json"

def get_youtube_service():
    creds = None
    if os.path.exists(TOKEN_FILE):
        try:
            creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
        except: pass
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except:
                creds = None
        if not creds:
            if not os.path.exists(CLIENT_SECRET_FILE):
                raise Exception(f"Chua co {CLIENT_SECRET_FILE}")
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "w") as token:
            token.write(creds.to_json())
    youtube = build("youtube", "v3", credentials=creds)
    return youtube

def upload_video(file_path, title, description, tags=None, privacy="private", category_id="24"):
    if not os.path.exists(file_path):
        raise Exception(f"File not found {file_path}")
    youtube = get_youtube_service()
    title = (title[:95] + "...") if len(title) > 100 else title
    body = {
        "snippet": {"title": title, "description": description[:5000], "tags": tags or ["douyin"], "categoryId": category_id},
        "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False}
    }
    media = MediaFileUpload(file_path, chunksize=-1, resumable=True, mimetype="video/mp4")
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    while response is None:
        status, response = request.next_chunk()
    video_id = response["id"]
    return {"video_id": video_id, "url": f"https://www.youtube.com/watch?v={video_id}"}

def check_auth():
    has_client = os.path.exists(CLIENT_SECRET_FILE)
    has_token = os.path.exists(TOKEN_FILE)
    return {"has_client_secret": has_client, "has_token": has_token, "ready": has_client}

def save_client_secret_from_json(json_str_or_dict):
    if isinstance(json_str_or_dict, str):
        data = json.loads(json_str_or_dict)
    else:
        data = json_str_or_dict
    if "installed" not in data and "web" not in data:
        raise Exception("JSON khong hop le")
    with open(CLIENT_SECRET_FILE, "w") as f:
        json.dump(data, f, indent=2)
    return True
