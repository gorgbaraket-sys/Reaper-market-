import os, uuid, json, asyncio, subprocess, threading, base64
from flask import Flask, render_template_string, jsonify, send_file, request
from groq import Groq
import edge_tts
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import textwrap

app = Flask(__name__)

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
OUTPUT_DIR   = "/tmp/reaper_videos"
CHAR_DIR     = "/tmp/reaper_chars"
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(CHAR_DIR,   exist_ok=True)

# ─── COPY CHARACTER IMAGES ON STARTUP ─────────────────────────────────────────
# Looks for horror.png / chibi.png next to app.py (flat repo root)
BASE = os.path.dirname(os.path.abspath(__file__))

def _prep_chars():
    for name in ("horror.png", "chibi.png"):
        src = os.path.join(BASE, name)
        dst = os.path.join(CHAR_DIR, name)
        if os.path.exists(src) and not os.path.exists(dst):
            import shutil; shutil.copy2(src, dst)

_prep_chars()

# ─── JOB STORE ────────────────────────────────────────────────────────────────
jobs = {}

# ─── HTML TEMPLATE (inlined – no templates/ folder needed) ────────────────────
HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1.0"/>
<title>☠ Reaper Bot</title>
<style>
*{margin:0;padding:0;box-sizing:border-box;-webkit-tap-highlight-color:transparent}
body{background:#0a0a0a;color:#fff;font-family:system-ui,sans-serif;
     min-height:100vh;padding:24px 16px 60px}

