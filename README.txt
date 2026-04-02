╔══════════════════════════════════════════════════╗
║   MediRaksha — AI Medical Report Summarizer      ║
╚══════════════════════════════════════════════════╝

WHY THE OLD FILE DIDN'T WORK
──────────────────────────────
Opening an HTML file directly (file://) causes
"Failed to fetch" because browsers block all
external API calls from local files (CORS policy).

This version fixes it — Flask handles all API
calls on the server side, so the browser only
talks to localhost.

═══════════════════════════════════════════════════
HOW TO RUN  (3 simple steps)
═══════════════════════════════════════════════════

STEP 1 — Install Python packages
──────────────────────────────────
Open Terminal / Command Prompt in this folder:

    pip install -r requirements.txt


STEP 2 — Start the app
────────────────────────
    python app.py

You will see:
    Server running at: http://localhost:5000


STEP 3 — Open in browser
──────────────────────────
Go to:  http://localhost:5000

That's it!


═══════════════════════════════════════════════════
FREE API KEYS  (takes ~30 seconds each)
═══════════════════════════════════════════════════

GOOGLE GEMINI  (recommended — best free tier)
  → https://aistudio.google.com/app/apikey
  → Click "Create API Key"
  → Free: 1,500 requests/day, no credit card

GROQ  (very fast)
  → https://console.groq.com/keys
  → Click "Create API Key"
  → Free: 30 requests/min, no credit card


═══════════════════════════════════════════════════
FOLDER STRUCTURE
═══════════════════════════════════════════════════

mediraksha/
├── app.py               ← Run this file
├── requirements.txt     ← Python dependencies
├── README.txt           ← This file
└── templates/
    └── index.html       ← Web UI (auto-served)


═══════════════════════════════════════════════════
TROUBLESHOOTING
═══════════════════════════════════════════════════

Problem              | Fix
─────────────────────|───────────────────────────────
ModuleNotFoundError  | pip install -r requirements.txt
Port 5000 in use     | Change port=5000 to port=5001
                     | in app.py (last line)
Invalid API key      | Double-check key, re-save it
No internet          | Check your network connection
PDF won't download   | Make sure app.py is still running


Press Ctrl+C in the terminal to stop the server.
