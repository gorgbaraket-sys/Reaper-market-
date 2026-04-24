import os
import uuid
import json
import asyncio
import subprocess
import threading
import time
from flask import Flask, render_template, jsonify, send_file, request
from groq import Groq
import edge_tts
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import textwrap

app = Flask(__name__)

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
OUTPUT_DIR = "/tmp/reaper_videos"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Track job status
jobs = {}

# ─── SCRIPT GENERATION ────────────────────────────────────────────────────────

def generate_script(topic):
    client = Groq(api_key=GROQ_API_KEY)

    prompt = f"""You are writing a short philosophical TikTok video script for two characters:
- CHIBI: A small, cute, naive Grim Reaper. Speaks innocently, asks simple questions, says obvious truths in a funny/sweet way.
- HORROR: The adult, terrifying Grim Reaper. Speaks in cold, dark, deep philosophical truths about life, society, money, the system.

Topic: {topic}

Rules:
- 4 to 6 alternating lines total (start with CHIBI, end with HORROR)
- Each line MAX 15 words
- HORROR lines must be chilling and profound
- CHIBI lines must be ironic or innocently naive
- Return ONLY a valid JSON array, no markdown, no extra text

Format:
[
  {{"character": "CHIBI", "text": "..."}},
  {{"character": "HORROR", "text": "..."}},
  {{"character": "CHIBI", "text": "..."}},
  {{"character": "HORROR", "text": "..."}}
]"""

    response = client.chat.completions.create(
        model="llama3-70b-8192",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.85,
        max_tokens=400,
    )

    raw = response.choices[0].message.content.strip()
    # Clean up in case model adds extra text
    start = raw.find("[")
    end = raw.rfind("]") + 1
    return json.loads(raw[start:end])


# ─── TTS GENERATION ───────────────────────────────────────────────────────────

async def generate_tts(text, character, output_path):
    if character == "CHIBI":
        voice = "en-US-JennyNeural"  # Light, friendly
    else:
        voice = "en-GB-RyanNeural"   # Deep, serious

    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(output_path)


# ─── FRAME GENERATION ─────────────────────────────────────────────────────────

