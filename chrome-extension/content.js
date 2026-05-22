const CONFIG = {
  backendUrl: "http://127.0.0.1:8000/api/v1/collect/segment",
  sessionsUrl: "http://127.0.0.1:8000/api/v1/sessions",
  attachDebounceMs: 600,
  backendTimeoutMs: 15000,
  analysisPollIntervalMs: 2000,
  analysisPollTimeoutMs: 10000
};

const EVENTS = {
  subtitleRequest: "studysis:bilibili-subtitle-request",
  subtitleMeta: "studysis:bilibili-subtitle-meta",
  subtitleBody: "studysis:bilibili-subtitle-body",
  subtitleDebug: "studysis:bilibili-subtitle-debug"
};

const TEXT = {
  noVideo: "当前页面未检测到可用视频",
  waitingBackend: "轻量模式：尚未向后端同步",
  backendUnavailablePrefix: "无法连接本地后端："
};

const state = {
  activeVideo: null,
  pageObserver: null,
  videoScanTimer: null,
  attachBestVideoTimer: null,
  pageUrl: getSessionPageUrl(),
  sessionId: createSessionId(),
  processedSegments: 0,
  lastKnownVideoTime: 0,
  backendConnected: false,
  lastSnapshotSignature: "",
  snapshotInFlight: false,
  extensionContextInvalidated: false,
  debugSyncTimer: null,
  officialSubtitleSent: false,
  officialSubtitleTracks: [],
  officialSubtitleTrackMap: new Map(),
  officialSubtitleMetaByUrl: new Map(),
  officialSubtitlePendingUrls: new Set(),
  bilibiliSubtitleDebug: null,
  analysisPollTimer: null,
  analysisPollInFlight: false
};

initCollector();

function initCollector() {
  initBilibiliSubtitleCapture();
  bindRuntimeMessage();
  attachBestVideo();
  observePageVideoChanges();
  window.addEventListener("beforeunload", detachActiveVideo);
}

function initBilibiliSubtitleCapture() {
  if (!isBilibiliHost()) {
    return;
  }

  state.bilibiliSubtitleDebug = createEmptySubtitleDebugState();
  bindBilibiliSubtitleEvents();
  requestBilibiliSubtitleCollection("page-init");
}

function bindRuntimeMessage() {
  try {
    chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
      if (message?.type === "SEEK_VIDEO") {
        seekCurrentVideo(message.seconds);
        sendResponse({ ok: true });
        return true;
      }
      return false;
    });
  } catch (error) {
    handleRuntimeError(error);
  }
}

function bindBilibiliSubtitleEvents() {
  window.addEventListener(EVENTS.subtitleMeta, (event) => {
    const tracks = Array.isArray(event?.detail?.tracks) ? event.detail.tracks : [];
    tracks.forEach((track) => {
      const sourceUrl = normalizeSubtitleUrl(track?.sourceUrl ?? "");
      if (!sourceUrl) {
        return;
      }
      state.officialSubtitleMetaByUrl.set(sourceUrl, {
        lang: sanitizeText(track?.lang ?? ""),
        langKey: sanitizeText(track?.langKey ?? ""),
        trackType: Number(track?.trackType ?? 0) || 0,
        source: sanitizeText(track?.source ?? "")
      });
    });
    void fetchOfficialSubtitleBodies(tracks);
  });

  window.addEventListener(EVENTS.subtitleBody, (event) => {
    const normalizedTrack = normalizeCapturedSubtitleTrack(event?.detail);
    if (!normalizedTrack) {
      return;
    }

    const existingSignature = state.officialSubtitleTrackMap.get(normalizedTrack.source_url)?.signature ?? "";
    if (existingSignature === normalizedTrack.signature) {
      return;
    }

    state.officialSubtitleTrackMap.set(normalizedTrack.source_url, normalizedTrack);
    state.officialSubtitleTracks = Array.from(state.officialSubtitleTrackMap.values()).map(stripTrackSignature);
    state.officialSubtitleSent = false;

    if (state.activeVideo && !state.snapshotInFlight) {
      void sendLightweightSnapshot("official-subtitle-captured");
    }
  });

  window.addEventListener(EVENTS.subtitleDebug, (event) => {
    state.bilibiliSubtitleDebug = normalizeSubtitleDebugPayload(event?.detail);
    scheduleDebugSnapshotSync();
  });
}

