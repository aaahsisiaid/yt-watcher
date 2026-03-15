#!/usr/bin/env python3
"""
YT Playlist Watcher — GitHub Actions runner
- YouTube Data API v3 でプレイリストの新着動画を検出
- yt-dlp でダウンロード → Google Drive にアップロード
- Web Push で通知送信
- state.json に既知動画IDを記録（リポジトリにコミット）
"""

import os, json, base64, subprocess, tempfile, sys
from pathlib import Path

import requests
from pywebpush import webpush, WebPushException
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# ─── 環境変数 ─────────────────────────────────────────────────────────────────
YT_API_KEY       = os.environ["YOUTUBE_API_KEY"]
VAPID_PRIVATE    = os.environ["VAPID_PRIVATE_KEY"]
VAPID_PUBLIC     = os.environ["VAPID_PUBLIC_KEY"]
VAPID_EMAIL      = os.environ.get("VAPID_EMAIL", "mailto:admin@example.com")
GDRIVE_CREDS_B64 = os.environ.get("GDRIVE_CREDENTIALS", "")
PLAYLISTS_JSON   = os.environ.get("PLAYLISTS_JSON", "[]")
SUBSCRIPTIONS_JSON = os.environ.get("SUBSCRIPTIONS_JSON", "[]")

# ─── 設定読み込み ─────────────────────────────────────────────────────────────
# PLAYLISTS_JSON 例:
# [{"id":"PLxxxxxx","title":"My PL","autoDownload":true,"driveFolder":"1xyzFolderID"}]
playlists     = json.loads(PLAYLISTS_JSON)
subscriptions = json.loads(SUBSCRIPTIONS_JSON)

# ─── state.json ───────────────────────────────────────────────────────────────
STATE_FILE = Path("state.json")
state = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}
# state = { playlistId: [videoId, ...] }

# ─── YouTube API ──────────────────────────────────────────────────────────────
def fetch_playlist_videos(playlist_id: str) -> list[dict]:
    videos, page_token = [], ""
    while True:
        url = (
            f"https://www.googleapis.com/youtube/v3/playlistItems"
            f"?part=snippet&maxResults=50&playlistId={playlist_id}&key={YT_API_KEY}"
            + (f"&pageToken={page_token}" if page_token else "")
        )
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        data = r.json()
        for item in data.get("items", []):
            s = item["snippet"]
            vid = s["resourceId"]["videoId"]
            videos.append({
                "id":    vid,
                "title": s["title"],
                "url":   f"https://www.youtube.com/watch?v={vid}",
                "thumb": (s.get("thumbnails") or {}).get("medium", {}).get("url", ""),
            })
        page_token = data.get("nextPageToken", "")
        if not page_token:
            break
    return videos

# ─── Web Push ─────────────────────────────────────────────────────────────────
def send_push(title: str, body: str, url: str = ""):
    payload = json.dumps({"title": title, "body": body, "url": url})
    dead = []
    for sub in subscriptions:
        try:
            webpush(
                subscription_info=sub,
                data=payload,
                vapid_private_key=VAPID_PRIVATE,
                vapid_claims={"sub": VAPID_EMAIL},
            )
            print(f"  [push] sent to {sub['endpoint'][:40]}...")
        except WebPushException as e:
            print(f"  [push] failed: {e}", file=sys.stderr)
            if e.response and e.response.status_code in (404, 410):
                dead.append(sub["endpoint"])
    return dead

# ─── Google Drive ─────────────────────────────────────────────────────────────
_drive_service = None

def get_drive():
    global _drive_service
    if _drive_service or not GDRIVE_CREDS_B64:
        return _drive_service
    creds_json = base64.b64decode(GDRIVE_CREDS_B64).decode()
    creds_data = json.loads(creds_json)
    creds = service_account.Credentials.from_service_account_info(
        creds_data, scopes=["https://www.googleapis.com/auth/drive.file"]
    )
    _drive_service = build("drive", "v3", credentials=creds, cache_discovery=False)
    return _drive_service

def upload_to_drive(file_path: str, filename: str, folder_id: str = "") -> str:
    drive = get_drive()
    if not drive:
        print("  [drive] no credentials, skip upload")
        return ""
    meta = {"name": filename}
    if folder_id:
        meta["parents"] = [folder_id]
    media = MediaFileUpload(file_path, resumable=True)
    f = drive.files().create(body=meta, media_body=media, fields="id,webViewLink").execute()
    return f.get("webViewLink", "")

# ─── yt-dlp download ──────────────────────────────────────────────────────────
def download_video(video: dict, folder_id: str = "") -> bool:
    with tempfile.TemporaryDirectory() as tmpdir:
        out_template = os.path.join(tmpdir, "%(title)s.%(ext)s")
        cmd = [
            "yt-dlp",
            "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "--merge-output-format", "mp4",
            "-o", out_template,
            "--no-playlist",
            video["url"],
        ]
        print(f"  [yt-dlp] downloading: {video['title']}")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"  [yt-dlp] error: {result.stderr[:300]}", file=sys.stderr)
            send_push("❌ ダウンロード失敗", f"「{video['title']}」", video["url"])
            return False

        # tmpdir にできたファイルを探す
        files = list(Path(tmpdir).glob("*.mp4"))
        if not files:
            print("  [yt-dlp] no output file found", file=sys.stderr)
            return False

        mp4 = files[0]
        print(f"  [drive] uploading {mp4.name} ({mp4.stat().st_size // 1024 // 1024} MB)")
        link = upload_to_drive(str(mp4), mp4.name, folder_id)
        msg = f"「{video['title']}」をGoogle Driveに保存しました"
        send_push("✅ ダウンロード完了", msg, link or video["url"])
        return True

# ─── Main ─────────────────────────────────────────────────────────────────────
def main():
    if not playlists:
        print("No playlists configured. Set PLAYLISTS_JSON secret.")
        return

    changed = False

    for pl in playlists:
        pl_id    = pl["id"]
        pl_title = pl.get("title", pl_id)
        auto_dl  = pl.get("autoDownload", False)
        folder   = pl.get("driveFolder", "")

        print(f"\n[playlist] {pl_title} ({pl_id})")
        try:
            videos = fetch_playlist_videos(pl_id)
        except Exception as e:
            print(f"  [error] fetch failed: {e}", file=sys.stderr)
            continue

        known    = set(state.get(pl_id, []))
        all_ids  = [v["id"] for v in videos]
        new_vids = [v for v in videos if v["id"] not in known]

        print(f"  total={len(videos)}, known={len(known)}, new={len(new_vids)}")

        for v in new_vids:
            print(f"  [new] {v['title']}")
            send_push(
                "🆕 新しい動画",
                f"{pl_title}: 「{v['title']}」が追加されました",
                v["url"],
            )
            if auto_dl:
                download_video(v, folder)

        # state 更新
        state[pl_id] = all_ids
        changed = True

    # state.json 書き出し（Actionsがコミットする）
    if changed:
        STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2))
        print("\n[state] saved")

if __name__ == "__main__":
    main()
