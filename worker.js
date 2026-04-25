const ALLOWED_ORIGIN = 'https://aaahsisiaid.github.io';
const cors = {
  'Access-Control-Allow-Origin': ALLOWED_ORIGIN,
  'Access-Control-Allow-Methods': 'POST, GET, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type, Range',
  'Access-Control-Expose-Headers': 'Content-Length, Content-Range, Content-Type',
};

export default {
  async fetch(request, env) {
    if (request.method === 'OPTIONS') return new Response(null, { headers: cors });
    const url = new URL(request.url);

    // ── /stream : 動画URLリストを返す ──────────────────────────────
    if (request.method === 'GET' && url.pathname === '/stream') {
      const videoId = url.searchParams.get('v');
      if (!videoId) return json({ error: 'Missing v' }, 400);
      try { return json(await fetchStreamInfo(videoId)); }
      catch (e) { return json({ error: e.message }, 500); }
    }

    // ── /proxy : YouTubeストリームをWorker経由で中継 ────────────────
    // player.html から ?url=<encoded> で呼ばれる
    if (request.method === 'GET' && url.pathname === '/proxy') {
      const targetUrl = url.searchParams.get('url');
      if (!targetUrl) return json({ error: 'Missing url' }, 400);

      // Rangeヘッダーを透過させてシーク対応
      const rangeHeader = request.headers.get('Range');
      const fetchHeaders = {
        'User-Agent': 'Mozilla/5.0 (SMART-TV; Linux; Tizen 6.0) AppleWebKit/538.1 (KHTML, like Gecko) Version/6.0 TV Safari/538.1',
        'Referer': 'https://www.youtube.com/',
        'Origin': 'https://www.youtube.com',
      };
      if (rangeHeader) fetchHeaders['Range'] = rangeHeader;

      try {
        const upstream = await fetch(targetUrl, { headers: fetchHeaders });
        const responseHeaders = {
          ...cors,
          'Content-Type': upstream.headers.get('Content-Type') || 'video/mp4',
          'Accept-Ranges': 'bytes',
        };
        const cl = upstream.headers.get('Content-Length');
        const cr = upstream.headers.get('Content-Range');
        if (cl) responseHeaders['Content-Length'] = cl;
        if (cr) responseHeaders['Content-Range'] = cr;

        return new Response(upstream.body, {
          status: upstream.status,
          headers: responseHeaders,
        });
      } catch (e) {
        return json({ error: 'proxy error: ' + e.message }, 502);
      }
    }

    // ── /videos : プレイリスト一覧 ─────────────────────────────────
    if (request.method === 'GET' && url.pathname === '/videos') {
      const plId = url.searchParams.get('playlistId');
      if (!plId) return json({ error: 'Missing playlistId' }, 400);
      try { return json(await fetchPlaylistVideos(plId, env.YT_API_KEY)); }
      catch (e) { return json({ error: e.message }, 500); }
    }

    // ── POST / : Push通知サブスクリプション登録 ────────────────────
    if (request.method === 'POST' && url.pathname === '/') {
      try {
        const { subscription } = await request.json();
        if (!subscription) return json({ error: 'Missing subscription' }, 400);
        const pat = env.GH_PAT, repo = env.GITHUB_REPO;
        if (!pat || !repo) return json({ error: 'Missing env' }, 500);
        const current = env.SUBSCRIPTIONS_JSON || '[]';
        let subs = [];
        try { subs = JSON.parse(current); if (!Array.isArray(subs)) subs = []; } catch { subs = []; }
        subs = subs.filter(s => s.endpoint !== subscription.endpoint);
        subs.push(subscription);
        const r = await fetch(`https://api.github.com/repos/${repo}/dispatches`, {
          method: 'POST',
          headers: { Authorization: `token ${pat}`, Accept: 'application/vnd.github+json', 'Content-Type': 'application/json', 'User-Agent': 'yt-watcher' },
          body: JSON.stringify({ event_type: 'register-subscription', client_payload: { subscription: JSON.stringify(subscription), all_subs: JSON.stringify(subs) } })
        });
        if (!r.ok) return json({ error: `dispatch error: ${r.status} ${await r.text()}` }, 500);
        return json({ ok: true, total: subs.length });
      } catch (e) { return json({ error: e.message }, 500); }
    }

    return new Response('Not found', { status: 404 });
  }
};

// ── YouTubeからストリームURLを取得（Innertube API）─────────────────
async function fetchStreamInfo(videoId) {
  const res = await fetch(
    'https://www.youtube.com/youtubei/v1/player?prettyPrint=false',
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'User-Agent': 'Mozilla/5.0 (SMART-TV; Linux; Tizen 6.0) AppleWebKit/538.1 (KHTML, like Gecko) Version/6.0 TV Safari/538.1',
        'Origin': 'https://www.youtube.com',
        'Referer': `https://www.youtube.com/watch?v=${videoId}`,
      },
      body: JSON.stringify({
        videoId,
        context: {
          client: {
            clientName: 'TVHTML5',
            clientVersion: '7.20230405.08.01',
            hl: 'ja',
            gl: 'JP',
          }
        }
      })
    }
  );
  if (!res.ok) throw new Error(`Innertube: ${res.status}`);
  const data = await res.json();

  const status = data.playabilityStatus?.status;
  if (status === 'LOGIN_REQUIRED') throw new Error('ログインが必要です');
  if (status === 'UNPLAYABLE' || status === 'ERROR') throw new Error('再生不可: ' + (data.playabilityStatus?.reason || status));

  const streaming = data.streamingData || {};
  const details = data.videoDetails || {};
  const formats = [...(streaming.formats || []), ...(streaming.adaptiveFormats || [])];
  const muxed = formats
    .filter(f => f.url && f.mimeType?.includes('video/mp4') && f.audioQuality)
    .sort((a, b) => (b.height || 0) - (a.height || 0))
    .map(f => ({ url: f.url, quality: f.qualityLabel || f.quality, height: f.height || 0 }));

  if (!muxed.length) throw new Error('mp4ストリームなし (status: ' + status + ')');
  return { title: details.title || '', author: details.author || '', streams: muxed };
}

// ── プレイリスト動画一覧 ──────────────────────────────────────────
async function fetchPlaylistVideos(playlistId, apiKey) {
  const videos = []; let pageToken = '';
  do {
    const u = `https://www.googleapis.com/youtube/v3/playlistItems?part=snippet&maxResults=50&playlistId=${playlistId}&key=${apiKey}${pageToken ? '&pageToken=' + pageToken : ''}`;
    const r = await fetch(u);
    if (!r.ok) throw new Error(`YouTube API: ${r.status}`);
    const data = await r.json();
    for (const item of data.items || []) {
      const s = item.snippet, vid = s.resourceId.videoId;
      videos.push({ id: vid, title: s.title, url: `https://www.youtube.com/watch?v=${vid}`, thumb: s.thumbnails?.medium?.url || '' });
    }
    pageToken = data.nextPageToken || '';
  } while (pageToken);
  return videos;
}

function json(data, status = 200) {
  return new Response(JSON.stringify(data), { status, headers: { ...cors, 'Content-Type': 'application/json' } });
}