function scheduleDebugSnapshotSync() {
  if (!isBilibiliHost() || state.extensionContextInvalidated) {
    return;
  }

  if (state.debugSyncTimer) {
    window.clearTimeout(state.debugSyncTimer);
  }

  state.debugSyncTimer = window.setTimeout(() => {
    state.debugSyncTimer = null;
    void sendLightweightSnapshot("subtitle-debug", { allowWithoutVideo: true });
  }, 350);
}

function clearAnalysisPolling() {
  if (state.analysisPollTimer) {
    window.clearTimeout(state.analysisPollTimer);
    state.analysisPollTimer = null;
  }
  state.analysisPollInFlight = false;
}

function scheduleAnalysisPoll(delayMs = CONFIG.analysisPollIntervalMs) {
  if (state.extensionContextInvalidated || !state.sessionId) {
    return;
  }

  if (state.analysisPollTimer) {
    window.clearTimeout(state.analysisPollTimer);
  }

  state.analysisPollTimer = window.setTimeout(() => {
    state.analysisPollTimer = null;
    void pollBackendSession();
  }, delayMs);
}

async function pollBackendSession() {
  if (state.analysisPollInFlight || !state.sessionId || state.extensionContextInvalidated) {
    return;
  }

  state.analysisPollInFlight = true;

  try {
    const response = await fetchWithTimeout(
      `${CONFIG.sessionsUrl}/${encodeURIComponent(state.sessionId)}`,
      {
        method: "GET",
        headers: {
          Accept: "application/json"
        }
      },
      CONFIG.analysisPollTimeoutMs
    );

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const payload = await response.json();
    const sessionData = payload?.data ?? {};
    const analysisStatus = sessionData.analysis_status ?? sessionData.analysisStatus ?? "idle";
    const analysisMessage = sessionData.analysis_message ?? sessionData.analysisMessage ?? "";

    await sendRuntimeMessageSafe({
      type: "SYNC_SESSION",
      payload: {
        sessionId: sessionData.session_id ?? state.sessionId,
        source: {
          title: sessionData.page_title ?? "",
          url: sessionData.page_url ?? "",
          host: sessionData.host ?? ""
        },
        status: state.activeVideo?.paused ? "ready" : "running",
        backendConnected: true,
        processedSegments: state.processedSegments,
        error: "",
        lastSegment: null,
        notes: normalizeBackendNotes(
          {
            data: {
              notes: {
                ...(sessionData.notes ?? {}),
                backend_message:
                  sessionData.notes?.backend_message ??
                  sessionData.notes?.backendMessage ??
                  analysisMessage
              }
            }
          },
          state.lastKnownVideoTime
        )
      }
    });

    if (analysisStatus === "pending" || analysisStatus === "running") {
      scheduleAnalysisPoll();
      return;
    }

    clearAnalysisPolling();
  } catch (_error) {
    scheduleAnalysisPoll(CONFIG.analysisPollIntervalMs * 2);
  } finally {
    state.analysisPollInFlight = false;
  }
}

async function fetchOfficialSubtitleBodies(tracks) {
  if (!Array.isArray(tracks) || !tracks.length) {
    return;
  }

  for (const track of tracks) {
    const sourceUrl = normalizeSubtitleUrl(track?.sourceUrl ?? "");
    if (!sourceUrl) {
      continue;
    }
    if (state.officialSubtitleTrackMap.has(sourceUrl) || state.officialSubtitlePendingUrls.has(sourceUrl)) {
      continue;
    }

    state.officialSubtitlePendingUrls.add(sourceUrl);
    try {
      const response = await sendRuntimeMessageSafe({
        type: "FETCH_SUBTITLE_BODY",
        sourceUrl
      });
      applySubtitleBodyFetchResult(track, sourceUrl, response);
    } finally {
      state.officialSubtitlePendingUrls.delete(sourceUrl);
    }
  }
}

