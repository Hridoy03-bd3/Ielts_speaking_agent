import math
import os
import re
import struct
import uuid
import wave
from json import loads
from urllib.parse import quote

from flask import Flask, jsonify, request, send_file
from flask_cors import CORS

try:
    import whisper
except Exception:
    whisper = None

try:
    from gtts import gTTS
except Exception:
    gTTS = None

try:
    from openai import OpenAI
except Exception:
    OpenAI = None

try:
    from google import genai
except Exception:
    genai = None


app = Flask(__name__)
CORS(app, expose_headers=["X-Reply-Text"])
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def load_local_env():
    env_path = os.path.join(BASE_DIR, ".env")
    if not os.path.exists(env_path):
        return

    with open(env_path, encoding="utf-8") as env_file:
        for line in env_file:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


load_local_env()


if whisper is not None:
    try:
        model = whisper.load_model("base")
    except Exception:
        model = None
        print("Warning: failed to load Whisper model - continuing in demo mode.")
else:
    model = None
    print("Warning: whisper package not available - continuing in demo mode.")


OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if OPENAI_API_KEY and OpenAI is not None:
    client = OpenAI(api_key=OPENAI_API_KEY)
else:
    client = None

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "openai/gpt-oss-120b:free")
if OPENROUTER_API_KEY and OpenAI is not None:
    openrouter_client = OpenAI(
        api_key=OPENROUTER_API_KEY,
        base_url="https://openrouter.ai/api/v1",
    )
else:
    openrouter_client = None

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if GEMINI_API_KEY and genai is not None:
    gemini_client = genai.Client(api_key=GEMINI_API_KEY)
else:
    gemini_client = None


def create_fallback_wav(path):
    sample_rate = 16000
    duration = 0.35
    frequency = 660
    amplitude = 9000
    frame_count = int(sample_rate * duration)

    with wave.open(path, "w") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        for i in range(frame_count):
            sample = int(amplitude * math.sin(2 * math.pi * frequency * i / sample_rate))
            wav_file.writeframes(struct.pack("<h", sample))


TOPIC_QUESTIONS = [
    "Let's change the topic. What kind of food do you enjoy eating, and why?",
    "Okay, let's talk about study. What subject did you enjoy most at school?",
    "Let's move to technology. How do you usually use your phone in daily life?",
    "Now let's talk about travel. Is there a place you would like to visit?",
]


def clean_words(text):
    return re.findall(r"[a-zA-Z']+", text.lower())


def build_demo_reply(user_text, history):
    text = user_text.strip()
    lowered = text.lower()
    words = clean_words(text)
    user_turn_count = sum(1 for item in history if item.get("role") == "user")

    if any(phrase in lowered for phrase in ["another topic", "change topic", "new topic", "different topic"]):
        return TOPIC_QUESTIONS[user_turn_count % len(TOPIC_QUESTIONS)]

    if lowered in {"yes", "yes.", "yeah", "yeah.", "no", "no.", "nope", "nope."}:
        return (
            "I understand, but a one-word answer is too short for IELTS speaking. "
            "Try to explain your opinion with a reason. "
            "Why do you feel that way?"
        )

    if len(words) == 1 and words[0] not in {"kushtia", "dhaka"}:
        return (
            "I am not sure I understood that clearly. "
            "Please repeat it as a full sentence so I can respond to your idea. "
            "What do you want to say about this topic?"
        )

    if len(words) <= 1:
        topic = words[0].title() if words else "that"
        return (
            f"{topic} sounds like an interesting answer, but it is too short for IELTS speaking. "
            "Try to say two or three sentences with one reason or example. "
            f"What do you like or dislike about {topic}?"
        )

    if len(words) <= 3:
        return (
            "I understand, but try not to stop with a very short answer. "
            "In IELTS, you should extend your answer with because, for example, or in my experience. "
            "Can you explain your answer in more detail?"
        )

    if "don't" in lowered or "do not" in lowered or "no, actually" in lowered:
        return (
            "That is a natural correction, good. You can make it stronger by explaining why you do not do it. "
            "What is the main reason you avoid it?"
        )

    if any(place in lowered for place in ["kushtia", "dhaka", "hometown", "city", "village"]):
        return (
            "Nice. You are talking about your hometown, so add details like people, food, roads, or culture. "
            "What is one thing visitors should see or experience there?"
        )

    if any(word in lowered for word in ["food", "eat", "restaurant", "rice", "fish"]):
        return (
            "Good, food is an easy topic to develop with examples. "
            "Try to describe taste, place, and who you eat with. "
            "What food is popular in your area?"
        )

    if any(word in lowered for word in ["study", "school", "university", "english", "ielts"]):
        return (
            "That connects well with your learning goal. "
            "A stronger IELTS answer would include a challenge and how you handle it. "
            "What is the hardest part of improving your speaking?"
        )

    return (
        f"I heard your point about: '{text}'. That is a useful start. "
        "To sound more fluent, add one reason and one personal example. "
        "Can you give me a specific example from your own life?"
    )


