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
  <title>☠ THE REAPER</title>
  <style>
    @import url('https://fonts.googleapis.com/css2?family=Cinzel:wght@700;900&family=Inter:wght@300;400;600&display=swap');
    *{margin:0;padding:0;box-sizing:border-box}
    body{background:#050505;color:#fff;font-family:'Inter',sans-serif;
         min-height:100vh;display:flex;flex-direction:column;align-items:center;overflow-x:hidden}
    body::before{content:'';position:fixed;inset:0;
      background:radial-gradient(ellipse at 20% 20%,rgba(120,0,0,.15) 0%,transparent 60%),
                 radial-gradient(ellipse at 80% 80%,rgba(80,0,0,.10) 0%,transparent 60%);
      pointer-events:none;z-index:0}
    .wrap{position:relative;z-index:1;width:100%;max-width:700px;padding:40px 20px 80px}

    /* header */
    .hdr{text-align:center;margin-bottom:44px}
    .chars{display:flex;justify-content:center;align-items:flex-end;gap:20px;margin-bottom:22px}
    .chars img{filter:drop-shadow(0 0 18px rgba(200,0,0,.55));transition:transform .3s}
    .chars img:hover{transform:scale(1.06)}
    .horror-img{height:130px} .chibi-img{height:88px}
    .logo{font-family:'Cinzel',serif;font-size:40px;font-weight:900;letter-spacing:6px;
          background:linear-gradient(135deg,#cc0000,#ff4444,#cc0000);
          -webkit-background-clip:text;-webkit-text-fill-color:transparent;
          background-clip:text;text-transform:uppercase;margin-bottom:6px}
    .sub{color:#555;font-size:12px;letter-spacing:3px;text-transform:uppercase}

    /* card */
    .card{background:linear-gradient(145deg,#111,#0d0d0d);border:1px solid #1a1a1a;
          border-radius:16px;padding:32px;margin-bottom:22px;
          box-shadow:0 0 40px rgba(0,0,0,.6),inset 0 1px 0 rgba(255,255,255,.03)}
    .card-title{font-family:'Cinzel',serif;font-size:12px;letter-spacing:3px;
                color:#cc3333;text-transform:uppercase;margin-bottom:18px}

    /* pills */
    .pills{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:14px}
    .pill{padding:6px 14px;border-radius:20px;border:1px solid #2a2a2a;background:#111;
          color:#777;font-size:12px;cursor:pointer;transition:all .2s}
    .pill:hover,.pill.on{border-color:#cc3333;color:#ff4444;background:rgba(200,0,0,.08)}

    label{font-size:11px;color:#555;letter-spacing:2px;text-transform:uppercase;display:block;margin-bottom:8px}
    input[type=text]{width:100%;background:#0a0a0a;border:1px solid #222;border-radius:10px;
                     padding:14px 16px;color:#fff;font-size:15px;font-family:'Inter',sans-serif;
                     outline:none;transition:border-color .2s;margin-bottom:22px}
    input[type=text]:focus{border-color:#cc3333}
    input::placeholder{color:#333}

    /* buttons */
    .btn-gen{width:100%;padding:17px;background:linear-gradient(135deg,#8b0000,#cc0000);
             border:none;border-radius:12px;color:#fff;font-family:'Cinzel',serif;
             font-size:15px;letter-spacing:3px;cursor:pointer;transition:all .3s;
             text-transform:uppercase;box-shadow:0 4px 28px rgba(180,0,0,.3)}
    .btn-gen:hover:not(:disabled){background:linear-gradient(135deg,#cc0000,#ff2222);
             transform:translateY(-2px);box-shadow:0 8px 38px rgba(220,0,0,.4)}
    .btn-gen:disabled{opacity:.35;cursor:not-allowed;transform:none}

    /* progress */
    .prog{display:none}.prog.on{display:block}
    .bar-wrap{background:#111;border-radius:8px;height:6px;overflow:hidden;margin:14px 0}
    .bar-fill{height:100%;background:linear-gradient(90deg,#8b0000,#ff2222);
              border-radius:8px;transition:width .5s ease;width:0%}
    .stat-row{display:flex;align-items:center;gap:12px}
    .stat-icon{font-size:22px;animation:pulse 1.5s infinite}
    @keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}
    .stat-txt{font-size:13px;color:#666;letter-spacing:1px}

    /* script */
    .script{display:none;margin-top:14px}.script.on{display:block}
    .s-line{display:flex;gap:10px;align-items:flex-start;padding:11px 0;border-bottom:1px solid #111}
    .s-line:last-child{border-bottom:none}
    .badge{padding:3px 10px;border-radius:20px;font-size:10px;font-weight:700;
           letter-spacing:1px;white-space:nowrap}
    .b-hor{background:rgba(180,0,0,.18);color:#ff4444;border:1px solid #440000}
    .b-chi{background:rgba(255,200,0,.10);color:#ffcc44;border:1px solid #443300}
    .s-txt{color:#ccc;font-size:13px;line-height:1.5;flex:1}

    /* download */
    .btn-dl{display:none;width:100%;padding:19px;
            background:linear-gradient(135deg,#003a00,#006600);border:none;
            border-radius:12px;color:#fff;font-family:'Cinzel',serif;font-size:16px;
            letter-spacing:3px;cursor:pointer;text-transform:uppercase;text-align:center;
            text-decoration:none;box-shadow:0 4px 28px rgba(0,150,0,.3);transition:all .3s;margin-top:18px}
    .btn-dl.on{display:block}
    .btn-dl:hover{background:linear-gradient(135deg,#006600,#00aa00);
                  transform:translateY(-2px);box-shadow:0 8px 38px rgba(0,200,0,.4)}

    .err{display:none;background:rgba(200,0,0,.09);border:1px solid #440000;
         border-radius:10px;padding:15px;color:#ff6666;font-size:13px;margin-top:14px}
    .err.on{display:block}
    .footer{text-align:center;color:#222;font-size:10px;letter-spacing:2px;margin-top:36px}
  </style>
</head>
<body>
<div class="wrap">
  <div class="hdr">
    <div class="chars">
      <img src="/char/chibi"  class="chibi-img"  alt="Little Reaper"/>
      <img src="/char/horror" class="horror-img" alt="Horror Reaper"/>
    </div>
    <div class="logo">The Reaper</div>
    <div class="sub">AI TikTok Video Generator</div>
  </div>

  <div class="card">
    <div class="card-title">☠ Choose Your Topic</div>
    <div class="pills">
      <span class="pill" onclick="pick(this,'money and the system')">💀 Money &amp; System</span>
      <span class="pill" onclick="pick(this,'success and sacrifice')">🔥 Success</span>
      <span class="pill" onclick="pick(this,'society and freedom')">⛓ Society</span>
      <span class="pill" onclick="pick(this,'time is running out')">⏳ Time</span>
      <span class="pill" onclick="pick(this,'luxury and wealth mindset')">💎 Luxury</span>
      <span class="pill" onclick="pick(this,'fear and courage')">🗡 Fear</span>
    </div>
    <label>Or type your own topic</label>
    <input type="text" id="topic" placeholder="e.g. working 9 to 5 your whole life..."/>
    <button class="btn-gen" id="genBtn" onclick="generate()">☠ &nbsp; Generate Video</button>
  </div>

  <div class="card prog" id="prog">
    <div class="card-title">⚙ Generating</div>
    <div class="stat-row">
      <span class="stat-icon" id="icon">⏳</span>
      <span class="stat-txt" id="stxt">Summoning the Reaper...</span>
    </div>
    <div class="bar-wrap"><div class="bar-fill" id="bar"></div></div>

    <div class="script" id="script">
      <div class="card-title" style="margin-top:10px">📜 Script</div>
      <div id="lines"></div>
    </div>

    <a class="btn-dl" id="dlBtn" href="#" download>⬇ &nbsp; Download MP4</a>
    <div class="err" id="err"></div>
  </div>

  <div class="footer">GROQ · EDGE-TTS · FFMPEG · FLASK</div>
</div>

<script>
  let timer = null;
  const msgs = {
    queued:'In queue...', generating_script:'AI writing the script...',
    creating_video:'Rendering frames & video...', done:'Video ready ☠', error:'Error occurred.'
  };
  function pick(el,t){document.querySelectorAll('.pill').forEach(p=>p.classList.remove('on'));
    el.classList.add('on');document.getElementById('topic').value=t}
  function setP(p,m){document.getElementById('bar').style.width=p+'%';
    document.getElementById('stxt').textContent=m}
  async function generate(){
    const topic=(document.getElementById('topic').value.trim())||'money and the system';
    document.getElementById('genBtn').disabled=true;
    const pg=document.getElementById('prog');pg.classList.add('on');
    document.getElementById('dlBtn').classList.remove('on');
    document.getElementById('script').classList.remove('on');
    document.getElementById('err').classList.remove('on');
    document.getElementById('lines').innerHTML='';
    setP(5,'Summoning the Reaper...');
    const r=await fetch('/generate',{method:'POST',
      headers:{'Content-Type':'application/json'},body:JSON.stringify({topic})});
    const {job_id}=await r.json();
    if(timer)clearInterval(timer);
    timer=setInterval(()=>poll(job_id),2500);
  }
  async function poll(id){
    const d=await(await fetch('/status/'+id)).json();
    setP(d.progress||0,msgs[d.status]||d.status);
    if(d.status==='done'){
      clearInterval(timer);
      document.getElementById('genBtn').disabled=false;
      const ic=document.getElementById('icon');ic.textContent='☠';ic.style.animation='none';
      if(d.script){
        const c=document.getElementById('lines');c.innerHTML='';
        d.script.forEach(l=>{const h=l.character==='HORROR';
          c.innerHTML+=`<div class="s-line">
            <span class="badge ${h?'b-hor':'b-chi'}">${h?'☠ REAPER':'✦ LITTLE'}</span>
            <span class="s-txt">"${l.text}"</span></div>`;});
        document.getElementById('script').classList.add('on');
      }
      const dl=document.getElementById('dlBtn');dl.href='/download/'+d.file;dl.classList.add('on');
    } else if(d.status==='error'){
      clearInterval(timer);
      document.getElementById('genBtn').disabled=false;
      document.getElementById('icon').textContent='💀';
      const e=document.getElementById('err');e.textContent='❌ '+(d.message||'Unknown error');e.classList.add('on');
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
