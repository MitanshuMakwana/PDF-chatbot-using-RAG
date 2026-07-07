let uploadedFiles = [];
let isUploading = false;

async function uploadFile() {

    const fileInput = document.getElementById("fileInput");
    const file = fileInput.files[0];

    if (!file) {
        alert("Please select a PDF");
        return;
    }

    // Prevent duplicate uploads
    if (uploadedFiles.includes(file.name)) {
        alert("This PDF is already uploaded.");
        return;
    }

    // Prevent multiple clicks
    if (isUploading) {
        return;
    }

    isUploading = true;

    const uploadStatus =
        document.getElementById("uploadStatus");

    uploadStatus.innerText = "Uploading PDF...";

    const formData = new FormData();
    formData.append("file", file);

    try {

        const response = await fetch("/api/upload", {
            method: "POST",
            body: formData
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(
                data.detail || "Upload failed"
            );
        }

        uploadStatus.innerText =
            data.message || "PDF uploaded successfully";

        uploadedFiles.push(file.name);

        const li = document.createElement("li");
        li.textContent = "📄 " + file.name;

        document
            .getElementById("documentList")
            .appendChild(li);

        // Clear selected file
        fileInput.value = "";

    } catch (error) {

        uploadStatus.innerText =
            error.message || "Upload failed";

    } finally {

        isUploading = false;
    }
}

async function askQuestion() {

    const input =
        document.getElementById("question");

    const question =
        input.value.trim();

    if (!question) return;

    const chat =
        document.getElementById("chatMessages");

    // User message
    chat.innerHTML += `
        <div class="user-message">
            ${question}
        </div>
    `;

    chat.scrollTop = chat.scrollHeight;

    input.value = "";

    // Loading message
    const loadingDiv = document.createElement("div");

    loadingDiv.className = "bot-message";

    loadingDiv.innerHTML = "Thinking...";

    chat.appendChild(loadingDiv);

    chat.scrollTop = chat.scrollHeight;

    try {

        const response = await fetch("/api/chat", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                message: question
            })
        });

        const data = await response.json();

        loadingDiv.remove();

        if (!response.ok) {

            chat.innerHTML += `
                <div class="bot-message">
                    ERROR: ${data.detail}
                </div>
            `;

            chat.scrollTop = chat.scrollHeight;
            return;
        }

        chat.innerHTML += `
            <div class="bot-message">
                ${data.answer}
            </div>
        `;

        chat.scrollTop = chat.scrollHeight;

    } catch (error) {

        loadingDiv.remove();

        chat.innerHTML += `
            <div class="bot-message">
                Error getting response.
            </div>
        `;

        chat.scrollTop = chat.scrollHeight;
    }
}

// Enter key support
document.addEventListener("DOMContentLoaded", () => {

    const questionInput =
        document.getElementById("question");

    questionInput.addEventListener("keydown", (e) => {

        if (e.key === "Enter") {

            e.preventDefault();
            askQuestion();
        }
    });
});