def create_frame(character, text, output_path):
    W, H = 1080, 1920
    img = Image.new("RGB", (W, H), color=(8, 8, 8))
    draw = ImageDraw.Draw(img)

    if character == "HORROR":
        # Dark red vignette
        for i in range(30):
            alpha = int(80 - i * 2.5)
            if alpha > 0:
                draw.ellipse(
                    [W//2 - i*25, H//2 - i*35, W//2 + i*25, H//2 + i*35],
                    outline=(120, 0, 0, 0),
                )
        # Red glow at top
        for y in range(300):
            r = int(40 * (1 - y / 300))
            draw.line([(0, y), (W, y)], fill=(r, 0, 0))
    else:
        # Subtle warm tint for chibi
        for y in range(400):
            b = int(15 * (1 - y / 400))
            draw.line([(0, H - y), (W, H - y)], fill=(8, 8, b + 8))

    # Load character image
    char_path = f"static/characters/{'horror' if character == 'HORROR' else 'chibi'}.png"
    try:
        char_img = Image.open(char_path).convert("RGBA")
        # Position: centered, horror at top-center, chibi lower-center
        if character == "HORROR":
            new_w = 600
            ratio = new_w / char_img.width
            new_h = int(char_img.height * ratio)
            char_img = char_img.resize((new_w, new_h), Image.LANCZOS)
            x = (W - new_w) // 2
            y = 200
        else:
            new_w = 450
            ratio = new_w / char_img.width
            new_h = int(char_img.height * ratio)
            char_img = char_img.resize((new_w, new_h), Image.LANCZOS)
            x = (W - new_w) // 2
            y = 500

        img.paste(char_img, (x, y), char_img)
    except Exception as e:
        print(f"Character load error: {e}")

    # Text box at bottom
    try:
        font_large = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 58)
        font_name = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 36)
    except:
        font_large = ImageFont.load_default()
        font_name = ImageFont.load_default()

    # Character label
    label_color = (200, 50, 50) if character == "HORROR" else (255, 220, 100)
    label = "☠ THE REAPER" if character == "HORROR" else "✦ LITTLE REAPER"
    draw.text((W // 2, H - 500), label, font=font_name, fill=label_color, anchor="mm")

    # Text background
    draw.rectangle([60, H - 450, W - 60, H - 80], fill=(0, 0, 0, 180))

    # Wrapped text
    wrapped = textwrap.fill(text, width=28)
    lines = wrapped.split("\n")
    total_h = len(lines) * 70
    start_y = H - 450 + (370 - total_h) // 2

    text_color = (255, 80, 80) if character == "HORROR" else (255, 255, 255)
    for i, line in enumerate(lines):
        draw.text((W // 2, start_y + i * 70), line,
                  font=font_large, fill=text_color, anchor="mm")

    img.save(output_path)


# ─── VIDEO ASSEMBLY ───────────────────────────────────────────────────────────

def assemble_video(script, job_id):
    job_dir = os.path.join(OUTPUT_DIR, job_id)
    os.makedirs(job_dir, exist_ok=True)
    segments = []

    for i, line in enumerate(script):
        char = line["character"]
        text = line["text"]

        frame_path = os.path.join(job_dir, f"frame_{i}.png")
        audio_path = os.path.join(job_dir, f"audio_{i}.mp3")
        seg_path   = os.path.join(job_dir, f"seg_{i}.mp4")

        # Generate frame
        create_frame(char, text, frame_path)

        # Generate TTS
        asyncio.run(generate_tts(text, char, audio_path))

        # Get audio duration
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "csv=p=0", audio_path],
            capture_output=True, text=True
        )
        duration = float(result.stdout.strip() or "3.0") + 0.5

        # Create segment: image + audio
        subprocess.run([
            "ffmpeg", "-y",
            "-loop", "1", "-i", frame_path,
            "-i", audio_path,
            "-c:v", "libx264", "-tune", "stillimage",
            "-c:a", "aac", "-b:a", "128k",
            "-t", str(duration),
            "-pix_fmt", "yuv420p",
            "-vf", "scale=1080:1920",
            seg_path
        ], capture_output=True)

        segments.append(seg_path)

    # Add transition effect: add 0.5s black fade between segments
    concat_list = os.path.join(job_dir, "concat.txt")
    with open(concat_list, "w") as f:
        for seg in segments:
            f.write(f"file '{seg}'\n")

    final_path = os.path.join(OUTPUT_DIR, f"{job_id}.mp4")
    subprocess.run([
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", concat_list,
        "-c", "copy",
        final_path
    ], capture_output=True)

    return final_path


# ─── BACKGROUND JOB ───────────────────────────────────────────────────────────

def run_job(job_id, topic):
    try:
        jobs[job_id] = {"status": "generating_script", "progress": 10}
        script = generate_script(topic)

        jobs[job_id] = {"status": "creating_video", "progress": 30, "lines": len(script)}

        final_path = assemble_video(script, job_id)

        jobs[job_id] = {
            "status": "done",
            "progress": 100,
            "file": f"{job_id}.mp4",
            "script": script
        }
    except Exception as e:
        jobs[job_id] = {"status": "error", "message": str(e)}


# ─── ROUTES ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/generate", methods=["POST"])
def generate():
    data = request.get_json()
    topic = data.get("topic", "money and the system").strip()
    if not topic:
        topic = "money and the system"

    job_id = str(uuid.uuid4())
    jobs[job_id] = {"status": "queued", "progress": 0}

    thread = threading.Thread(target=run_job, args=(job_id, topic))
    thread.daemon = True
    thread.start()

    return jsonify({"job_id": job_id})


@app.route("/status/<job_id>")
def status(job_id):
    return jsonify(jobs.get(job_id, {"status": "not_found"}))


@app.route("/download/<filename>")
def download(filename):
    path = os.path.join(OUTPUT_DIR, filename)
    if os.path.exists(path):
        return send_file(path, as_attachment=True, download_name="reaper_video.mp4")
    return "File not found", 404


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
