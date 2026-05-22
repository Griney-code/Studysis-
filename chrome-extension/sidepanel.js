const TEXT = {
  waitingConnection: "等待连接",
  noVideoPage: "尚未检测到视频页面",
  openVideoTip: "请打开带有 HTML5 视频的网课页面",
  noSegment: "暂无分片数据",
  subtitlePlaceholder: "采集到的字幕会显示在这里",
  summaryPlaceholder: "暂无速览总结",
  noStructuredNotes: "暂无结构化笔记",
  noExamPoints: "暂无考点清单",
  noPageTitle: "未获取到页面标题",
  noTimeInfo: "暂无时间信息",
  noSubtitle: "该分片未抓取到字幕",
  noQuickSummary: "暂无速览总结",
  unnamedNote: "未命名章节",
  knowledgePoint: "章节导览",
  jumpTo: "跳转到",
  itemsSuffix: "条",
  loadingOverview: "正在生成内容摘要",
  loadingHint: "先整理页面线索和字幕，再给出首轮导览",
  loadingChapters: "正在整理章节内容",
  loadingChaptersHint: "章节卡片整理完成后会自动展示在这里",
  loadingExamPoints: "正在整理备考考点",
  loadingExamPointsHint: "章节完成后会同步提炼重点内容"
};

const STATUS_LABELS = {
  idle: "等待视频",
  ready: "已连接",
  running: "采集中",
  paused: "已暂停",
  warning: "采样中",
  error: "连接异常"
};

const elements = {
  statusBadge: document.getElementById("statusBadge"),
  pageTitle: document.getElementById("pageTitle"),
  pageMeta: document.getElementById("pageMeta"),
  segmentTime: document.getElementById("segmentTime"),
  segmentSubtitle: document.getElementById("segmentSubtitle"),
  quickSummary: document.getElementById("quickSummary"),
  notesList: document.getElementById("notesList"),
  examList: document.getElementById("examList"),
  notesCount: document.getElementById("notesCount"),
  examCount: document.getElementById("examCount")
};

let currentTabId = null;
let openedChapterIds = new Set();

document.addEventListener("DOMContentLoaded", () => {
  void initializePanel();
});

async function initializePanel() {
  chrome.runtime.onMessage.addListener((message) => {
    if (message?.type !== "SESSION_UPDATED") {
      return;
    }

    if (currentTabId && message.payload?.tabId !== currentTabId) {
      return;
    }

    renderSession(message.payload);
  });

  chrome.tabs.onActivated.addListener(() => {
    void loadActiveSession();
  });

  chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
    if (tabId === currentTabId && changeInfo.status === "complete") {
      void loadActiveSession();
    }
  });

  await loadActiveSession();
}

async function loadActiveSession() {
  const tabs = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
  currentTabId = tabs[0]?.id ?? null;

  if (!currentTabId) {
    renderSession(null);
    return;
  }

  const response = await chrome.runtime.sendMessage({
    type: "GET_SESSION",
    tabId: currentTabId
  });

  renderSession(response);
}

function renderSession(session) {
  rememberOpenedChapters();

  if (!session) {
    elements.statusBadge.textContent = TEXT.waitingConnection;
    elements.statusBadge.className = "status-badge idle";
    elements.pageTitle.textContent = TEXT.noVideoPage;
    elements.pageMeta.textContent = TEXT.openVideoTip;
    elements.segmentTime.textContent = TEXT.noSegment;
    elements.segmentSubtitle.textContent = TEXT.subtitlePlaceholder;
    renderQuickSummary(null);
    renderStructuredNotes(elements.notesList, [], TEXT.noStructuredNotes, null);
    renderList(elements.examList, [], TEXT.noExamPoints, null, null);
    elements.notesCount.textContent = `0 ${TEXT.itemsSuffix}`;
    elements.examCount.textContent = `0 ${TEXT.itemsSuffix}`;
    return;
  }

  elements.statusBadge.textContent = STATUS_LABELS[session.status] ?? "处理中";
  elements.statusBadge.className = `status-badge ${session.status ?? "idle"}`;
  elements.pageTitle.textContent = session.pageTitle || session.pageUrl || TEXT.noPageTitle;
  elements.pageMeta.textContent = session.error
    ? `${session.host || ""} | ${session.error}`
    : `${session.host || ""} | 已处理 ${session.processedSegments || 0} 个分片`;

  if (session.lastSegment) {
    elements.segmentTime.textContent = session.lastSegment.timeLabel || TEXT.noTimeInfo;
    elements.segmentSubtitle.textContent = session.lastSegment.subtitleText || TEXT.noSubtitle;
  } else {
    elements.segmentTime.textContent = TEXT.noSegment;
    elements.segmentSubtitle.textContent = TEXT.subtitlePlaceholder;
  }

  renderQuickSummary(session);

  const structuredNotes = session.notes?.structuredNotes ?? [];
  const examPoints = session.notes?.examPoints ?? [];

  renderStructuredNotes(elements.notesList, structuredNotes, TEXT.noStructuredNotes, session);
  renderList(
    elements.examList,
    examPoints,
    TEXT.noExamPoints,
    isExamPointsLoading(session, examPoints),
    {
      title: TEXT.loadingExamPoints,
      subtitle: TEXT.loadingExamPointsHint
    }
  );

  elements.notesCount.textContent = `${structuredNotes.length} ${TEXT.itemsSuffix}`;
  elements.examCount.textContent = `${examPoints.length} ${TEXT.itemsSuffix}`;
}

