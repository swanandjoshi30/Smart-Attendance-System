// chat.js
/**
 * Interactive Client Script for Conversational AI Assistant
 */

(function () {
    // DOM Elements
    const chatToggleBtn = document.getElementById("chat-toggle-btn");
    const chatPanel = document.getElementById("ai-chat-panel");
    const closeChatBtn = document.getElementById("close-chat-btn");
    const clearChatBtn = document.getElementById("clear-chat-btn");
    const chatInputForm = document.getElementById("chat-input-form");
    const chatUserInput = document.getElementById("chat-user-input");
    const chatMessages = document.getElementById("chat-messages");
    const suggestionChips = document.querySelectorAll(".suggestion-chip");

    // Session Management: persistent ID per user device
    let chatSessionId = localStorage.getItem("eduvision_chat_session_id");
    if (!chatSessionId) {
        chatSessionId = "session_" + Math.random().toString(36).substring(2, 15) + Math.random().toString(36).substring(2, 15);
        localStorage.setItem("eduvision_chat_session_id", chatSessionId);
    }

    // Toggle panel visibility
    chatToggleBtn.addEventListener("click", () => {
        chatPanel.classList.toggle("active");
        if (chatPanel.classList.contains("active")) {
            chatUserInput.focus();
            scrollToBottom();
        }
    });

    closeChatBtn.addEventListener("click", () => {
        chatPanel.classList.remove("active");
    });

    // Clear Conversation History
    clearChatBtn.addEventListener("click", async () => {
        if (!confirm("Are you sure you want to clear this conversation session history?")) {
            return;
        }

        try {
            const response = await fetch("/api/chat/clear", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ session_id: chatSessionId, message: "clear" })
            });
            const data = await response.json();
            if (data.success) {
                // Reset visual messages state to initial greeting
                chatMessages.innerHTML = `
                    <div class="chat-message assistant">
                        <p>Hello! I am your smart attendance assistant. You can ask me questions about classes, subjects, students, cameras, or attendance records. E.g.,</p>
                        <p><em>"Was Atharva present yesterday?"</em></p>
                    </div>
                `;
                appendSystemMessage("Conversation history cleared.");
            } else {
                appendSystemMessage("Failed to clear chat history: " + data.detail);
            }
        } catch (err) {
            console.error(err);
            appendSystemMessage("Error: Could not connect to API server.");
        }
    });

    // Handle suggestion chips
    suggestionChips.forEach(chip => {
        chip.addEventListener("click", () => {
            const query = chip.getAttribute("data-query");
            if (query) {
                chatUserInput.value = query;
                chatInputForm.dispatchEvent(new Event("submit"));
            }
        });
    });

    // Submit message handler
    chatInputForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        const rawMessage = chatUserInput.value.trim();
        if (!rawMessage) return;

        // Render user message bubble
        appendMessage("user", rawMessage);
        chatUserInput.value = "";

        // Show typing indicator
        showTypingIndicator();
        scrollToBottom();

        try {
            const response = await fetch("/api/chat", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    message: rawMessage,
                    session_id: chatSessionId
                })
            });

            removeTypingIndicator();

            if (!response.ok) {
                const errData = await response.json();
                appendMessage("assistant", `Error: ${errData.detail || "Server error occurred"}`);
                return;
            }

            const data = await response.json();
            if (data.success) {
                appendMessage("assistant", data.response);
            } else {
                appendMessage("assistant", "Failed to retrieve a response from the database assistant.");
            }
        } catch (err) {
            removeTypingIndicator();
            console.error(err);
            appendMessage("assistant", "Error: Connection timed out or server is offline. Please verify API is running.");
        }
        scrollToBottom();
    });

    // =========================================================================
    // UI HELPERS
    // =========================================================================

    function appendMessage(role, text) {
        const bubble = document.createElement("div");
        bubble.classList.add("chat-message", role);
        
        if (role === "assistant") {
            bubble.innerHTML = formatMarkdown(text);
        } else {
            // User message is plain text
            bubble.textContent = text;
        }
        
        chatMessages.appendChild(bubble);
        scrollToBottom();
    }

    function appendSystemMessage(text) {
        const bubble = document.createElement("div");
        bubble.classList.add("chat-message", "system");
        bubble.textContent = text;
        chatMessages.appendChild(bubble);
        scrollToBottom();
    }

    function showTypingIndicator() {
        if (document.getElementById("typing-indicator")) return;
        const indicator = document.createElement("div");
        indicator.id = "typing-indicator";
        indicator.classList.add("typing-indicator");
        indicator.innerHTML = `
            <div class="typing-dot"></div>
            <div class="typing-dot"></div>
            <div class="typing-dot"></div>
        `;
        chatMessages.appendChild(indicator);
    }

    function removeTypingIndicator() {
        const indicator = document.getElementById("typing-indicator");
        if (indicator) {
            indicator.remove();
        }
    }

    function scrollToBottom() {
        chatMessages.scrollTop = chatMessages.scrollHeight;
    }

    /**
     * Translates simple Markdown tables and paragraphs into beautiful HTML blocks.
     */
    function formatMarkdown(text) {
        // Escaping HTML elements to prevent script injection
        let html = text
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;");

        // Convert double asterisks to bold tags
        html = html.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');

        // Regex parsing to build clean HTML Tables
        const lines = html.split('\n');
        let inTable = false;
        let tableHtml = "";
        let newLines = [];

        for (let i = 0; i < lines.length; i++) {
            let line = lines[i].trim();
            if (line.startsWith('|') && line.endsWith('|')) {
                // Ignore table divider row (e.g. |---|---|)
                if (line.replace(/[|:\-\s]/g, '') === '') {
                    continue;
                }
                if (!inTable) {
                    inTable = true;
                    tableHtml = "<table>";
                }
                
                let cells = line.split('|').map(c => c.trim());
                cells = cells.slice(1, cells.length - 1);
                
                let isHeader = !tableHtml.includes('<th>');
                let tag = isHeader ? 'th' : 'td';
                
                tableHtml += "<tr>" + cells.map(c => `<${tag}>${c}</${tag}>`).join('') + "</tr>";
            } else {
                if (inTable) {
                    inTable = false;
                    tableHtml += "</table>";
                    newLines.push(tableHtml);
                    tableHtml = "";
                }
                newLines.push(line);
            }
        }
        if (inTable) {
            tableHtml += "</table>";
            newLines.push(tableHtml);
        }

        // Wrap plain text lines in paragraphs
        return newLines.map(line => {
            if (line.startsWith('<table>') || line.endsWith('</table>')) return line;
            if (line === '') return '<br>';
            return `<p>${line}</p>`;
        }).join('');
    }
})();
