import os, json, sys
from pywebpush import webpush, WebPushException
from py_vapid import Vapid

YOUTUBE_API_KEY  = os.environ["YOUTUBE_API_KEY"]
VAPID_PRIVATE_KEY = os.environ["VAPID_PRIVATE_KEY"]
VAPID_PUBLIC_KEY  = os.environ["VAPID_PUBLIC_KEY"]
VAPID_EMAIL       = os.environ.get("VAPID_EMAIL", "mailto:a6068376@gmail.com")
PLAYLISTS_JSON    = os.environ.get("PLAYLISTS_JSON", "[]")
SUBSCRIPTIONS_JSON = os.environ.get("SUBSCRIPTIONS_JSON", "[]")

import urllib.request, urllib.parse

def yt_playlist_videos(playlist_id):
    videos = []
    page_token = ""
    while True:
        url = (
            f"https://www.googleapis.com/youtube/v3/playlistItems"
            f"?part=snippet&maxResults=50&playlistId={playlist_id}"
            f"&key={YOUTUBE_API_KEY}"
        )
        if page_token:
            url += f"&pageToken={page_token}"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req) as r:
            data = json.loads(r.read())
        for item in data.get("items", []):
            s = item["snippet"]
            vid = s["resourceId"]["videoId"]
            videos.append({"id": vid, "title": s["title"]})
        page_token = data.get("nextPageToken", "")
        if not page_token:
            break
    return videos

def send_push(subscription, title, body, url=""):
    try:
        sub_info = {
            "endpoint": subscription["endpoint"],
            "keys": {
                "p256dh": subscription["keys"]["p256dh"],
                "auth":   subscription["keys"]["auth"],
            }
        }
        payload = json.dumps({"title": title, "body": body, "url": url})
        webpush(
            subscription_info=sub_info,
            data=payload,
            vapid_private_key=VAPID_PRIVATE_KEY,
            vapid_claims={"sub": VAPID_EMAIL},
        )
        print(f"  [push] sent → {subscription['endpoint'][:60]}...")
    except WebPushException as e:
        resp = e.response
        if resp is not None:
            print(f"  [push] failed: {e} ({resp.status_code}) {resp.text[:100]}")
            # 410 Gone = expired subscription, skip silently
        else:
            print(f"  [push] failed: {e}")
    except Exception as e:
        print(f"  [push] error: {e}")

def main():
    # Load state
    state = {}
    if os.path.exists("state.json"):
        with open("state.json") as f:
            try: state = json.load(f)
            except: state = {}

    # Parse playlists
    try:
        playlists = json.loads(PLAYLISTS_JSON)
    except:
        print("[error] PLAYLISTS_JSON parse failed")
        return

    # Parse subscriptions
    try:
        subs = json.loads(SUBSCRIPTIONS_JSON)
        if not isinstance(subs, list): subs = []
    except:
        subs = []

    print(f"[config] {len(playlists)} playlists, {len(subs)} subscribers")

    any_new = False

    for pl in playlists:
        pl_id    = pl.get("id", "")
        pl_title = pl.get("title", pl_id)
        if not pl_id:
            continue

        print(f"\n[playlist] {pl_title} ({pl_id})")

        try:
            videos = yt_playlist_videos(pl_id)
        except Exception as e:
            print(f"  [error] fetch failed: {e}")
            continue

        known = set(state.get(pl_id, []))
        new_videos = [v for v in videos if v["id"] not in known]

        print(f"  total={len(videos)}, known={len(known)}, new={len(new_videos)}")

        if not new_videos:
            # Update known list even if no new videos
            state[pl_id] = [v["id"] for v in videos]
            continue

        any_new = True

        for v in new_videos:
            print(f"  [new] {v['title']}")

        # Send push notification per new video (max 3 to avoid spam)
        for v in new_videos[:3]:
            title = f"新着: {pl_title}"
            body  = v["title"]
            url   = f"https://www.youtube.com/watch?v={v['id']}"
            for sub in subs:
                send_push(sub, title, body, url)

        if len(new_videos) > 3:
            extra = len(new_videos) - 3
            title = f"{pl_title}: 他{extra}件の新着動画"
            body  = "タップして確認"
            url   = f"https://www.youtube.com/playlist?list={pl_id}"
            for sub in subs:
                send_push(sub, title, body, url)

        # Update state
        state[pl_id] = [v["id"] for v in videos]

    print("\n[state] saved")
    with open("state.json", "w") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()