function renderQuickSummary(session) {
  if (!session) {
    elements.quickSummary.textContent = TEXT.summaryPlaceholder;
    return;
  }

  const overviewSummary = session.notes?.overviewSummary || session.notes?.quickSummary || "";

  if (isSummaryLoading(session, overviewSummary)) {
    elements.quickSummary.innerHTML = `
      <div class="summary-loading">
        <span class="summary-spinner" aria-hidden="true"></span>
        <div class="summary-loading-text">
          <span class="summary-loading-title">${TEXT.loadingOverview}</span>
          <span class="summary-loading-subtitle">${TEXT.loadingHint}</span>
        </div>
      </div>
    `;
    return;
  }

  elements.quickSummary.textContent = overviewSummary || TEXT.noQuickSummary;
}

function isSummaryLoading(session, overviewSummary) {
  if (session?.error) {
    return false;
  }
  if (overviewSummary) {
    return false;
  }
  return ["ready", "running", "warning"].includes(session.status);
}

function rememberOpenedChapters() {
  openedChapterIds = new Set(
    Array.from(document.querySelectorAll(".chapter-card[open]"))
      .map((element) => element.dataset.noteId)
      .filter(Boolean)
  );
}

function renderStructuredNotes(container, items, emptyText, session) {
  container.innerHTML = "";

  if (!items.length) {
    if (isStructuredNotesLoading(session, items)) {
      renderLoadingState(container, TEXT.loadingChapters, TEXT.loadingChaptersHint);
      return;
    }
    container.className = "note-list empty-state";
    container.textContent = emptyText;
    return;
  }

  container.className = "note-list";

  items.forEach((item, index) => {
    const noteId = getNoteId(item, index);
    const card = document.createElement("details");
    card.className = "chapter-card";
    card.dataset.noteId = noteId;
    if (openedChapterIds.has(noteId)) {
      card.open = true;
    }
    card.addEventListener("toggle", () => {
      if (card.open) {
        openedChapterIds.add(noteId);
      } else {
        openedChapterIds.delete(noteId);
      }
    });

    const summary = document.createElement("summary");
    summary.className = "chapter-summary";

    const header = document.createElement("div");
    header.className = "note-top";

    const titleWrap = document.createElement("div");
    titleWrap.className = "chapter-title-wrap";

    const title = document.createElement("h3");
    title.className = "note-title";
    title.textContent = item.title || TEXT.unnamedNote;

    const meta = document.createElement("div");
    meta.className = "chapter-meta";
    meta.textContent = `${item.category || TEXT.knowledgePoint} | ${item.timestamp || "00:00"}`;

    titleWrap.appendChild(title);
    titleWrap.appendChild(meta);

    const category = document.createElement("span");
    category.className = "note-category";
    category.textContent = item.category || TEXT.knowledgePoint;

    header.appendChild(titleWrap);
    header.appendChild(category);

    const preview = document.createElement("p");
    preview.className = "chapter-preview";
    const chapterParts = splitChapterContent(item.content || "");
    preview.textContent = chapterParts.preview;

    summary.appendChild(header);
    summary.appendChild(preview);

    const body = document.createElement("div");
    body.className = "chapter-body";

    const detail = document.createElement("p");
    detail.className = "note-content detail-content";
    detail.textContent =
      item.detail ||
      chapterParts.detail ||
      "这里会展示该章节的详细讲解，后续还会补充板书识别、公式识别和关键帧分析。";

    const future = document.createElement("div");
    future.className = "future-hint";
    future.textContent = "多模态增强预留：板书识别 / 公式识别 / 关键帧分析";

    const jumpButton = document.createElement("button");
    jumpButton.className = "jump-button";
    jumpButton.textContent = `${TEXT.jumpTo} ${item.timestamp || "00:00"}`;
    jumpButton.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      void jumpToVideo(item.seconds ?? 0);
    });

    body.appendChild(detail);
    body.appendChild(future);
    body.appendChild(jumpButton);

    card.appendChild(summary);
    card.appendChild(body);
    container.appendChild(card);
  });
}

