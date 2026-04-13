#  MediRaksha — AI Medical Report Summarizer

MediRaksha is an AI-powered system that analyzes and summarizes medical reports into structured, easy-to-understand insights. It helps doctors quickly interpret reports and enables patients to understand their health in simple language.



##  Features

*  Upload medical reports (PDF)
*  Automatic report type detection (Lab, Prescription, Discharge Summary, etc.)
*  AI-powered extraction using LLM (Groq)
*  Structured data extraction:
* Patient details
* Diagnoses
* Lab results
* Medications
* Clinical findings
*  Rule-based validation engine:
* Detects abnormal values
* Infers conditions (e.g., Anaemia, Diabetes)
* Removes incorrect AI outputs
*  Risk level classification (Low / Moderate / High / Critical)
*  Multi-language support (9 Indian languages)
*  Professional PDF report generation
*  Chatbot to ask questions about reports
*  Persistent audit logging using SQLite



##  How It Works

1. User uploads a medical report (PDF)
2. System detects report type automatically
3. Extracted text is processed using AI (Groq LLM)
4. Structured data is generated
5. Post-processing engine validates results using medical rules
6. Summary is generated and translated (if needed)
7. Report is stored in audit log database
8. User can interact using chatbot or download PDF



##  Project Structure


Mediraksha/
│
├── app.py                 # App factory & entry point
├── config.py              # Environment configuration
├── modules/               # Core logic modules
│   ├── audit.py
│   ├── detection.py
│   ├── extraction.py
│   ├── pdf_generator.py
│   ├── prompts.py
│   ├── providers.py
│   ├── routes.py
│   ├── sanitizer.py
│   ├── translation.py
│   ├── validation.py
│
├── templates/             # Frontend HTML
├── data/                  # SQLite database (audit logs)
├── requirements.txt
└── README.md
```


##  Setup & Installation

### 1. Clone the repository

```
git clone https://github.com/Rigveda1610/Mediraksha.git
cd Mediraksha
```

---

### 2. Create virtual environment (recommended)

```
python -m venv venv
```

Activate:

Windows:

```
venv\Scripts\activate
```

---

### 3. Install dependencies

```
pip install -r requirements.txt
```

---

### 4. Configure environment variables

Create a `.env` file:

```
GROQ_API_KEY=your_groq_api_key
SECRET_KEY=your_secret_key
```

---

### 5. Run the application

```
python app.py
```

---

### 6. Open in browser

```
http://localhost:5000
```

---

##  API Endpoints

* `/analyze` → Analyze medical report
* `/ask` → Chatbot Q&A
* `/audit` → View audit logs
* `/download_pdf` → Download report
* `/health` → System health check



##  Tech Stack

* Python (Flask)
* Groq API (LLM)
* SQLite (Audit Logs)
* HTML/CSS (Frontend)
* PDF Processing Libraries

---

##  Key Highlights

* Modular backend architecture (production-ready)
* SQLite-based persistent audit logging
* Rule-based medical validation engine
* Multi-language patient-friendly summaries
* AI + deterministic validation hybrid system

---

##  Future Improvements

* OpenAI integration (multi-provider AI support)
* Doctor dashboard with patient history
* Graph-based trend analysis
* EMR/Hospital system integration
* Enhanced security & authentication

---

##  Author

**Rigveda Mhatre**

---

## ⭐ If you like this project

Give it a ⭐ on GitHub!
