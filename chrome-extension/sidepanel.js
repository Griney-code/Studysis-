const TEXT = {
  waitingConnection: "等待连接",
  noVideoPage: "尚未检测到视频页面",
  openVideoTip: "请打开带有 HTML5 视频的网页页面",
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
  loadingChaptersHint: "章节卡片整理完成后会自动显示在这里",
  loadingExamPoints: "正在整理备考考点",
  loadingExamPointsHint: "章节完成后会同步提炼重点内容",
  visualEvidenceTitle: "板书识别",
  visualBoardLabel: "板书识别",
  visualFormulaLabel: "公式提取",
  visualDiagramLabel: "图示元素",
  visualUncertainLabel: "识别备注",
  visualImageLabel: "关键帧证据"
};

const STATUS_LABELS = {
  idle: "等待视频",
  ready: "已连接",
  running: "采集中",
  paused: "已暂停",
  warning: "采样中",
  error: "连接异常"
};

const VISUAL_MARKERS = {
  visualSummary: ["关键帧补充："],
  boardNotes: ["板书识别：", "板书要点："],
  formulaPoints: ["公式提取：", "公式/图示："],
  diagramElements: ["图示元素："],
  uncertainParts: ["识别备注："],
  imageUrls: ["关键帧图片："]
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
    renderList(elements.examList, [], TEXT.noExamPoints, false, null);
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
  if (session?.error || overviewSummary) {
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

    const detailSections = splitDetailSections(item.detail || chapterParts.detail || "");
    const visualData = mergeVisualEvidence(detailSections.visual, item.imageUrls ?? []);
    const detail = document.createElement("p");
    detail.className = "note-content detail-content";
    detail.textContent = detailSections.body || "这里会展示该章节的详细讲解。";
    body.appendChild(detail);

    const visualEvidence = createVisualEvidenceBlock(visualData);
    if (visualEvidence) {
      body.appendChild(visualEvidence);
    }

    const jumpButton = document.createElement("button");
    jumpButton.className = "jump-button";
    jumpButton.textContent = `${TEXT.jumpTo} ${item.timestamp || "00:00"}`;
    jumpButton.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      void jumpToVideo(item.seconds ?? 0);
    });

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

function splitDetailSections(detailText) {
  const text = String(detailText || "").trim();
  if (!text) {
    return { body: "", visual: null };
  }

  const lines = text.split(/\n+/).map((line) => line.trim()).filter(Boolean);
  const bodyLines = [];
  const visual = {
    visualSummary: "",
    detailAppendix: [],
    boardNotes: [],
    formulaPoints: [],
    diagramElements: [],
    uncertainParts: [],
    imageUrls: []
  };
  let currentSection = "body";

  lines.forEach((line) => {
    const matchedMarker = Object.entries(VISUAL_MARKERS).find(([, markers]) =>
      markers.some((marker) => line.startsWith(marker))
    );
    if (matchedMarker) {
      const [sectionKey, markers] = matchedMarker;
      const markerText = markers.find((marker) => line.startsWith(marker)) || "";
      currentSection = sectionKey;
      const value = line.slice(markerText.length).trim();
      if (sectionKey === "visualSummary") {
        visual.visualSummary = value;
      } else if (sectionKey === "imageUrls") {
        visual.imageUrls.push(...splitDelimitedItems(value));
      } else if (value) {
        visual[sectionKey].push(...splitDelimitedItems(value));
      }
      return;
    }

    if (currentSection === "visualSummary") {
      visual.detailAppendix.push(line);
      return;
    }

    if (
      currentSection === "boardNotes"
      || currentSection === "formulaPoints"
      || currentSection === "diagramElements"
      || currentSection === "uncertainParts"
    ) {
      visual[currentSection].push(...splitDelimitedItems(line));
      return;
    }

    if (currentSection === "imageUrls") {
      visual.imageUrls.push(...splitDelimitedItems(line));
      return;
    }

    bodyLines.push(line);
  });

  const hasVisualEvidence = Boolean(
    visual.visualSummary ||
    visual.detailAppendix.length ||
    visual.boardNotes.length ||
    visual.formulaPoints.length ||
    visual.diagramElements.length ||
    visual.uncertainParts.length ||
    visual.imageUrls.length
  );

  return {
    body: bodyLines.join("\n"),
    visual: hasVisualEvidence ? visual : null
  };
}

