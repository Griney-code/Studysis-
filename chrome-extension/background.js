const STORAGE_KEY_PREFIX = "studysis-session-";

chrome.runtime.onInstalled.addListener(async () => {
  await chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true });
});

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!message?.type) {
    return false;
  }

  if (message.type === "SYNC_SESSION") {
    void syncSession(message.payload, sender).then(sendResponse);
    return true;
  }

  if (message.type === "GET_SESSION") {
    void getSession(message.tabId).then(sendResponse);
    return true;
  }

  if (message.type === "SEEK_VIDEO") {
    void seekVideo(message.tabId, message.seconds).then(sendResponse);
    return true;
  }

  if (message.type === "FETCH_SUBTITLE_BODY") {
    void fetchSubtitleBody(message).then(sendResponse);
    return true;
  }

  return false;
});

chrome.tabs.onRemoved.addListener(async (tabId) => {
  await chrome.storage.local.remove(getStorageKey(tabId));
});

function getStorageKey(tabId) {
  return `${STORAGE_KEY_PREFIX}${tabId}`;
}

async function getActiveTabId() {
  const tabs = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
  return tabs[0]?.id ?? null;
}

async function getSession(tabId) {
  const targetTabId = tabId ?? (await getActiveTabId());
  if (!targetTabId) {
    return null;
  }

  const storageKey = getStorageKey(targetTabId);
  const result = await chrome.storage.local.get(storageKey);
  return result[storageKey] ?? null;
}

async function syncSession(payload, sender) {
  const tabId = sender.tab?.id ?? payload?.tabId;
  if (!tabId) {
    return { ok: false, error: "未找到当前标签页 ID" };
  }

  const storageKey = getStorageKey(tabId);
  const previous = (await chrome.storage.local.get(storageKey))[storageKey] ?? {};
  const isNewSession = Boolean(
    payload?.sessionId
    && previous.sessionId
    && payload.sessionId !== previous.sessionId
  );

  const previousVersion = getSessionVersion(previous);
  const incomingVersion = getPayloadVersion(payload, previousVersion);
  if (!isNewSession && incomingVersion < previousVersion) {
    return { ok: true, session: previous, ignored: true };
  }

  const mergedNotes = mergeNotes(isNewSession ? {} : previous.notes, payload.notes);

  const session = {
    tabId,
    sessionId: payload.sessionId ?? previous.sessionId ?? "",
    pageTitle: preferNonEmptyString(payload.source?.title, previous.pageTitle ?? ""),
    pageUrl: preferNonEmptyString(payload.source?.url, previous.pageUrl ?? ""),
    host: preferNonEmptyString(payload.source?.host, previous.host ?? ""),
    status: payload.status ?? previous.status ?? "idle",
    backendConnected: payload.backendConnected ?? previous.backendConnected ?? false,
    processedSegments: payload.processedSegments ?? previous.processedSegments ?? 0,
    error: payload.error ?? "",
    lastSegment: payload.lastSegment ?? previous.lastSegment ?? null,
    notes: mergedNotes,
    analysisRequestVersion: payload.analysisRequestVersion ?? previous.analysisRequestVersion ?? 0,
    sessionUpdatedAt: payload.sessionUpdatedAt ?? previous.sessionUpdatedAt ?? "",
    stateVersion: incomingVersion,
    lastUpdated: new Date().toISOString()
  };

  await chrome.storage.local.set({ [storageKey]: session });

  try {
    await chrome.runtime.sendMessage({
      type: "SESSION_UPDATED",
      payload: session
    });
  } catch (_error) {
    // Sidepanel may be closed; this should not interrupt collection.
  }

  return { ok: true, session };
}

async function seekVideo(tabId, seconds) {
  const targetTabId = tabId ?? (await getActiveTabId());
  if (!targetTabId) {
    return { ok: false, error: "当前没有可跳转的视频页面" };
  }

  await chrome.tabs.sendMessage(targetTabId, {
    type: "SEEK_VIDEO",
    seconds
  });

  return { ok: true };
}

