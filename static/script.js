let uploadedFiles = [];
let isUploading = false;

function apiUrl(path) {
    const base = (window.RAG_API_BASE_URL || "").replace(/\/$/, "");
    return `${base}${path}`;
}

if (typeof marked !== "undefined") {
    marked.setOptions({
        breaks: true,
        gfm: true,
    });
}

function formatTime(date = new Date()) {
    return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function updateDocCount() {
    const count = uploadedFiles.length;
    const label = document.getElementById("docCount");
    const dot = document.querySelector(".status-dot");
    const pill = document.getElementById("docCountPill");
    const headerStatus = document.getElementById("headerStatus");
    const chatBox = document.getElementById("chatBox");

    if (label) {
        label.textContent = count === 0
            ? "No documents yet"
            : count === 1
                ? "1 document active"
                : `${count} documents active`;
    }

    if (dot) dot.classList.toggle("active", count > 0);
    if (headerStatus) headerStatus.classList.toggle("active", count > 0);

    if (pill) {
        pill.textContent = count;
        pill.classList.toggle("has-docs", count > 0);
    }

    if (chatBox) {
        chatBox.classList.toggle("disabled", count === 0);
    }
}

function showToast(message, type = "success") {
    const container = document.getElementById("toastContainer");
    const toast = document.createElement("div");
    toast.className = `toast ${type}`;
    toast.textContent = message;
    container.appendChild(toast);

    setTimeout(() => {
        toast.classList.add("removing");
        setTimeout(() => toast.remove(), 300);
    }, 3200);
}

function removeWelcomeCard() {
    const welcome = document.getElementById("welcomeCard");
    if (welcome) welcome.remove();
}

function restoreWelcomeCard() {
    const chat = document.getElementById("chatTranscript");
    if (document.getElementById("welcomeCard")) return;

    chat.insertAdjacentHTML("beforeend", `
        <div class="welcome-card" id="welcomeCard">
            <div class="welcome-badge">AI Document Assistant</div>
            <div class="welcome-icon">
                <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
            </div>
            <h2>Ask anything about your PDF</h2>
            <p>Upload a resume, report, or manual — then get clear, tailored answers grounded in your document content.</p>
            <div class="how-it-works">
                <div class="how-step"><span class="how-num">1</span><div><strong>Upload</strong><span>Drop a PDF in the sidebar</span></div></div>
                <div class="how-step"><span class="how-num">2</span><div><strong>Ask</strong><span>Type your question below</span></div></div>
                <div class="how-step"><span class="how-num">3</span><div><strong>Get answers</strong><span>Receive human-readable responses</span></div></div>
            </div>
            <div class="suggestions">
                <span class="suggestion-label">Quick prompts</span>
                <div class="suggestion-grid">
                    <button class="suggestion-chip" onclick="useSuggestion('What is this document about?')">What is this about?</button>
                    <button class="suggestion-chip" onclick="useSuggestion('Summarize the key points')">Summarize key points</button>
                    <button class="suggestion-chip" onclick="useSuggestion('List all skills mentioned')">List all skills</button>
                    <button class="suggestion-chip" onclick="useSuggestion('Explain the main project in detail')">Explain a project</button>
                </div>
            </div>
        </div>
    `);
}

function appendMessage(role, content, isError = false, sources = []) {
    const chat = document.getElementById("chatMessages");
    const transcript = document.getElementById("chatTranscript");
    const row = document.createElement("div");
    row.className = `message-row ${role}`;

    const avatar = document.createElement("div");
    avatar.className = "message-avatar";
    avatar.textContent = role === "user" ? "You" : "AI";

    const contentWrap = document.createElement("div");
    contentWrap.className = "message-content";

    const bubble = document.createElement("div");
    bubble.className = `message-bubble${isError ? " error" : ""}`;

    if (role === "bot" && !isError) {
        bubble.innerHTML = marked.parse(content);
        const sourceControl = document.createElement("div");
        sourceControl.className = "source-control";

        const sourceButton = document.createElement("button");
        sourceButton.className = "source-dot";
        sourceButton.type = "button";
        sourceButton.setAttribute("aria-label", "Show answer sources");
        sourceButton.setAttribute("aria-expanded", "false");
        sourceButton.title = "Answer sources";

        const sourcePopover = document.createElement("div");
        sourcePopover.className = "source-popover";
        sourcePopover.setAttribute("role", "tooltip");
        sourcePopover.id = `sources-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
        sourceButton.setAttribute("aria-describedby", sourcePopover.id);

        const sourceHeading = document.createElement("strong");
        sourceHeading.textContent = "Sources";
        sourcePopover.appendChild(sourceHeading);

        if (!sources.length) {
            const noSources = document.createElement("span");
            noSources.className = "source-pages";
            noSources.textContent = "No PDF source pages were returned for this answer.";
            sourcePopover.appendChild(noSources);
        } else {
            sources.forEach((source) => {
                const item = document.createElement("div");
                item.className = "source-item";

                const name = document.createElement("span");
                name.className = "source-name";
                name.textContent = source.source || "Uploaded PDF";
                item.appendChild(name);

                const pages = Array.isArray(source.pages) ? source.pages : [];
                if (pages.length) {
                    const pageLabel = document.createElement("span");
                    pageLabel.className = "source-pages";
                    pageLabel.textContent = `Page${pages.length === 1 ? "" : "s"} ${pages.join(", ")}`;
                    item.appendChild(pageLabel);
                }
                sourcePopover.appendChild(item);
            });
        }

        sourceControl.addEventListener("mouseenter", () => sourceButton.setAttribute("aria-expanded", "true"));
        sourceControl.addEventListener("mouseleave", () => sourceButton.setAttribute("aria-expanded", "false"));
        sourceButton.addEventListener("focus", () => sourceButton.setAttribute("aria-expanded", "true"));
        sourceButton.addEventListener("blur", () => sourceButton.setAttribute("aria-expanded", "false"));
        sourceControl.append(sourceButton, sourcePopover);
        bubble.appendChild(sourceControl);
    } else {
        bubble.textContent = content;
    }

    const meta = document.createElement("div");
    meta.className = "message-meta";

    const time = document.createElement("span");
    time.className = "message-time";
    time.textContent = formatTime();
    meta.appendChild(time);

    if (role === "bot" && !isError) {
        const copyBtn = document.createElement("button");
        copyBtn.className = "copy-btn";
        copyBtn.innerHTML = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg> Copy`;
        copyBtn.onclick = () => {
            navigator.clipboard.writeText(content).then(() => {
                copyBtn.classList.add("copied");
                copyBtn.textContent = "Copied!";
                setTimeout(() => {
                    copyBtn.classList.remove("copied");
                    copyBtn.innerHTML = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg> Copy`;
                }, 2000);
            });
        };
        meta.appendChild(copyBtn);
    }

    contentWrap.appendChild(bubble);
    contentWrap.appendChild(meta);
    row.appendChild(avatar);
    row.appendChild(contentWrap);
    transcript.appendChild(row);
    chat.scrollTop = chat.scrollHeight;

    return row;
}

function showTypingIndicator() {
    const chat = document.getElementById("chatMessages");
    const transcript = document.getElementById("chatTranscript");
    const row = document.createElement("div");
    row.className = "message-row bot";
    row.id = "typingIndicator";
    row.innerHTML = `
        <div class="message-avatar">AI</div>
        <div class="message-content">
            <div class="message-bubble">
                <div class="typing-indicator"><span></span><span></span><span></span></div>
            </div>
        </div>
    `;
    transcript.appendChild(row);
    chat.scrollTop = chat.scrollHeight;
}

function hideTypingIndicator() {
    document.getElementById("typingIndicator")?.remove();
}

function addDocumentToList(filename, chunks) {
    const list = document.getElementById("documentList");
    document.getElementById("emptyDocState")?.remove();

    const li = document.createElement("li");
    li.className = "doc-item";
    li.dataset.filename = filename;
    li.innerHTML = `
        <span class="doc-item-icon">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
        </span>
        <div class="doc-item-info">
            <span class="doc-item-name" title="${filename}">${filename}</span>
            <span class="doc-item-meta">${chunks ? chunks + " chunks indexed" : "Ready for questions"}</span>
        </div>
        <button class="doc-item-remove" data-remove="${encodeURIComponent(filename)}" title="Remove from session" aria-label="Remove document">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
        </button>
    `;
    list.appendChild(li);

    li.querySelector(".doc-item-remove")?.addEventListener("click", () => {
        removeDocument(filename);
    });
}

function removeDocument(filename) {
    uploadedFiles = uploadedFiles.filter((f) => f !== filename);
    document.querySelector(`.doc-item[data-filename="${CSS.escape(filename)}"]`)?.remove();

    if (uploadedFiles.length === 0) {
        const list = document.getElementById("documentList");
        list.innerHTML = `
            <li class="empty-state" id="emptyDocState">
                <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
                <p>No documents uploaded</p>
                <span>Upload a PDF to start chatting</span>
            </li>
        `;
    }

    updateDocCount();
    showToast(`Removed ${filename}`, "success");
}

function setUploadStatus(message, type = "") {
    const status = document.getElementById("uploadStatus");
    status.textContent = message;
    status.className = `upload-status${type ? ` ${type}` : ""}`;
}

function useSuggestion(text) {
    const input = document.getElementById("question");
    input.value = text;
    input.focus();

    if (uploadedFiles.length > 0) {
        askQuestion();
    } else {
        showToast("Upload a PDF first, then try this prompt", "error");
    }
}

function clearChat() {
    const chat = document.getElementById("chatMessages");
    const transcript = document.getElementById("chatTranscript");
    transcript.querySelectorAll(":scope > .message-row").forEach((row) => row.remove());
    document.getElementById("welcomeCard")?.remove();
    restoreWelcomeCard();
    chat.scrollTop = 0;
    showToast("Chat cleared", "success");
}

function resizeQuestionInput() {
    const input = document.getElementById("question");
    input.style.height = "auto";
    const maxHeight = 200;
    input.style.height = `${Math.min(input.scrollHeight, maxHeight)}px`;
    input.style.overflowY = input.scrollHeight > maxHeight ? "auto" : "hidden";
}

function toggleSidebar(open) {
    const sidebar = document.getElementById("sidebar");
    const overlay = document.getElementById("sidebarOverlay");
    const isOpen = open ?? !sidebar.classList.contains("open");
    sidebar.classList.toggle("open", isOpen);
    overlay.classList.toggle("visible", isOpen);
}

async function uploadFile() {
    const fileInput = document.getElementById("fileInput");
    const file = fileInput.files[0];

    if (!file) {
        setUploadStatus("Please select a PDF file first.", "error");
        return;
    }

    if (uploadedFiles.includes(file.name)) {
        setUploadStatus("This PDF is already uploaded.", "error");
        showToast("This PDF is already in your session", "error");
        return;
    }

    if (isUploading) return;

    isUploading = true;
    const uploadBtn = document.getElementById("uploadBtn");
    uploadBtn.disabled = true;
    uploadBtn.classList.add("loading");
    setUploadStatus("Uploading and indexing PDF...", "loading");

    const formData = new FormData();
    formData.append("file", file);

    try {
        const response = await fetch(apiUrl("/api/upload"), {
            method: "POST",
            body: formData,
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.detail || "Upload failed");
        }

        setUploadStatus(`Indexed ${data.chunks || 0} chunks successfully`, "success");
        uploadedFiles.push(file.name);
        addDocumentToList(file.name, data.chunks);
        updateDocCount();
        fileInput.value = "";
        showToast(`${file.name} is ready for questions`, "success");
        toggleSidebar(false);

    } catch (error) {
        setUploadStatus(error.message || "Upload failed", "error");
        showToast(error.message || "Upload failed", "error");
    } finally {
        isUploading = false;
        uploadBtn.disabled = false;
        uploadBtn.classList.remove("loading");
    }
}

async function askQuestion() {
    const input = document.getElementById("question");
    const question = input.value.trim();

    if (!question) return;

    if (uploadedFiles.length === 0) {
        setUploadStatus("Upload a PDF before asking questions.", "error");
        showToast("Upload a PDF first", "error");
        return;
    }

    removeWelcomeCard();
    appendMessage("user", question);
    input.value = "";
    resizeQuestionInput();
    showTypingIndicator();

    const sendBtn = document.getElementById("sendBtn");
    sendBtn.disabled = true;

    try {
        const response = await fetch(apiUrl("/api/chat"), {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                message: question,
                documents: uploadedFiles,
            }),
        });

        const data = await response.json();
        hideTypingIndicator();

        if (!response.ok) {
            appendMessage("bot", data.detail || "Something went wrong.", true);
            return;
        }

        appendMessage("bot", data.answer, false, data.sources || []);

    } catch (error) {
        hideTypingIndicator();
        appendMessage("bot", "Could not reach the server. Please try again.", true);
    } finally {
        sendBtn.disabled = false;
        input.focus();
    }
}

document.addEventListener("DOMContentLoaded", () => {
    const questionInput = document.getElementById("question");
    const fileInput = document.getElementById("fileInput");
    const dropZone = document.getElementById("dropZone");
    const attachButton = document.getElementById("attachBtn");

    questionInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
            if (e.shiftKey) return;
            e.preventDefault();
            askQuestion();
        }
    });
    questionInput.addEventListener("input", resizeQuestionInput);
    attachButton.addEventListener("click", () => fileInput.click());

    dropZone.addEventListener("click", () => fileInput.click());

    fileInput.addEventListener("change", () => {
        if (fileInput.files[0]) uploadFile();
    });

    dropZone.addEventListener("dragover", (e) => {
        e.preventDefault();
        dropZone.classList.add("drag-over");
    });

    dropZone.addEventListener("dragleave", () => {
        dropZone.classList.remove("drag-over");
    });

    dropZone.addEventListener("drop", (e) => {
        e.preventDefault();
        dropZone.classList.remove("drag-over");

        const file = e.dataTransfer.files[0];
        if (!file) return;

        if (!file.name.toLowerCase().endsWith(".pdf")) {
            setUploadStatus("Only PDF files are supported.", "error");
            showToast("Only PDF files are supported", "error");
            return;
        }

        const dt = new DataTransfer();
        dt.items.add(file);
        fileInput.files = dt.files;
        uploadFile();
    });

    document.getElementById("sidebarToggle")?.addEventListener("click", () => toggleSidebar());
    document.getElementById("sidebarOverlay")?.addEventListener("click", () => toggleSidebar(false));

    updateDocCount();
});
