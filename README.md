# YT Playlist Watcher (GitHub Actions版)

**サーバー代ゼロ**でYouTubeプレイリストを10分ごと監視し、新着動画をPush通知 + 自動ダウンロード → Google Driveに保存。

## 構成

```
├── .github/workflows/
│   ├── check.yml      # 10分ごとに実行: チェック + 通知 + DL
│   └── pages.yml      # GitHub PagesにPWAをデプロイ
├── scripts/
│   └── check.js       # メインロジック
├── public/
│   ├── index.html     # PWA管理画面
│   ├── sw.js          # Service Worker
│   └── manifest.json  # PWAマニフェスト
└── data/              # Git管理の状態ファイル (自動更新)
    ├── playlists.json
    ├── known_videos.json
    ├── subscriptions.json
    └── log.json
```

## セットアップ (15分)

### 1. リポジトリ作成
```bash
# このプロジェクトをGitHubにpush
git init && git add . && git commit -m "init"
gh repo create yt-playlist-watcher --public --push --source=.
```

### 2. GitHub Secrets を設定
リポジトリ → Settings → Secrets and variables → Actions → New secret

| Secret名 | 値 |
|---|---|
| `YOUTUBE_API_KEY` | [Google Cloud Console](https://console.cloud.google.com/) でYouTube Data API v3のAPIキー |
| `VAPID_PUBLIC_KEY` | `npx web-push generate-vapid-keys` の PUBLIC KEY |
| `VAPID_PRIVATE_KEY` | 同上の PRIVATE KEY |
| `VAPID_EMAIL` | `mailto:your@email.com` |
| `GDRIVE_CREDENTIALS` | Service AccountのJSONを1行に圧縮したもの |
| `GDRIVE_FOLDER_ID` | Google DriveのフォルダURL末尾のID |
| `GH_TOKEN` | Personal Access Token (Contents: Read+Write) |

### 3. GitHub Pages を有効化
リポジトリ → Settings → Pages → Source: **GitHub Actions**

### 4. data/ ディレクトリを初期化
```bash
mkdir -p data
echo '[]' > data/playlists.json
echo '{}' > data/known_videos.json
echo '[]' > data/subscriptions.json
echo '[]' > data/log.json
git add data/ && git commit -m "init data" && git push
```

### 5. PWAにアクセス
`https://あなたのGitHubユーザー名.github.io/yt-playlist-watcher/`

### 6. PWA設定画面で入力
- GitHub リポジトリ: `owner/yt-playlist-watcher`
- Personal Access Token: `ghp_...` (Contents Read+Write)
- VAPID公開鍵: ステップ2で生成したもの

### 7. スマホにインストール
- **iPhone**: Safari → 共有ボタン → ホーム画面に追加
- **Android**: Chrome → メニュー → アプリをインストール

---

## Google Drive設定

1. [Google Cloud Console](https://console.cloud.google.com/) → IAM → サービスアカウント作成
2. キーを作成 → JSON でダウンロード
3. JSONを1行に: `cat key.json | python3 -m json.tool --compact`
4. Google Drive でフォルダ作成 → サービスアカウントのメールに「編集者」権限を付与
5. フォルダのURLからIDをコピー (`https://drive.google.com/drive/folders/【ここがID】`)

## 注意事項

- GitHub Actionsの無料枠: パブリックリポジトリは**無制限**、プライベートは月2000分
- 10分ごと実行 = 1日144回 × 約30秒 = 約72分/日 → 月約2160分 (プライベートは課金注意)
- **パブリックリポジトリ推奨** (subscriptions.jsonに通知エンドポイントが入るが実害は少ない)
- yt-dlpのダウンロード: GitHub Actionsのランナーは/tmpのみ (8GB) → その場でGDriveに転送後削除