function applySubtitleBodyFetchResult(track, sourceUrl, response) {
  const debugState = ensureSubtitleDebugState();
  const payloadBody = Array.isArray(response?.payload?.body) ? response.payload.body : [];
  const fetchedBodyEntry = {
    source_url: sourceUrl,
    lang: sanitizeText(track?.lang ?? ""),
    lang_key: sanitizeText(track?.langKey ?? ""),
    track_type: Number(track?.trackType ?? 0) || 0,
    source: sanitizeText(track?.source ?? ""),
    ok: Boolean(response?.ok && payloadBody.length),
    http_status: Number(response?.status ?? 0) || 0,
    response_error: sanitizeText(response?.error ?? ""),
    segment_count: payloadBody.length
  };

  if (payloadBody.length) {
    fetchedBodyEntry.preview = payloadBody.slice(0, 3).map((item) => ({
      from: Number(item?.from ?? 0),
      to: Number(item?.to ?? 0),
      content: sanitizeText(item?.content ?? "")
    }));
  }

  upsertFetchedBody(debugState, fetchedBodyEntry);

  if (response?.ok && payloadBody.length) {
    debugState.last_stage = "subtitle_body_ready";
    state.bilibiliSubtitleDebug = cloneSubtitleDebugPayload(debugState);
    window.dispatchEvent(
      new CustomEvent(EVENTS.subtitleBody, {
        detail: {
          sourceUrl,
          lang: track?.lang ?? "",
          langKey: track?.langKey ?? "",
          trackType: Number(track?.trackType ?? 0) || 0,
          source: track?.source ?? "",
          payload: response.payload
        }
      })
    );
    scheduleDebugSnapshotSync();
    return;
  }

  debugState.last_stage = "subtitle_body_empty";
  if (fetchedBodyEntry.response_error) {
    debugState.errors.push({
      step: "subtitle_body_fetch",
      message: fetchedBodyEntry.response_error,
      context: { url: sourceUrl },
      at: new Date().toISOString()
    });
  }
  state.bilibiliSubtitleDebug = cloneSubtitleDebugPayload(debugState);
  scheduleDebugSnapshotSync();
}

function ensureSubtitleDebugState() {
  if (!state.bilibiliSubtitleDebug || typeof state.bilibiliSubtitleDebug !== "object") {
    state.bilibiliSubtitleDebug = createEmptySubtitleDebugState();
  }
  return state.bilibiliSubtitleDebug;
}

function upsertFetchedBody(debugState, entry) {
  const list = Array.isArray(debugState.fetched_bodies) ? debugState.fetched_bodies : [];
  const index = list.findIndex((item) => item?.source_url === entry.source_url);
  if (index >= 0) {
    list[index] = entry;
  } else {
    list.push(entry);
  }
  debugState.fetched_bodies = list;
  debugState.updated_at = new Date().toISOString();
}

function observePageVideoChanges() {
  if (!document.documentElement) {
    return;
  }

  state.pageObserver = new MutationObserver(() => {
    scheduleAttachBestVideo();
  });

  state.pageObserver.observe(document.documentElement, {
    childList: true,
    subtree: true
  });

  state.videoScanTimer = window.setInterval(() => {
    scheduleAttachBestVideo();
  }, 5000);
}

function requestBilibiliSubtitleCollection(reason) {
  if (!isBilibiliHost()) {
    return;
  }

  window.dispatchEvent(
    new CustomEvent(EVENTS.subtitleRequest, {
      detail: { reason }
    })
  );
}

function scheduleAttachBestVideo() {
  if (state.attachBestVideoTimer) {
    window.clearTimeout(state.attachBestVideoTimer);
  }

  state.attachBestVideoTimer = window.setTimeout(() => {
    state.attachBestVideoTimer = null;
    attachBestVideo();
  }, CONFIG.attachDebounceMs);
}

function attachBestVideo() {
  refreshSessionForPageChange();
  const candidate = findBestVideoElement();

  if (!candidate) {
    detachActiveVideo();
    void syncStatus({
      status: "idle",
      backendConnected: false,
      error: TEXT.noVideo
    });
    return;
  }

  if (candidate === state.activeVideo) {
    updatePlaybackClock(candidate.currentTime);
    return;
  }

  detachActiveVideo();
  state.activeVideo = candidate;
  updatePlaybackClock(candidate.currentTime);

  const onPlay = () => {
    updatePlaybackClock(candidate.currentTime);
    void syncStatus({
      status: "running",
      backendConnected: state.backendConnected,
      error: ""
    });
    void sendLightweightSnapshot("playback-start");
  };

  const onPause = () => {
    updatePlaybackClock(candidate.currentTime);
    void syncStatus({
      status: "paused",
      backendConnected: state.backendConnected,
      error: ""
    });
  };

  const onEnded = () => {
    updatePlaybackClock(candidate.currentTime);
    void syncStatus({
      status: "paused",
      backendConnected: state.backendConnected,
      error: ""
    });
  };

  const onSeeked = () => {
    updatePlaybackClock(candidate.currentTime);
    void sendLightweightSnapshot("seeked");
  };

  const onTimeUpdate = () => {
    updatePlaybackClock(candidate.currentTime);
  };

  const onEmptied = () => {
    detachActiveVideo();
    attachBestVideo();
  };

  candidate.__studysisHandlers = {
    onPlay,
    onPause,
    onEnded,
    onSeeked,
    onTimeUpdate,
    onEmptied
  };

  candidate.addEventListener("play", onPlay);
  candidate.addEventListener("pause", onPause);
  candidate.addEventListener("ended", onEnded);
  candidate.addEventListener("seeked", onSeeked);
  candidate.addEventListener("timeupdate", onTimeUpdate);
  candidate.addEventListener("emptied", onEmptied);

  requestBilibiliSubtitleCollection("video-attached");
  void syncStatus({
    status: candidate.paused ? "ready" : "running",
    backendConnected: state.backendConnected,
    error: state.backendConnected ? "" : TEXT.waitingBackend
  });
  void sendLightweightSnapshot("video-attached");
}