/* TOP */
.top{text-align:center;padding:20px 0 28px}
.duo{display:flex;justify-content:center;align-items:flex-end;gap:16px;margin-bottom:18px}
.duo img{filter:drop-shadow(0 0 16px rgba(220,0,0,.6))}
.horror-img{height:110px}
.chibi-img{height:72px}
h1{font-size:28px;font-weight:800;letter-spacing:2px;color:#fff;margin-bottom:4px}
.tagline{font-size:12px;color:#444;letter-spacing:2px}

/* TOPIC GRID */
.grid{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:16px}
.topic-btn{
  padding:16px 10px;
  background:#141414;
  border:2px solid #1e1e1e;
  border-radius:14px;
  color:#888;
  font-size:14px;
  font-weight:600;
  cursor:pointer;
  transition:all .15s;
  text-align:center;
  line-height:1.4;
}
.topic-btn:active{transform:scale(.96)}
.topic-btn.sel{
  border-color:#cc0000;
  background:#1a0000;
  color:#ff4444;
}

/* INPUT */
input{
  width:100%;
  background:#111;
  border:2px solid #1e1e1e;
  border-radius:14px;
  padding:16px;
  color:#fff;
  font-size:16px;
  outline:none;
  margin-bottom:14px;
  transition:border-color .2s;
}
input:focus{border-color:#cc0000}
input::placeholder{color:#333}

/* GENERATE BTN */
.go{
  width:100%;
  padding:20px;
  background:#cc0000;
  border:none;
  border-radius:16px;
  color:#fff;
  font-size:18px;
  font-weight:800;
  letter-spacing:1px;
  cursor:pointer;
  transition:all .15s;
  box-shadow:0 4px 24px rgba(200,0,0,.35);
}
.go:active{transform:scale(.97);background:#aa0000}
.go:disabled{opacity:.3;cursor:default;transform:none}

/* STATUS BOX */
.box{
  margin-top:20px;
  background:#111;
  border:2px solid #1e1e1e;
  border-radius:16px;
  padding:20px;
  display:none;
}
.box.show{display:block}

.status-row{display:flex;align-items:center;gap:12px;margin-bottom:14px}
.spin{font-size:28px;animation:spin 1.2s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
.status-txt{font-size:16px;font-weight:600;color:#ccc}

/* BAR */
.bar-bg{background:#1a1a1a;border-radius:99px;height:8px;overflow:hidden;margin-bottom:18px}
.bar{height:100%;background:linear-gradient(90deg,#8b0000,#ff3333);
     border-radius:99px;width:0%;transition:width .4s ease}

/* SCRIPT LINES */
.lines{margin-bottom:18px}
.line{display:flex;gap:10px;align-items:flex-start;padding:12px 0;
      border-bottom:1px solid #1a1a1a}
.line:last-child{border-bottom:none}
.who{font-size:11px;font-weight:700;padding:4px 10px;border-radius:99px;white-space:nowrap;margin-top:2px}
.who.h{background:#2a0000;color:#ff4444}
.who.c{background:#2a2000;color:#ffcc33}
.said{font-size:14px;color:#bbb;line-height:1.5;flex:1}

/* DOWNLOAD */
.dl{
  display:none;
  width:100%;
  padding:20px;
  background:#004400;
  border:none;
  border-radius:16px;
  color:#fff;
  font-size:18px;
  font-weight:800;
  letter-spacing:1px;
  cursor:pointer;
  text-align:center;
  text-decoration:none;
  box-shadow:0 4px 24px rgba(0,150,0,.3);
  transition:all .15s;
}
.dl.show{display:block}
.dl:active{transform:scale(.97);background:#003300}

/* ERROR */
.err-box{display:none;background:#1a0000;border:1px solid #440000;
         border-radius:12px;padding:14px;color:#ff6666;font-size:13px;margin-top:12px;line-height:1.5}
.err-box.show{display:block}

.footer{text-align:center;color:#222;font-size:10px;margin-top:32px;letter-spacing:1px}
</style>
</head>
<body>

<div class="top">
  <div class="duo">
    <img src="/char/chibi"  class="chibi-img"  alt=""/>
    <img src="/char/horror" class="horror-img" alt=""/>
  </div>
  <h1>☠ REAPER BOT</h1>
  <div class="tagline">AI · TIKTOK · VIDEO GENERATOR</div>
</div>

<!-- TOPIC GRID -->
<div class="grid">
  <div class="topic-btn" onclick="pick(this,'money and the system')">💀<br>Money & System</div>
  <div class="topic-btn" onclick="pick(this,'success and sacrifice')">🔥<br>Success</div>
  <div class="topic-btn" onclick="pick(this,'society and freedom')">⛓<br>Society</div>
  <div class="topic-btn" onclick="pick(this,'time is running out')">⏳<br>Time</div>
  <div class="topic-btn" onclick="pick(this,'luxury and wealth mindset')">💎<br>Luxury</div>
  <div class="topic-btn" onclick="pick(this,'fear and courage')">🗡<br>Fear</div>
</div>

<input type="text" id="topic" placeholder="Or type your own topic..."/>
<button class="go" id="goBtn" onclick="go()">☠ &nbsp; GENERATE VIDEO</button>

<!-- STATUS -->
<div class="box" id="box">
  <div class="status-row">
    <span id="icon" class="spin">⚙️</span>
    <span id="stxt" class="status-txt">Starting...</span>
  </div>
  <div class="bar-bg"><div class="bar" id="bar"></div></div>

  <div class="lines" id="lines"></div>

  <a class="dl" id="dlBtn" href="#" download>⬇ DOWNLOAD VIDEO</a>
  <div class="err-box" id="err"></div>
</div>

<div class="footer">GROQ · EDGE-TTS · FFMPEG</div>

<script>
let t=null;
const M={queued:'In queue...',generating_script:'Writing script with AI...',
  creating_video:'Building your video...',done:'Done! Tap download ⬇',error:'Something went wrong'};

function pick(el,v){
  document.querySelectorAll('.topic-btn').forEach(b=>b.classList.remove('sel'));
  el.classList.add('sel');
  document.getElementById('topic').value=v;
}
function setP(p,m){
  document.getElementById('bar').style.width=p+'%';
  document.getElementById('stxt').textContent=m;
}
async function go(){
  const topic=(document.getElementById('topic').value.trim())||'money and the system';
  const btn=document.getElementById('goBtn');
  btn.disabled=true;
  const box=document.getElementById('box');box.classList.add('show');
  document.getElementById('dlBtn').classList.remove('show');
  document.getElementById('err').classList.remove('show');
  document.getElementById('lines').innerHTML='';
  setP(5,'Summoning the Reaper...');
  document.getElementById('icon').style.animation='spin 1.2s linear infinite';
  document.getElementById('icon').textContent='⚙️';
  const r=await fetch('/generate',{method:'POST',
    headers:{'Content-Type':'application/json'},body:JSON.stringify({topic})});
  const {job_id}=await r.json();
  if(t)clearInterval(t);
  t=setInterval(()=>poll(job_id),2500);
}
async function poll(id){
  const d=await(await fetch('/status/'+id)).json();
  setP(d.progress||0, M[d.status]||d.status);
  if(d.status==='done'){
    clearInterval(t);
    document.getElementById('goBtn').disabled=false;
    const ic=document.getElementById('icon');
    ic.textContent='☠';ic.style.animation='none';
    if(d.script){
      const c=document.getElementById('lines');c.innerHTML='';
      d.script.forEach(l=>{
        const h=l.character==='HORROR';
        c.innerHTML+=`<div class="line">
          <span class="who ${h?'h':'c'}">${h?'☠':'✦'}</span>
          <span class="said">${l.text}</span></div>`;
      });
    }
    const dl=document.getElementById('dlBtn');
    dl.href='/download/'+d.file;dl.classList.add('show');
    box.scrollIntoView({behavior:'smooth'});
  } else if(d.status==='error'){
    clearInterval(t);
    document.getElementById('goBtn').disabled=false;
    document.getElementById('icon').textContent='💀';
    document.getElementById('icon').style.animation='none';
    const e=document.getElementById('err');
    e.textContent='❌ '+(d.message||'Unknown error');e.classList.add('show');
  }
}
</script>
</body>
</html>"""


# ─── CHARACTER IMAGE ROUTE (serves PNGs directly) ─────────────────────────────
@app.route("/char/<n>")
def serve_char(n):
    if n not in ("horror", "chibi"):
        return "not found", 404
    path = os.path.join(CHAR_DIR, f"{n}.png")
    if not os.path.exists(path):
        # Fallback: check BASE dir
        path = os.path.join(BASE, f"{n}.png")
    return send_file(path, mimetype="image/png")


# ─── SCRIPT GENERATION ────────────────────────────────────────────────────────
def generate_script(topic):
    client = Groq(api_key=GROQ_API_KEY)
    prompt = f"""You are writing a short philosophical TikTok video script for two characters:
- CHIBI: Small cute naive Grim Reaper. Innocent, ironic, funny.
- HORROR: Adult terrifying Grim Reaper. Cold, dark, philosophical truths about life/money/society.

Topic: {topic}

Rules:
- 4 to 6 alternating lines total (start CHIBI, end HORROR)
- Each line MAX 15 words
- HORROR = chilling and profound. CHIBI = innocent or ironic.
- Return ONLY valid JSON array, no markdown, no extra text.

Format:
[
  {{"character":"CHIBI","text":"..."}},
  {{"character":"HORROR","text":"..."}},
  {{"character":"CHIBI","text":"..."}},
  {{"character":"HORROR","text":"..."}}
]"""
    r = client.chat.completions.create(
        model="llama3-70b-8192",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.85, max_tokens=400,
    )
    raw = r.choices[0].message.content.strip()
    s, e = raw.find("["), raw.rfind("]") + 1
    return json.loads(raw[s:e])


# ─── TTS ──────────────────────────────────────────────────────────────────────
async def gen_tts(text, char, out):
    voice = "en-US-JennyNeural" if char == "CHIBI" else "en-GB-RyanNeural"
    await edge_tts.Communicate(text, voice).save(out)


# ─── FRAME BUILDER ────────────────────────────────────────────────────────────
def make_frame(char, text, out):
    W, H = 1080, 1920
    bg = Image.new("RGB", (W, H), (8, 8, 8))
    draw = ImageDraw.Draw(bg)

    if char == "HORROR":
        for y in range(350):
            draw.line([(0, y), (W, y)], fill=(int(35*(1-y/350)), 0, 0))
    else:
        for y in range(300):
            v = int(12*(1-y/300))
            draw.line([(0, H-y), (W, H-y)], fill=(8, 8, 8+v))

    # Character overlay
    cpath = os.path.join(CHAR_DIR, "horror.png" if char == "HORROR" else "chibi.png")
    if not os.path.exists(cpath):
        cpath = os.path.join(BASE, "horror.png" if char == "HORROR" else "chibi.png")
    try:
        cimg = Image.open(cpath).convert("RGBA")
        if char == "HORROR":
            nw = 560; nh = int(cimg.height * nw / cimg.width)
            cimg = cimg.resize((nw, nh), Image.LANCZOS)
            bg.paste(cimg, ((W-nw)//2, 180), cimg)
        else:
            nw = 420; nh = int(cimg.height * nw / cimg.width)
            cimg = cimg.resize((nw, nh), Image.LANCZOS)
            bg.paste(cimg, ((W-nw)//2, 480), cimg)
    except Exception as ex:
        print("Char load err:", ex)

    draw2 = ImageDraw.Draw(bg)
    try:
        fnt_big  = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 56)
        fnt_name = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 34)
    except:
        fnt_big = fnt_name = ImageFont.load_default()

    lbl = "☠ THE REAPER" if char == "HORROR" else "✦ LITTLE REAPER"
    lbl_col = (210, 50, 50) if char == "HORROR" else (255, 215, 90)
    draw2.text((W//2, H-510), lbl, font=fnt_name, fill=lbl_col, anchor="mm")

    draw2.rectangle([55, H-455, W-55, H-75], fill=(0, 0, 0, 185))

    lines = textwrap.fill(text, width=26).split("\n")
    th = len(lines) * 68
    sy = H - 455 + (380 - th) // 2
    tcol = (255, 75, 75) if char == "HORROR" else (255, 255, 255)
    for i, ln in enumerate(lines):
        draw2.text((W//2, sy + i*68), ln, font=fnt_big, fill=tcol, anchor="mm")

    bg.save(out)


# ─── VIDEO ASSEMBLY ───────────────────────────────────────────────────────────
def assemble(script, job_id):
    jdir = os.path.join(OUTPUT_DIR, job_id)
    os.makedirs(jdir, exist_ok=True)
    segs = []

    for i, line in enumerate(script):
        char, text = line["character"], line["text"]
        frame = os.path.join(jdir, f"f{i}.png")
        audio = os.path.join(jdir, f"a{i}.mp3")
        seg   = os.path.join(jdir, f"s{i}.mp4")

        make_frame(char, text, frame)
        asyncio.run(gen_tts(text, char, audio))

        res = subprocess.run(
            ["ffprobe","-v","quiet","-show_entries","format=duration",
             "-of","csv=p=0", audio], capture_output=True, text=True)
        dur = float(res.stdout.strip() or "3") + 0.6

        subprocess.run([
            "ffmpeg","-y","-loop","1","-i",frame,"-i",audio,
            "-c:v","libx264","-tune","stillimage",
            "-c:a","aac","-b:a","128k",
            "-t",str(dur),"-pix_fmt","yuv420p",
            "-vf","scale=1080:1920", seg
        ], capture_output=True)
        segs.append(seg)

    concat = os.path.join(jdir, "list.txt")
    with open(concat,"w") as f:
        for s in segs: f.write(f"file '{s}'\n")

    out = os.path.join(OUTPUT_DIR, f"{job_id}.mp4")
    subprocess.run([
        "ffmpeg","-y","-f","concat","-safe","0","-i",concat,"-c","copy", out
    ], capture_output=True)
    return out


# ─── BACKGROUND JOB ───────────────────────────────────────────────────────────
def run_job(job_id, topic):
    try:
        jobs[job_id] = {"status":"generating_script","progress":10}
        script = generate_script(topic)
        jobs[job_id] = {"status":"creating_video","progress":35,"lines":len(script)}
        final  = assemble(script, job_id)
        jobs[job_id] = {"status":"done","progress":100,
                        "file":f"{job_id}.mp4","script":script}
    except Exception as e:
        jobs[job_id] = {"status":"error","message":str(e)}


# ─── ROUTES ───────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template_string(HTML)

@app.route("/generate", methods=["POST"])
def generate():
    topic  = request.get_json().get("topic","money and the system").strip() or "money and the system"
    job_id = str(uuid.uuid4())
    jobs[job_id] = {"status":"queued","progress":0}
    t = threading.Thread(target=run_job, args=(job_id, topic))
    t.daemon = True; t.start()
    return jsonify({"job_id": job_id})

@app.route("/status/<job_id>")
def status(job_id):
    return jsonify(jobs.get(job_id,{"status":"not_found"}))

@app.route("/download/<filename>")
def download(filename):
    path = os.path.join(OUTPUT_DIR, filename)
    if os.path.exists(path):
        return send_file(path, as_attachment=True, download_name="reaper_video.mp4")
    return "Not found", 404

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
