# ☠ THE REAPER — AI TikTok Video Generator

Generates philosophical TikTok videos featuring two Grim Reaper characters:
- **Little Reaper** (cute chibi) — innocent, ironic lines
- **The Reaper** (horror adult) — cold, dark philosophical truths

## 📦 Tech Stack
| Component | Service | Cost |
|---|---|---|
| Script Generation | Groq API (Llama 3 70B) | Free tier |
| Text-to-Speech | edge-tts (Microsoft) | Free |
| Video Rendering | FFmpeg + Pillow | Free |
| Hosting | Railway | ~$5/month |

## 🚀 Deploy on Railway

### 1. Clone & Push to GitHub
```bash
git init
git add .
git commit -m "initial"
git remote add origin https://github.com/YOUR_USER/reaper-bot
git push -u origin main
```

### 2. Create Railway Project
- Go to railway.app → New Project → Deploy from GitHub repo
- Select your repo

### 3. Set Environment Variables in Railway
```
GROQ_API_KEY=your_groq_api_key_here
```

### 4. Done!
Railway auto-detects `nixpacks.toml` and builds the app.

## 🔑 API Keys Needed
- **Groq API** → https://console.groq.com (free, no credit card)

## 📁 Project Structure
```
reaper_project/
├── app.py                   # Flask app
├── requirements.txt
├── nixpacks.toml            # Railway build config
├── Procfile
├── static/
│   └── characters/
│       ├── horror.png       # Horror Reaper character
│       └── chibi.png        # Chibi Reaper character
└── templates/
    └── index.html           # Dark UI with download button
```

## 🎬 Video Output
- Format: MP4 (H.264)
- Resolution: 1080×1920 (9:16 TikTok/Reels)
- Duration: ~30–60 seconds
- Audio: AAC 128k (two different AI voices)