function splitChapterContent(content) {
  const text = String(content || "").trim();
  if (!text) {
    return { preview: "", detail: "" };
  }

  const lines = text.split(/\n+/).map((line) => line.trim()).filter(Boolean);
  if (!lines.length) {
    return { preview: "", detail: "" };
  }

  if (lines.length === 1) {
    return { preview: lines[0], detail: "" };
  }

  return {
    preview: lines[0],
    detail: lines.slice(1).join("\n")
  };
}

function renderList(container, items, emptyText, isLoading = false, loadingCopy = null) {
  container.innerHTML = "";

  if (!items.length) {
    if (isLoading && loadingCopy) {
      renderLoadingState(container, loadingCopy.title, loadingCopy.subtitle);
      return;
    }
    container.className = "note-list empty-state";
    container.textContent = emptyText;
    return;
  }

  container.className = "note-list";

  items.forEach((item) => {
    const wrapper = document.createElement("article");
    wrapper.className = "note-item";

    const header = document.createElement("div");
    header.className = "note-top";

    const title = document.createElement("h3");
    title.className = "note-title";
    title.textContent = item.title || TEXT.unnamedNote;

    const category = document.createElement("span");
    category.className = "note-category";
    category.textContent = item.category || TEXT.knowledgePoint;

    header.appendChild(title);
    header.appendChild(category);

    const content = document.createElement("p");
    content.className = "note-content";
    content.textContent = item.content || "";

    const jumpButton = document.createElement("button");
    jumpButton.className = "jump-button";
    jumpButton.textContent = `${TEXT.jumpTo} ${item.timestamp || "00:00"}`;
    jumpButton.addEventListener("click", () => {
      void jumpToVideo(item.seconds ?? 0);
    });

    wrapper.appendChild(header);
    wrapper.appendChild(content);
    wrapper.appendChild(jumpButton);
    container.appendChild(wrapper);
  });
}

function renderLoadingState(container, title, subtitle) {
  container.className = "note-list";
  container.innerHTML = `
    <div class="list-loading-card">
      <div class="summary-loading">
        <span class="summary-spinner" aria-hidden="true"></span>
        <div class="summary-loading-text">
          <span class="summary-loading-title">${title}</span>
          <span class="summary-loading-subtitle">${subtitle}</span>
        </div>
      </div>
    </div>
  `;
}

function isStructuredNotesLoading(session, items) {
  if (!session || session.error || items.length) {
    return false;
  }
  const backendMessage = session.notes?.backendMessage || "";
  if (backendMessage.includes("整理章节内容")) {
    return true;
  }
  return ["ready", "running", "warning"].includes(session.status);
}

function isExamPointsLoading(session, items) {
  if (!session || session.error || items.length) {
    return false;
  }
  const backendMessage = session.notes?.backendMessage || "";
  if (backendMessage.includes("整理章节内容")) {
    return true;
  }
  return ["ready", "running", "warning"].includes(session.status);
}

function getNoteId(item, index) {
  return item.id || `${item.title || "note"}-${item.timestamp || "00:00"}-${index}`;
}

async function jumpToVideo(seconds) {
  if (!currentTabId) {
    return;
  }

  await chrome.runtime.sendMessage({
    type: "SEEK_VIDEO",
    tabId: currentTabId,
    seconds
  });
}
