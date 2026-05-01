let recognition;
let finalTranscript = "";
let isRecording = false;
let silenceTimer;
let conversation = [
  {
    role: "assistant",
    content: "Let's begin. Which topic are you interested in discussing today?"
  }
];

const startBtn = document.getElementById("startBtn");
const stopBtn = document.getElementById("stopBtn");
const statusText = document.getElementById("status");
const responseAudio = document.getElementById("responseAudio");
const transcriptText = document.getElementById("transcript");
const conversationEl = document.getElementById("conversation");
const typedAnswer = document.getElementById("typedAnswer");
const sendTypedBtn = document.getElementById("sendTypedBtn");
const sessionState = document.getElementById("sessionState");
const topicChips = document.querySelectorAll(".topic-chip");

function setStatus(message, state = "Ready") {
  statusText.textContent = message;
  sessionState.textContent = state;
}

function renderConversation() {
  conversationEl.innerHTML = conversation
    .map((message) => {
      const label = message.role === "assistant" ? "AI Examiner" : "You";
      return `
        <div class="message ${message.role}">
          <span>${label}</span>
          <p>${escapeHtml(message.content)}</p>
        </div>
      `;
    })
    .join("");
  conversationEl.scrollTop = conversationEl.scrollHeight;
}

function escapeHtml(value) {
  return value.replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "\"": "&quot;",
    "'": "&#039;",
  }[char]));
}

async function startRecording() {
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;

  if (!SpeechRecognition) {
    setStatus("Voice recognition is not available here. Type your answer and press Send.", "Type");
    typedAnswer.focus();
    return;
  }

  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    setStatus("Microphone access is not available in this browser. Try Chrome or Edge.", "Type");
    typedAnswer.focus();
    return;
  }

  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    stream.getTracks().forEach((track) => track.stop());
  } catch (error) {
    console.error("Microphone permission error:", error);
    setStatus("Microphone permission was blocked. Allow microphone access, then try again.", "Blocked");
    return;
  }

  finalTranscript = "";
  transcriptText.textContent = "";
  recognition = new SpeechRecognition();
  recognition.lang = "en-US";
  recognition.continuous = true;
  recognition.interimResults = true;

  recognition.addEventListener("result", (event) => {
    let interimTranscript = "";
    clearTimeout(silenceTimer);

    for (let i = event.resultIndex; i < event.results.length; i++) {
      const text = event.results[i][0].transcript;
      if (event.results[i].isFinal) {
        finalTranscript += `${text} `;
      } else {
        interimTranscript += text;
      }
    }

    transcriptText.textContent = (finalTranscript + interimTranscript).trim();
    silenceTimer = window.setTimeout(() => {
      if (isRecording && transcriptText.textContent.trim()) {
        stopRecording();
      }
    }, 1800);
  });

  recognition.addEventListener("error", (event) => {
    console.warn("Speech recognition error:", event.error);
    isRecording = false;
    startBtn.disabled = false;
    stopBtn.disabled = true;

    if (event.error === "not-allowed" || event.error === "service-not-allowed") {
      setStatus("Speech recognition was blocked. Allow microphone/speech access or type your answer.", "Blocked");
    } else if (event.error === "no-speech") {
      setStatus("I did not hear speech. Press Speak Answer and try again.", "Try again");
    } else {
      setStatus(`Speech recognition error: ${event.error}. You can type your answer below.`, "Type");
    }
  });

  recognition.addEventListener("end", () => {
    clearTimeout(silenceTimer);
    if (isRecording) {
      isRecording = false;
      stopBtn.disabled = true;
      startBtn.disabled = false;
      submitAnswer(transcriptText.textContent.trim());
    }
  });

  isRecording = true;
  try {
    recognition.start();
    startBtn.disabled = true;
    stopBtn.disabled = false;
    setStatus("Listening now. Speak your answer, then press Stop.", "Listening");
  } catch (error) {
    console.error("Speech recognition start error:", error);
    isRecording = false;
    startBtn.disabled = false;
    stopBtn.disabled = true;
    setStatus("Could not start listening. Refresh the page or type your answer below.", "Type");
  }
}

function stopRecording() {
  if (recognition && isRecording) {
    setStatus("Thinking...", "Processing");
    recognition.stop();
  } else {
    setStatus("Press Speak Answer first, or type your answer below.", "Ready");
  }
}

function sendTypedAnswer() {
  const text = typedAnswer.value.trim();
  typedAnswer.value = "";
  transcriptText.textContent = text;
  submitAnswer(text);
}

async function submitAnswer(transcript) {
  if (!transcript) {
    setStatus("I did not receive any words. Please speak again or type your answer.", "Try again");
    return;
  }

  startBtn.disabled = true;
  stopBtn.disabled = true;
  sendTypedBtn.disabled = true;
  conversation.push({ role: "user", content: transcript });
  renderConversation();
  setStatus("AI examiner is replying...", "Replying");

  try {
    const response = await fetch("http://127.0.0.1:5000/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        transcript,
        history: JSON.stringify(conversation.slice(0, -1)),
      }),
    });

    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.error || `Server returned ${response.status}`);
    }

    conversation.push({ role: "assistant", content: data.reply_text });
    renderConversation();
    speakReply(data.reply_text);
    setStatus("Answer the next question when you are ready.", "Ready");
  } catch (error) {
    console.error(error);
    setStatus("Could not reach the AI agent. Make sure the backend is running.", "Offline");
  } finally {
    startBtn.disabled = false;
    stopBtn.disabled = true;
    sendTypedBtn.disabled = false;
  }
}

function speakReply(text) {
  if (!("speechSynthesis" in window)) {
    return;
  }

  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = "en-US";
  utterance.rate = 0.95;
  window.speechSynthesis.speak(utterance);
}

typedAnswer.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    sendTypedAnswer();
  }
});

startBtn.addEventListener("click", startRecording);
stopBtn.addEventListener("click", stopRecording);
sendTypedBtn.addEventListener("click", sendTypedAnswer);
topicChips.forEach((chip) => {
  chip.addEventListener("click", () => {
    typedAnswer.value = chip.dataset.prompt || chip.textContent.trim();
    typedAnswer.focus();
  });
});

window.startRecording = startRecording;
window.stopRecording = stopRecording;
window.sendTypedAnswer = sendTypedAnswer;

responseAudio.style.display = "none";
renderConversation();
setStatus("Ready. Use Chrome or Edge, allow microphone access, then press Speak Answer.", "Ready");