async function fetchSubtitleBody(message) {
  const sourceUrl = typeof message?.sourceUrl === "string" ? message.sourceUrl.trim() : "";
  if (!sourceUrl) {
    return { ok: false, status: 0, error: "missing sourceUrl", payload: null };
  }

  try {
    const response = await fetch(sourceUrl, {
      method: "GET",
      credentials: "include",
      headers: {
        Accept: "application/json, text/plain, */*"
      }
    });

    if (!response.ok) {
      return {
        ok: false,
        status: response.status,
        error: `HTTP ${response.status}`,
        payload: null
      };
    }

    const payload = await response.json();
    return {
      ok: true,
      status: response.status,
      error: "",
      payload
    };
  } catch (error) {
    return {
      ok: false,
      status: 0,
      error: String(error?.message ?? error ?? "Failed to fetch"),
      payload: null
    };
  }
}

function mergeNotes(previousNotes = {}, incomingNotes = undefined) {
  if (!incomingNotes || typeof incomingNotes !== "object") {
    return previousNotes || {};
  }

  const structuredNotes = Array.isArray(incomingNotes.structuredNotes)
    ? mergeNoteArrays(previousNotes.structuredNotes || [], incomingNotes.structuredNotes)
    : previousNotes.structuredNotes || [];
  const detailedNotes = Array.isArray(incomingNotes.detailedNotes)
    ? mergeNoteArrays(previousNotes.detailedNotes || [], incomingNotes.detailedNotes)
    : previousNotes.detailedNotes || [];
  const examPoints = Array.isArray(incomingNotes.examPoints)
    ? mergeNoteArrays(previousNotes.examPoints || [], incomingNotes.examPoints)
    : previousNotes.examPoints || [];

  return {
    quickSummary:
      incomingNotes.quickSummary
      ?? incomingNotes.overviewSummary
      ?? previousNotes.quickSummary
      ?? "",
    overviewSummary:
      incomingNotes.overviewSummary
      ?? incomingNotes.quickSummary
      ?? previousNotes.overviewSummary
      ?? "",
    liveSummary: incomingNotes.liveSummary ?? previousNotes.liveSummary ?? "",
    structuredNotes,
    detailedNotes,
    examPoints,
    markdown: incomingNotes.markdown ?? previousNotes.markdown ?? "",
    backendMessage: incomingNotes.backendMessage ?? previousNotes.backendMessage ?? ""
  };
}

function mergeNoteArrays(previousItems = [], incomingItems = []) {
  if (!incomingItems.length) {
    return [];
  }

  const previousById = new Map(
    previousItems
      .filter((item) => item && typeof item === "object")
      .map((item, index) => [getNoteIdentity(item, index), item])
  );

  return incomingItems.map((item, index) => {
    if (!item || typeof item !== "object") {
      return item;
    }

    const noteId = getNoteIdentity(item, index);
    const previousItem = previousById.get(noteId) || {};
    return {
      ...previousItem,
      ...item
    };
  });
}

function getNoteIdentity(item, index) {
  if (typeof item?.id === "string" && item.id.trim()) {
    return item.id.trim();
  }
  if (typeof item?.noteId === "string" && item.noteId.trim()) {
    return item.noteId.trim();
  }
  return `${item?.title ?? "note"}-${item?.timestamp ?? "00:00"}-${index}`;
}

function getSessionVersion(session = {}) {
  const updatedAt = Date.parse(session.sessionUpdatedAt ?? "") || 0;
  const requestVersion = Number(session.analysisRequestVersion ?? 0) || 0;
  return updatedAt * 1000 + requestVersion;
}

function getPayloadVersion(payload = {}, fallbackVersion = 0) {
  const updatedAt = Date.parse(payload.sessionUpdatedAt ?? "") || 0;
  const requestVersion = Number(payload.analysisRequestVersion ?? 0) || 0;
  if (!updatedAt && !requestVersion) {
    return fallbackVersion;
  }
  return updatedAt * 1000 + requestVersion;
}

function preferNonEmptyString(value, fallback) {
  const next = typeof value === "string" ? value.trim() : "";
  return next || fallback || "";
}