function mergeVisualEvidence(visual, imageUrls) {
  const normalizedImageUrls = normalizeImageUrls(imageUrls);

  if (!visual && !normalizedImageUrls.length) {
    return null;
  }

  if (!visual) {
    return {
      visualSummary: "",
      detailAppendix: [],
      boardNotes: [],
      formulaPoints: [],
      diagramElements: [],
      uncertainParts: [],
      imageUrls: normalizedImageUrls
    };
  }

  return {
    ...visual,
    imageUrls: dedupeItems([...(visual.imageUrls ?? []), ...normalizedImageUrls])
  };
}

function normalizeImageUrls(items) {
  if (!Array.isArray(items)) {
    return [];
  }

  return dedupeItems(
    items
      .map((item) => String(item || "").trim())
      .filter(Boolean)
  );
}

function splitDelimitedItems(text) {
  return String(text || "")
    .split("；")
    .map((item) => item.trim())
    .filter(Boolean);
}

function createVisualEvidenceBlock(visual) {
  if (!visual) {
    return null;
  }

  const wrapper = document.createElement("section");
  wrapper.className = "visual-evidence";

  const title = document.createElement("div");
  title.className = "visual-evidence-title";
  title.textContent = TEXT.visualEvidenceTitle;
  wrapper.appendChild(title);

  if (visual.visualSummary) {
    const summary = document.createElement("p");
    summary.className = "visual-evidence-summary";
    summary.textContent = visual.visualSummary;
    wrapper.appendChild(summary);
  }

  if (visual.detailAppendix.length) {
    const appendix = document.createElement("p");
    appendix.className = "visual-evidence-detail";
    appendix.textContent = visual.detailAppendix.join("\n");
    wrapper.appendChild(appendix);
  }

  if (visual.boardNotes.length) {
    wrapper.appendChild(createVisualEvidenceList(TEXT.visualBoardLabel, visual.boardNotes));
  }

  if (visual.formulaPoints.length) {
    wrapper.appendChild(createVisualEvidenceList(TEXT.visualFormulaLabel, visual.formulaPoints));
  }

  if (visual.diagramElements.length) {
    wrapper.appendChild(createVisualEvidenceList(TEXT.visualDiagramLabel, visual.diagramElements));
  }

  if (visual.uncertainParts.length) {
    wrapper.appendChild(createVisualEvidenceList(TEXT.visualUncertainLabel, visual.uncertainParts));
  }

  if (visual.imageUrls.length) {
    wrapper.appendChild(createVisualEvidenceImages(TEXT.visualImageLabel, visual.imageUrls));
  }

  return wrapper;
}

function createVisualEvidenceList(label, items) {
  const section = document.createElement("div");
  section.className = "visual-evidence-group";

  const heading = document.createElement("div");
  heading.className = "visual-evidence-label";
  heading.textContent = label;
  section.appendChild(heading);

  const list = document.createElement("ul");
  list.className = "visual-evidence-list";

  items.forEach((item) => {
    const listItem = document.createElement("li");
    listItem.textContent = item;
    list.appendChild(listItem);
  });

  section.appendChild(list);
  return section;
}

function createVisualEvidenceImages(label, imageUrls) {
  const section = document.createElement("details");
  section.className = "visual-evidence-group visual-evidence-images";

  const heading = document.createElement("summary");
  heading.className = "visual-evidence-label";
  heading.textContent = label;
  section.appendChild(heading);

  const gallery = document.createElement("div");
  gallery.className = "visual-evidence-gallery";

  imageUrls.forEach((url, index) => {
    if (!url) {
      return;
    }
    const image = document.createElement("img");
    image.className = "visual-evidence-image";
    image.src = url;
    image.alt = `关键帧 ${index + 1}`;
    image.loading = "lazy";
    gallery.appendChild(image);
  });

  section.appendChild(gallery);
  return section;
}

function splitVisualItems(text) {
  return String(text || "")
    .split("；")
    .map((item) => item.trim())
    .filter(Boolean);
}

function dedupeItems(items) {
  return Array.from(new Set((items || []).filter(Boolean)));
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
  return item.id || item.noteId || `${item.title || "note"}-${item.timestamp || "00:00"}-${index}`;
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