function detachActiveVideo() {
  if (state.attachBestVideoTimer) {
    window.clearTimeout(state.attachBestVideoTimer);
    state.attachBestVideoTimer = null;
  }

  if (state.activeVideo?.__studysisHandlers) {
    const handlers = state.activeVideo.__studysisHandlers;
    state.activeVideo.removeEventListener("play", handlers.onPlay);
    state.activeVideo.removeEventListener("pause", handlers.onPause);
    state.activeVideo.removeEventListener("ended", handlers.onEnded);
    state.activeVideo.removeEventListener("seeked", handlers.onSeeked);
    state.activeVideo.removeEventListener("timeupdate", handlers.onTimeUpdate);
    state.activeVideo.removeEventListener("emptied", handlers.onEmptied);
    delete state.activeVideo.__studysisHandlers;
  }

  state.activeVideo = null;
}

function findBestVideoElement() {
  const videos = Array.from(document.querySelectorAll("video"));
  if (!videos.length) {
    return null;
  }

  return (
    videos
      .filter((video) => {
        const rect = video.getBoundingClientRect();
        return rect.width >= 200 && rect.height >= 120 && rect.bottom > 0 && rect.right > 0;
      })
      .sort((left, right) => {
        const leftRect = left.getBoundingClientRect();
        const rightRect = right.getBoundingClientRect();
        return rightRect.width * rightRect.height - leftRect.width * leftRect.height;
      })[0] ?? null
  );
}

async function sendLightweightSnapshot(triggerReason, options = {}) {
  if ((!state.activeVideo && !options.allowWithoutVideo) || state.snapshotInFlight || state.extensionContextInvalidated) {
    return;
  }

  refreshSessionForPageChange();
  const payload = await buildSnapshotPayload(triggerReason);
  const signature = JSON.stringify(payload);
  if (signature === state.lastSnapshotSignature) {
    return;
  }

  state.snapshotInFlight = true;

  try {
    const response = await fetchWithTimeout(
      CONFIG.backendUrl,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify(payload)
      },
      CONFIG.backendTimeoutMs
    );

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const data = await response.json();
    const analysisStatus = data?.data?.analysis_status ?? data?.analysis_status ?? "idle";
    const analysisMessage = data?.data?.analysis_message ?? data?.analysis_message ?? "";
    state.lastSnapshotSignature = signature;
    state.backendConnected = true;
    state.processedSegments += 1;
    if (Array.isArray(payload.source?.official_subtitle_tracks) && payload.source.official_subtitle_tracks.length) {
      state.officialSubtitleSent = true;
    }

    await sendRuntimeMessageSafe({
      type: "SYNC_SESSION",
      payload: {
        sessionId: state.sessionId,
        source: payload.source,
        status: state.activeVideo?.paused ? "ready" : "running",
        backendConnected: true,
        processedSegments: state.processedSegments,
        error: "",
        lastSegment: {
          startTime: payload.segment.start_time,
          endTime: payload.segment.end_time,
          timeLabel: payload.segment.time_label,
          subtitleText: "",
          hasScreenshot: false,
          hasAudio: false
        },
        notes: normalizeBackendNotes(
          {
            ...data,
            data: {
              ...(data?.data ?? {}),
              notes: {
                ...(data?.data?.notes ?? data?.notes ?? {}),
                backend_message:
                  data?.data?.notes?.backend_message ??
                  data?.data?.notes?.backendMessage ??
                  data?.notes?.backend_message ??
                  data?.notes?.backendMessage ??
                  analysisMessage
              }
            }
          },
          payload.segment.end_time
        )
      }
    });

    if (analysisStatus === "pending" || analysisStatus === "running") {
      scheduleAnalysisPoll(1200);
    } else {
      clearAnalysisPolling();
    }
  } catch (error) {
    state.backendConnected = false;
    await syncStatus({
      status: state.activeVideo?.paused ? "ready" : "running",
      backendConnected: false,
      error: `${TEXT.backendUnavailablePrefix}${String(error?.message ?? error)}`
    });
  } finally {
    state.snapshotInFlight = false;
  }
}

