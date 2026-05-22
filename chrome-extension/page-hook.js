(function () {
  const EVENTS = {
    request: "studysis:bilibili-subtitle-request",
    meta: "studysis:bilibili-subtitle-meta",
    body: "studysis:bilibili-subtitle-body",
    debug: "studysis:bilibili-subtitle-debug"
  };
  const FLAG = "__studysisBilibiliSubtitleCollectorInstalled__";

  if (window[FLAG] || !location.host.includes("bilibili.com")) {
    return;
  }
  window[FLAG] = true;

  const state = {
    latestPageKey: "",
    fetchedTrackUrls: new Set(),
    retryTimer: 0,
    retryCount: 0,
    historyPatched: false,
    debug: createEmptyDebugState()
  };

  bootstrap();

  function bootstrap() {
    window.addEventListener(EVENTS.request, (event) => {
      const reason = sanitizeText(event?.detail?.reason || "external-request");
      void collectOfficialSubtitles(reason, { force: true });
    });

    document.addEventListener("DOMContentLoaded", () => {
      void collectOfficialSubtitles("dom-content-loaded");
    });

    window.addEventListener("load", () => {
      void collectOfficialSubtitles("window-load");
    });

    patchHistoryNavigation();

    window.setTimeout(() => {
      void collectOfficialSubtitles("startup-delay");
    }, 300);
  }

  function patchHistoryNavigation() {
    if (state.historyPatched) {
      return;
    }
    state.historyPatched = true;

    const wrap = (methodName) => {
      const original = history[methodName];
      if (typeof original !== "function") {
        return;
      }

      history[methodName] = function patchedHistoryMethod(...args) {
        const result = original.apply(this, args);
        window.setTimeout(() => {
          void collectOfficialSubtitles(`history-${methodName}`, { force: true });
        }, 50);
        return result;
      };
    };

    wrap("pushState");
    wrap("replaceState");
    window.addEventListener("popstate", () => {
      window.setTimeout(() => {
        void collectOfficialSubtitles("history-popstate", { force: true });
      }, 50);
    });
  }

  async function collectOfficialSubtitles(reason, options = {}) {
    startDebugRun(reason);
    const identifiers = extractVideoIdentifiers();
    state.debug.identifiers = identifiers;
    pushDebug();
    if (!identifiers.bvid || !identifiers.cid) {
      addError("identifier", "missing bvid or cid", { identifiers });
      state.debug.last_stage = "identifier_missing";
      pushDebug();
      scheduleRetry(reason);
      return;
    }

    const pageKey = `${location.href}|${identifiers.bvid}|${identifiers.cid}`;
    if (options.force || state.latestPageKey !== pageKey) {
      state.latestPageKey = pageKey;
      state.fetchedTrackUrls = new Set();
      state.retryCount = 0;
      clearRetry();
    }

    const trackList = await getSubtitleTrackList(identifiers);
    if (!trackList.length) {
      addError("track_list", "no subtitle tracks found", { identifiers });
      state.debug.last_stage = "track_list_empty";
      pushDebug();
      scheduleRetry(reason);
      return;
    }

    state.debug.final_track_list = trackList;
    state.debug.last_stage = "track_list_ready";
    pushDebug();

    emit(EVENTS.meta, {
      reason,
      identifiers,
      tracks: trackList.map((track) => ({
        lang: track.lang,
        langKey: track.langKey,
        trackType: track.trackType,
        source: track.source,
        sourceUrl: track.sourceUrl
      }))
    });

    state.debug.last_stage = "track_list_handoff";
    pushDebug();
  }

  async function getSubtitleTrackList(identifiers) {
    state.debug.last_stage = "collect_track_list";
    pushDebug();
    const playerTracks = await getPlayerSubtitleTracks();
    if (playerTracks.length) {
      state.debug.last_stage = "player_track_list_ready";
      pushDebug();
      return playerTracks;
    }

    const apiTracks = await getSubtitleTracksFromApi(identifiers);
    return apiTracks;
  }

  async function getPlayerSubtitleTracks() {
    const tracks = [];

    const player = window.player;
    try {
      if (player && typeof player.getSubtitleList === "function") {
        const result = await Promise.resolve(player.getSubtitleList());
        const normalized = normalizeTrackList(result, "player");
        state.debug.player_tracks_raw.push({
          source: "player",
          raw_count: Array.isArray(result) ? result.length : Array.isArray(result?.subtitles) ? result.subtitles.length : 0,
          normalized_count: normalized.length,
          items: normalized
        });
        tracks.push(...normalized);
      }
    } catch (error) {
      addError("player", String(error?.message || error), {});
    }

    try {
      const playInfo = window.__playinfo__ || {};
      const normalized = normalizeTrackList(playInfo?.data?.subtitle?.subtitles, "__playinfo__");
      state.debug.player_tracks_raw.push({
        source: "__playinfo__",
        raw_count: Array.isArray(playInfo?.data?.subtitle?.subtitles) ? playInfo.data.subtitle.subtitles.length : 0,
        normalized_count: normalized.length,
        items: normalized
      });
      tracks.push(...normalized);
    } catch (error) {
      addError("__playinfo__", String(error?.message || error), {});
    }

    return dedupeTrackList(tracks);
  }

  async function getSubtitleTracksFromApi(identifiers) {
    const requests = buildSubtitleApiRequests(identifiers);

    for (const request of requests) {
      const response = await fetchJson(request.url);
      state.debug.api_attempts.push({
        source: request.source,
        url: request.url,
        ok: response.ok,
        http_status: response.status,
        response_code: response.json?.code ?? null,
        response_message: sanitizeText(response.json?.message || response.error || ""),
        subtitle_payload: response.json?.data?.subtitle || null
      });
      pushDebug();
      const tracks = normalizeTrackList(
        response.json?.data?.subtitle?.subtitles || response.json?.data?.subtitle?.list || [],
        request.source
      );
      if (tracks.length) {
        state.debug.last_stage = "api_track_list_ready";
        pushDebug();
        return dedupeTrackList(tracks);
      }
    }

    return [];
  }

  function buildSubtitleApiRequests(identifiers) {
    const cid = String(identifiers.cid);
    const requests = [];

    if (identifiers.bvid) {
      requests.push({
        source: "x_player_wbi_v2",
        url: `https://api.bilibili.com/x/player/wbi/v2?bvid=${encodeURIComponent(identifiers.bvid)}&cid=${encodeURIComponent(cid)}`
      });
      requests.push({
        source: "x_player_v2",
        url: `https://api.bilibili.com/x/player/v2?bvid=${encodeURIComponent(identifiers.bvid)}&cid=${encodeURIComponent(cid)}`
      });
    }

    if (identifiers.aid) {
      requests.push({
        source: "x_player_wbi_v2",
        url: `https://api.bilibili.com/x/player/wbi/v2?aid=${encodeURIComponent(String(identifiers.aid))}&cid=${encodeURIComponent(cid)}`
      });
      requests.push({
        source: "x_player_v2",
        url: `https://api.bilibili.com/x/player/v2?aid=${encodeURIComponent(String(identifiers.aid))}&cid=${encodeURIComponent(cid)}`
      });
    }

    return requests;
  }

  async function fetchJson(url) {
    try {
      const response = await fetch(url, {
        method: "GET",
        credentials: "include",
        headers: {
          Accept: "application/json, text/plain, */*"
        }
      });

      if (!response.ok) {
        addError("fetch_json", `HTTP ${response.status}`, { url });
        return {
          ok: false,
          status: response.status,
          json: null,
          error: `HTTP ${response.status}`
        };
      }

      return {
        ok: true,
        status: response.status,
        json: await response.json(),
        error: ""
      };
    } catch (error) {
      addError("fetch_json", String(error?.message || error), { url });
      return {
        ok: false,
        status: 0,
        json: null,
        error: String(error?.message || error)
      };
    }
  }

  function extractVideoIdentifiers() {
    const initialState = window.__INITIAL_STATE__ || {};
    const playInfo = window.__playinfo__ || {};
    const videoData = initialState?.videoData || {};
    const pages = Array.isArray(videoData?.pages) ? videoData.pages : [];
    const url = new URL(location.href);
    const currentPageNumber = Math.max(
      1,
      Number(url.searchParams.get("p") || initialState?.p || videoData?.p || 1)
    );
    const currentPage = pages[currentPageNumber - 1] || pages[0] || {};

    const bvid =
      extractBvidFromUrl(location.href) ||
      sanitizeText(initialState?.bvid || videoData?.bvid || initialState?.epInfo?.bvid || "");
    const aid =
      Number(initialState?.aid || videoData?.aid || initialState?.epInfo?.aid || 0) || 0;
    const cid =
      Number(
        initialState?.cid ||
        videoData?.cid ||
        initialState?.epInfo?.cid ||
        currentPage?.cid ||
        playInfo?.data?.dash?.cid ||
        url.searchParams.get("cid") ||
        0
      ) || 0;

    return {
      bvid,
      aid,
      cid
    };
  }

  function extractBvidFromUrl(url) {
    const match = String(url || "").match(/\/video\/(BV[0-9A-Za-z]+)/i);
    return sanitizeText(match?.[1] || "");
  }

  function normalizeTrackList(rawTracks, source) {
    if (!rawTracks) {
      return [];
    }

    const list = Array.isArray(rawTracks)
      ? rawTracks
      : Array.isArray(rawTracks?.subtitles)
        ? rawTracks.subtitles
        : Array.isArray(rawTracks?.list)
          ? rawTracks.list
          : [];

    return list
      .map((item) => ({
        lang: sanitizeText(item?.lan_doc || item?.lang || item?.lan || ""),
        langKey: sanitizeText(item?.lan || item?.lang_key || ""),
        trackType: Number(item?.type || 0) || 0,
        source: sanitizeText(source),
        sourceUrl: normalizeSubtitleUrl(item?.subtitle_url || item?.subtitleUrl || item?.url || "")
      }))
      .filter((item) => item.sourceUrl);
  }

  function dedupeTrackList(tracks) {
    const output = [];
    const seen = new Set();

    tracks.forEach((track) => {
      if (!track.sourceUrl || seen.has(track.sourceUrl)) {
        return;
      }
      seen.add(track.sourceUrl);
      output.push(track);
    });

    return output;
  }

  function scheduleRetry(reason) {
    if (state.retryCount >= 5) {
      addError("retry", "retry limit reached", { reason, retry_count: state.retryCount });
      pushDebug();
      return;
    }

    clearRetry();
    const delay = [800, 1500, 2500, 4000, 6000][state.retryCount] || 6000;
    state.retryCount += 1;
    state.retryTimer = window.setTimeout(() => {
      void collectOfficialSubtitles(`${reason}-retry-${state.retryCount}`);
    }, delay);
    state.debug.last_stage = "retry_scheduled";
    pushDebug();
  }

  function clearRetry() {
    if (state.retryTimer) {
      window.clearTimeout(state.retryTimer);
      state.retryTimer = 0;
    }
  }

  function emit(eventName, detail) {
    window.dispatchEvent(new CustomEvent(eventName, { detail }));
  }

  function createEmptyDebugState() {
    return {
      collector: "bilibili_official_subtitle_v1",
      page_url: location.href,
      last_reason: "",
      last_stage: "",
      identifiers: {},
      player_tracks_raw: [],
      api_attempts: [],
      final_track_list: [],
      fetched_bodies: [],
      errors: [],
      updated_at: new Date().toISOString()
    };
  }

  function startDebugRun(reason) {
    state.debug = createEmptyDebugState();
    state.debug.last_reason = reason;
    state.debug.page_url = location.href;
    state.debug.updated_at = new Date().toISOString();
  }

  function addError(step, message, context) {
    state.debug.errors.push({
      step,
      message: sanitizeText(message),
      context: context || {},
      at: new Date().toISOString()
    });
  }

  function pushDebug() {
    state.debug.updated_at = new Date().toISOString();
    emit(EVENTS.debug, state.debug);
  }

  function normalizeSubtitleUrl(url) {
    const text = sanitizeText(url);
    if (!text) {
      return "";
    }
    if (text.startsWith("//")) {
      return `https:${text}`;
    }
    if (text.startsWith("/")) {
      return `${location.origin}${text}`;
    }
    return text;
  }

  function sanitizeText(text) {
    return String(text || "").replace(/\u3000+/g, " ").replace(/\s+/g, " ").trim();
  }
})();