def attach_reply_header(response, reply_text):
    response.headers["X-Reply-Text"] = quote(reply_text, safe="")
    return response


def get_reply_text(user_text, history_raw="[]"):
    try:
        history = loads(history_raw)
        history = [
            {"role": item["role"], "content": item["content"]}
            for item in history[-8:]
            if item.get("role") in {"user", "assistant"} and item.get("content")
        ]
    except Exception:
        history = []

    system_prompt = (
        "You are a friendly IELTS speaking examiner and practice partner. "
        "The learner speaks to you for practice. Reply directly to the learner's "
        "answer, mention one useful improvement when it fits, and then ask exactly "
        "one natural follow-up question. Keep the reply short and conversational."
    )

    if openrouter_client is not None:
        try:
            response = openrouter_client.chat.completions.create(
                model=OPENROUTER_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    *history,
                    {"role": "user", "content": user_text},
                ],
                extra_headers={
                    "HTTP-Referer": "http://127.0.0.1:8000",
                    "X-Title": "IELTS Voice Practice",
                },
            )
            return response.choices[0].message.content
        except Exception as exc:
            print("OpenRouter request failed:", exc)

    if client is not None:
        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    *history,
                    {"role": "user", "content": user_text},
                ],
            )
            return response.choices[0].message.content
        except Exception as exc:
            print("OpenAI request failed:", exc)

    if gemini_client is not None:
        history_text = "\n".join(
            f"{item['role'].title()}: {item['content']}" for item in history[-8:]
        )
        prompt = (
            f"{system_prompt}\n\n"
            f"Conversation so far:\n{history_text or 'No previous turns.'}\n\n"
            f"Learner: {user_text}\n"
            "AI Examiner:"
        )

        for model_name in ("gemini-2.5-flash", "gemini-2.5-flash-lite"):
            try:
                response = gemini_client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                )
                if response and getattr(response, "text", None):
                    result = response.text.strip()
                    return result
            except Exception as exc:
                print(f"Gemini {model_name} request failed:", exc)
                continue

    return build_demo_reply(user_text, history)


@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json(silent=True) or {}
    user_text = data.get("transcript", "").strip()
    history_raw = data.get("history", "[]")

    if not user_text:
        return jsonify({"error": "No speech transcript received."}), 400

    reply_text = get_reply_text(user_text, history_raw)
    print("User said:", user_text)
    print("AI:", reply_text)

    return jsonify({"user_text": user_text, "reply_text": reply_text})


@app.route("/process-audio", methods=["POST"])
def process_audio():
    browser_transcript = request.form.get("transcript", "").strip()
    history_raw = request.form.get("history", "[]")
    if "audio" not in request.files and not browser_transcript:
        return jsonify({"error": "No audio file or transcript uploaded."}), 400

    request_id = uuid.uuid4().hex
    if browser_transcript:
        user_text = browser_transcript
    elif model is not None:
        try:
            audio_file = request.files["audio"]
            file_path = os.path.join(BASE_DIR, f"input_{request_id}.webm")
            audio_file.save(file_path)
            result = model.transcribe(file_path)
            user_text = result.get("text", "")
        except Exception as exc:
            print("Whisper transcription failed:", exc)
            user_text = "[transcription unavailable in this environment]"
    else:
        user_text = "[transcription unavailable in this environment]"

    print("User said:", user_text)

    reply_text = get_reply_text(user_text, history_raw)

    print("AI:", reply_text)

    # Try TTS (gTTS). If it fails, fall back to a generated WAV.
    if gTTS is not None:
        output_mp3 = os.path.join(BASE_DIR, f"response_{request_id}.mp3")
        try:
            tts = gTTS(reply_text)
            tts.save(output_mp3)
            if os.path.exists(output_mp3):
                response = send_file(output_mp3, mimetype="audio/mpeg")
                return attach_reply_header(response, reply_text)
            else:
                print("gTTS: expected output file not found after save:", output_mp3)
        except Exception as exc:
            print("gTTS failed:", exc)

    # Fallback: generate a short WAV so the frontend always receives audio
    output_wav = os.path.join(BASE_DIR, f"response_{request_id}.wav")
    try:
        create_fallback_wav(output_wav)
        if os.path.exists(output_wav):
            response = send_file(output_wav, mimetype="audio/wav")
            return attach_reply_header(response, reply_text)
        else:
            print("Failed to create fallback WAV:", output_wav)
            return jsonify({"error": "Failed to produce audio output."}), 500
    except Exception as exc:
        print("Fallback WAV creation failed:", exc)
        return jsonify({"error": "TTS and fallback both failed."}), 500


if __name__ == "__main__":
    app.run(debug=True)