async function buildSnapshotPayload(triggerReason) {
  const video = state.activeVideo;
  const currentTime = roundSeconds(getReliableVideoTime());
  const loadedUntil = roundSeconds(getBufferedEndTime(video));
  const duration = Number.isFinite(video?.duration) ? video.duration : 0;

  return {
    session_id: state.sessionId,
    source: await buildSourcePayload(video),
    segment: {
      start_time: 0,
      end_time: loadedUntil || currentTime,
      time_label: `${formatTime(0)} - ${formatTime(loadedUntil || currentTime)}`,
      subtitle_text: "",
      capture_stage: "preview",
      trigger_reason: triggerReason,
      is_preview_only: true,
      loaded_until: loadedUntil,
      loaded_fraction: duration > 0 ? Math.min(1, loadedUntil / duration) : 0
    }
  };
}

async function buildSourcePayload(video) {
  const title = isBilibiliHost() ? collectBilibiliVideoTitle() : document.title;
  const description = isBilibiliHost() ? collectBilibiliVideoDescription() : collectPageDescription();
  const chapterTitles = isBilibiliHost() ? [] : collectChapterTitles();
  const visibleTexts = isBilibiliHost() ? [] : collectVisibleTexts();
  const officialSubtitleTracks = !state.officialSubtitleSent ? cloneOfficialSubtitleTracks(state.officialSubtitleTracks) : [];
  const bufferedRanges = collectBufferedRanges(video);
  const subtitlePreview = !state.officialSubtitleSent ? buildOfficialSubtitlePreview(officialSubtitleTracks, 24) : [];

  return {
    title: title || document.title,
    url: getSessionPageUrl(),
    host: location.host,
    description,
    page_text: [title, description, ...chapterTitles, ...subtitlePreview].filter(Boolean).join(" ").slice(0, 2000),
    chapter_titles: chapterTitles,
    visible_texts: visibleTexts,
    subtitle_candidates: subtitlePreview,
    official_subtitle_tracks: state.officialSubtitleSent ? [] : officialSubtitleTracks,
    bilibili_subtitle_debug: isBilibiliHost() ? cloneSubtitleDebugPayload(state.bilibiliSubtitleDebug) : {},
    buffered_ranges: bufferedRanges
  };
}

function isBilibiliHost() {
  return location.host.includes("bilibili.com");
}

function collectBilibiliVideoTitle() {
  const selectors = [
    "h1.video-title",
    ".video-title",
    ".video-info-detail .title",
    ".video-info-detail h1",
    ".video-title-container h1"
  ];

  for (const selector of selectors) {
    const element = document.querySelector(selector);
    const text = sanitizeText(element?.textContent ?? "");
    if (text) {
      return text.slice(0, 200);
    }
  }

  const metaSelectors = [
    "meta[property='og:title']",
    "meta[name='title']",
    "meta[itemprop='name']"
  ];

  for (const selector of metaSelectors) {
    const element = document.querySelector(selector);
    const text = sanitizeText(element?.content ?? "");
    if (text) {
      return text.slice(0, 200);
    }
  }

  return sanitizeText(document.title.replace(/_哔哩哔哩_bilibili$/i, "")).slice(0, 200);
}

function collectBilibiliVideoDescription() {
  const selectors = [
    "#v_desc .desc-info-text",
    ".video-desc-container",
    ".video-info-detail .desc-info",
    ".video-info-detail .desc",
    "#description"
  ];

  for (const selector of selectors) {
    const element = document.querySelector(selector);
    const text = sanitizeText(element?.textContent ?? "");
    if (text) {
      return text.slice(0, 500);
    }
  }

  const metaSelectors = [
    "meta[property='og:description']",
    "meta[name='description']",
    "meta[itemprop='description']"
  ];

  for (const selector of metaSelectors) {
    const element = document.querySelector(selector);
    const text = sanitizeText(element?.content ?? "");
    if (text) {
      return text.slice(0, 500);
    }
  }

  return "";
}

function refreshSessionForPageChange() {
  const currentPageUrl = getSessionPageUrl();
  if (state.pageUrl === currentPageUrl) {
    return;
  }

  clearAnalysisPolling();
  state.pageUrl = currentPageUrl;
  state.sessionId = createSessionId();
  state.processedSegments = 0;
  state.lastKnownVideoTime = 0;
  state.lastSnapshotSignature = "";
  state.backendConnected = false;
  if (state.debugSyncTimer) {
    window.clearTimeout(state.debugSyncTimer);
    state.debugSyncTimer = null;
  }
  state.officialSubtitleSent = false;
  state.officialSubtitleTracks = [];
  state.officialSubtitleTrackMap = new Map();
  state.officialSubtitleMetaByUrl = new Map();
  state.officialSubtitlePendingUrls = new Set();
  state.bilibiliSubtitleDebug = createEmptySubtitleDebugState();
  requestBilibiliSubtitleCollection("page-change");
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

function getSessionPageUrl() {
  try {
    const url = new URL(location.href);

    if (isBilibiliHost()) {
      const normalized = new URL(`${url.origin}${url.pathname}`);
      const pagePart = sanitizeText(url.searchParams.get("p") ?? "");
      if (pagePart) {
        normalized.searchParams.set("p", pagePart);
      }
      return normalized.toString();
    }

    return url.toString();
  } catch (_error) {
    return location.href;
  }
}

function normalizeCapturedSubtitleTrack(detail) {
  const sourceUrl = normalizeSubtitleUrl(detail?.sourceUrl ?? "");
  const payloadBody = Array.isArray(detail?.payload?.body) ? detail.payload.body : [];
  const meta = state.officialSubtitleMetaByUrl.get(sourceUrl) || {};

  if (!sourceUrl || !payloadBody.length) {
    return null;
  }

  const segments = payloadBody
    .map((item) => ({
      from_seconds: roundSeconds(Number(item?.from ?? 0)),
      to_seconds: roundSeconds(Number(item?.to ?? 0)),
      content: sanitizeText(item?.content ?? "")
    }))
    .filter((item) => item.content);

  if (!segments.length) {
    return null;
  }

  const signature = JSON.stringify({
    sourceUrl,
    segmentCount: segments.length,
    first: segments[0]?.content ?? "",
    last: segments[segments.length - 1]?.content ?? ""
  });

  return {
    lang: sanitizeText(detail?.lang ?? meta.lang ?? ""),
    lang_key: sanitizeText(detail?.langKey ?? meta.langKey ?? ""),
    track_type: Number(detail?.trackType ?? meta.trackType ?? 0) || 0,
    source: sanitizeText(detail?.source ?? meta.source ?? ""),
    source_url: sourceUrl,
    segments,
    signature
  };
}

function stripTrackSignature(track) {
  return {
    lang: track.lang ?? "",
    lang_key: track.lang_key ?? "",
    track_type: Number(track.track_type ?? 0),
    source: track.source ?? "",
    source_url: track.source_url ?? "",
    segments: Array.isArray(track.segments) ? track.segments : []
  };
}

function cloneOfficialSubtitleTracks(tracks) {
  if (!Array.isArray(tracks)) {
    return [];
  }

  return tracks.map((track) => ({
    lang: track.lang ?? "",
    lang_key: track.lang_key ?? "",
    track_type: Number(track.track_type ?? 0),
    source: track.source ?? "",
    source_url: track.source_url ?? "",
    segments: Array.isArray(track.segments)
      ? track.segments.map((segment) => ({
          from_seconds: Number(segment?.from_seconds ?? 0),
          to_seconds: Number(segment?.to_seconds ?? 0),
          content: segment?.content ?? ""
        }))
      : []
  }));
}

function createEmptySubtitleDebugState() {
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

function normalizeSubtitleDebugPayload(payload) {
  const base = createEmptySubtitleDebugState();
  if (!payload || typeof payload !== "object") {
    return base;
  }

  return {
    ...base,
    collector: typeof payload.collector === "string" ? payload.collector : base.collector,
    page_url: typeof payload.page_url === "string" ? payload.page_url : location.href,
    last_reason: typeof payload.last_reason === "string" ? payload.last_reason : "",
    last_stage: typeof payload.last_stage === "string" ? payload.last_stage : "",
    identifiers: payload.identifiers && typeof payload.identifiers === "object" ? payload.identifiers : {},
    player_tracks_raw: Array.isArray(payload.player_tracks_raw) ? payload.player_tracks_raw : [],
    api_attempts: Array.isArray(payload.api_attempts) ? payload.api_attempts : [],
    final_track_list: Array.isArray(payload.final_track_list) ? payload.final_track_list : [],
    fetched_bodies: Array.isArray(payload.fetched_bodies) ? payload.fetched_bodies : [],
    errors: Array.isArray(payload.errors) ? payload.errors : [],
    updated_at: typeof payload.updated_at === "string" ? payload.updated_at : new Date().toISOString()
  };
}

function cloneSubtitleDebugPayload(payload) {
  if (!payload || typeof payload !== "object") {
    return {};
  }
  try {
    return JSON.parse(JSON.stringify(payload));
  } catch (_error) {
    return {};
  }
}

function buildOfficialSubtitlePreview(tracks, limit) {
  if (!Array.isArray(tracks) || !tracks.length) {
    return [];
  }

  const preview = [];
  for (const track of tracks) {
    const segments = Array.isArray(track?.segments) ? track.segments : [];
    for (const segment of segments) {
      const text = sanitizeText(segment?.content ?? "");
      if (!text) {
        continue;
      }
      preview.push(text);
      if (preview.length >= limit) {
        return dedupeTexts(preview);
      }
    }
  }

  return dedupeTexts(preview);
}

function collectPageDescription() {
  const selectors = [
    "meta[name='description']",
    "meta[property='og:description']",
    "meta[name='twitter:description']",
    "#description",
    ".video-desc-container",
    ".desc-info"
  ];

  for (const selector of selectors) {
    const element = document.querySelector(selector);
    const text = sanitizeText(element?.content ?? element?.textContent ?? "");
    if (text) {
      return text.slice(0, 500);
    }
  }

  return "";
}

function collectChapterTitles() {
  const selectors = [
    "[data-marker='part-item']",
    ".video-section-card__info-title",
    ".pod-item .title-txt",
    ".multi-page .part",
    ".list-box li",
    "[class*='chapter']",
    "[class*='outline']"
  ];
  const items = [];

  selectors.forEach((selector) => {
    document.querySelectorAll(selector).forEach((element) => {
      const text = sanitizeText(element.textContent ?? "");
      if (text) {
        items.push(text);
      }
    });
  });

  return dedupeTexts(items).slice(0, 8);
}

function collectVisibleTexts() {
  const selectors = ["h1", "h2", "h3", ".video-title", ".title", ".course-title", ".lesson-title"];
  const items = [];

  selectors.forEach((selector) => {
    document.querySelectorAll(selector).forEach((element) => {
      if (!(element instanceof HTMLElement)) {
        return;
      }
      const rect = element.getBoundingClientRect();
      if (rect.width <= 0 || rect.height <= 0) {
        return;
      }
      const text = sanitizeText(element.textContent ?? "");
      if (text) {
        items.push(text);
      }
    });
  });

  return dedupeTexts(items).slice(0, 8);
}

function collectBufferedRanges(video) {
  if (!video?.buffered) {
    return [];
  }

  const ranges = [];
  for (let index = 0; index < video.buffered.length; index += 1) {
    ranges.push(`${formatTime(video.buffered.start(index))} - ${formatTime(video.buffered.end(index))}`);
  }
  return ranges.slice(0, 4);
}

function getBufferedEndTime(video) {
  if (!video?.buffered || video.buffered.length === 0) {
    return getReliableVideoTime();
  }

  try {
    return video.buffered.end(video.buffered.length - 1);
  } catch (_error) {
    return getReliableVideoTime();
  }
}

async function syncStatus({ status, backendConnected, error }) {
  const title = getCurrentPageTitle();
  return await sendRuntimeMessageSafe({
    type: "SYNC_SESSION",
    payload: {
      sessionId: state.sessionId,
      source: {
        title,
        url: location.href,
        host: location.host
      },
      status,
      backendConnected,
      processedSegments: state.processedSegments,
      error,
      notes: {
        quickSummary: "",
        overviewSummary: "",
        liveSummary: "",
        structuredNotes: [],
        detailedNotes: [],
        examPoints: [],
        markdown: "",
        backendMessage: ""
      }
    }
  });
}

function getCurrentPageTitle() {
  if (isBilibiliHost()) {
    return collectBilibiliVideoTitle() || sanitizeText(document.title);
  }
  return sanitizeText(document.title);
}

function normalizeBackendNotes(response, fallbackSeconds) {
  const notes = response?.data?.notes ?? response?.notes ?? {};
  return {
    quickSummary: notes.quick_summary ?? notes.quickSummary ?? notes.overview_summary ?? "",
    overviewSummary: notes.overview_summary ?? notes.overviewSummary ?? notes.quick_summary ?? "",
    liveSummary: notes.live_summary ?? notes.liveSummary ?? "",
    structuredNotes: normalizeNoteArray(notes.structured_notes ?? notes.structuredNotes ?? [], fallbackSeconds),
    detailedNotes: normalizeNoteArray(notes.detailed_notes ?? notes.detailedNotes ?? [], fallbackSeconds),
    examPoints: normalizeNoteArray(notes.exam_points ?? notes.examPoints ?? [], fallbackSeconds),
    markdown: notes.markdown ?? "",
    backendMessage: notes.backend_message ?? notes.backendMessage ?? ""
  };
}

function normalizeNoteArray(items, fallbackSeconds) {
  if (!Array.isArray(items)) {
    return [];
  }

  return items.map((item, index) => ({
    id: item.note_id ?? item.noteId ?? `${index}`,
    title: item.title ?? `笔记 ${index + 1}`,
    content: item.content ?? "",
    detail: item.detail ?? "",
    category: item.category ?? "章节导览",
    timestamp: item.timestamp ?? formatTime(fallbackSeconds),
    seconds: typeof item.seconds === "number" ? item.seconds : fallbackSeconds
  }));
}

function seekCurrentVideo(seconds) {
  if (!state.activeVideo || typeof seconds !== "number") {
    return;
  }

  state.activeVideo.currentTime = Math.max(0, seconds);
  updatePlaybackClock(state.activeVideo.currentTime);
}

function updatePlaybackClock(seconds) {
  if (typeof seconds === "number" && Number.isFinite(seconds)) {
    state.lastKnownVideoTime = Math.max(0, seconds);
  }
}

function getReliableVideoTime() {
  if (!state.activeVideo || Number.isNaN(state.activeVideo.currentTime)) {
    return state.lastKnownVideoTime || 0;
  }
  return Math.max(state.activeVideo.currentTime, state.lastKnownVideoTime || 0);
}

function sanitizeText(text) {
  return String(text ?? "")
    .replace(/\u3000+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function dedupeTexts(items) {
  const seen = new Set();
  const output = [];

  items.forEach((item) => {
    const text = sanitizeText(item);
    if (!text || seen.has(text)) {
      return;
    }
    seen.add(text);
    output.push(text);
  });

  return output;
}

async function fetchWithTimeout(url, options, timeoutMs) {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);

  try {
    return await fetch(url, {
      ...options,
      signal: controller.signal
    });
  } finally {
    window.clearTimeout(timer);
  }
}

async function sendRuntimeMessageSafe(message) {
  if (state.extensionContextInvalidated) {
    return null;
  }

  const runtime = globalThis.chrome?.runtime;
  if (!runtime?.sendMessage) {
    state.extensionContextInvalidated = true;
    return null;
  }

  try {
    return await runtime.sendMessage(message);
  } catch (error) {
    handleRuntimeError(error);
    return null;
  }
}

function handleRuntimeError(error) {
  const message = String(error?.message ?? error ?? "");
  if (!message.includes("Extension context invalidated")) {
    return;
  }

  state.extensionContextInvalidated = true;

  if (state.pageObserver) {
    state.pageObserver.disconnect();
    state.pageObserver = null;
  }

  if (state.videoScanTimer) {
    window.clearInterval(state.videoScanTimer);
    state.videoScanTimer = null;
  }
}

function formatTime(seconds) {
  const safeSeconds = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(safeSeconds / 3600);
  const minutes = Math.floor((safeSeconds % 3600) / 60);
  const remainSeconds = safeSeconds % 60;

  if (hours > 0) {
    return [hours, minutes, remainSeconds].map((value) => String(value).padStart(2, "0")).join(":");
  }

  return [minutes, remainSeconds].map((value) => String(value).padStart(2, "0")).join(":");
}

function roundSeconds(value) {
  return Number(Math.max(0, value || 0).toFixed(2));
}

function createSessionId() {
  return `studysis-${location.host}-${Date.now()}`;
}
