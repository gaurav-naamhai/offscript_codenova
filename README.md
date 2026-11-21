# Inkloom AI — Pre-Publication Brand Governance & Verification

> **See tomorrow's headline today, and fix the mistake before it reaches your customers.**

Inkloom AI is an intelligent brand safety assistant for marketing teams, copywriters, and agencies. Before you publish a social post, press release, ad banner, or product brief, Inkloom checks your draft against your internal brand guidelines **and** live external facts. It highlights exact mistakes, explains the risks, and offers one-click fixes.

---

## 🚀 Quick Access

### 1. Try It in Your Browser
If you have access to our live web deployment, navigate to:
* **Web Application:** `https://offscript-codenova.onrender.com`
* *Note on free-tier cloud instances:* If the server has been idle, it may take 30–50 seconds on the first request to wake up. A countdown timer will show you the status.

### 2. Instant 1-Click Demo Sign-In
You don't need to create an account to test Inkloom. Click the **Demo Accounts** tab on the login screen to sign in with one click, or use any of the credentials below:

| Brand / Workspace | Role | Email | Password | What You Can Do |
|---|---|---|---|---|
| **BrightLeaf Organics** | **Creator** | `creator@brightleaf.co` | `brightleaf123` | Draft copy, upload PDFs/images, accept AI fixes, submit for review |
| **BrightLeaf Organics** | **Manager** | `manager@brightleaf.co` | `brightleaf123` | Conduct Stage 1 review, edit rules in the Guideline Rectification loop |
| **BrightLeaf Organics** | **Final Reviewer** | `reviewer@brightleaf.co` | `brightleaf123` | Grant final publication sign-off, authorize overrides, export certificates |
| **Nike Demo** | **Creator** | `creator@nike.demo` | `nike123` | Test athletic apparel copy, footwear slogans, and claim verification |
| **Nike Demo** | **Manager** | `manager@nike.demo` | `nike123` | Manage Nike brand identity rules and approve creator submissions |
| **Nike Demo** | **Final Reviewer** | `reviewer@nike.demo` | `nike123` | Issue official compliance certificates for approved campaigns |
| **Inkloom Workspace** | **Creator** | `creator@inkloom.ai` | `inkloom123` | Test B2B enterprise software copy, SLAs, and technical whitepapers |

---

## 🏃 Run Locally (in under 3 minutes)

If you are running the project on your own machine:

### Prerequisites
* **Python 3.11+** installed
* **Node.js 18+** installed

### Step 1: Clone the repository
```bash
git clone https://github.com/gaurav-naamhai/offscript_codenova.git
cd offscript_codenova
```

### Step 2: Start the Backend (Terminal 1)
```bash
cd backend
python -m venv .venv

# Activate virtual environment:
# On Windows:
.venv\Scripts\activate
# On Mac/Linux:
# source .venv/bin/activate

pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```
Your backend API will be live at `http://localhost:8000`.

### Step 3: Start the Frontend (Terminal 2)
```bash
cd frontend
npm install
npm run dev
```
Open `http://localhost:5173` in your browser.

---

## 📖 Step-by-Step User Guide

### 1. Choose Your Brand Workspace
When you open Inkloom, click **Demo Accounts** and pick an organization (for example, **BrightLeaf Organics**). Each workspace is completely isolated: BrightLeaf's copywriters will only ever see BrightLeaf rules and submissions.

### 2. Inspect a Pre-Seeded Draft or Create a New One
* **Browse existing drafts:** On the Dashboard or Library, click any demo submission, such as `[Demo] Weekend Flash Promo Copy`.
* **Or create your own:** Click **+ New Review** in the navigation bar. You can:
  * **Paste Draft Text:** Write or paste an email newsletter, tweet, or press release.
  * **Upload an Image:** Drop a PNG, JPEG, or WebP banner to check visual branding and text contrast.
  * **Upload a PDF:** Drop a multi-page PDF brochure or product sheet.

### 3. Run the Compliance Check
Click **Start Compliance Check** (or **Retry check**). The automated engine runs several checks in parallel:
* **Extracting text:** Reads text and parses visual layouts.
* **Retrieving brand guidelines:** Searches your organization's approved guidelines.
* **Verifying external facts:** Checks factual statements, discounts, and statistics against live authoritative sources.

### 4. Switch Between Review Lenses
At the top of the Review Workspace, use the **Review Lens** toggle:
* **Brand Guidelines:** Highlights what violates your internal brand style, tone, prohibited terms, or visual standards.
* **External Facts & Claims:** Highlights unverified performance claims, health guarantees, or inaccurate discount figures.
* **All Findings:** Shows the complete audit list.

### 5. Read the 4-Section Finding Cards
Every flagged issue is presented with transparent evidence:
1. **Supporting Evidence (Top):** Shows the exact brand guideline chunk or external website used as proof, including similarity percentage and a direct link.
2. **Flagged Content (Middle):** The exact offending phrase is highlighted in your text. Clicking it will scroll and highlight that sentence in your draft on the left.
3. **Conflict Explanation (Middle):** Explains in plain English why the draft conflicts with the rule and what the commercial/brand risk is.
4. **Suggestions & Actions (Bottom):** Provides a minimal, intent-preserving rewrite with a visual diff (red for removed words, green for added words).

### 6. Apply Fixes with 1 Click
* Click **Accept change** to automatically update the draft text.
* Click **Preview recheck** to see if the issue is resolved without triggering new flags.
* Click **Edit manually** if you prefer to rewrite the copy yourself.

### 7. Approvals & Compliance Sign-Off
* **Separation of Duties:** A creator cannot approve their own copy. Once changes are made, switch account to **Manager** or **Final Reviewer**.
* **Approval Gates:** If there are open blocking issues, approval is blocked unless an authorized reviewer records an explicit override reason ($\ge 10$ characters).
* **Download Sign-Off Certificate:** Once approved, click **Export Certificate** to download an immutable compliance audit record.

---

## 🌟 Key Capabilities at a Glance

* **Auto-Compiled Brand Constitution (`#/knowledge`):** Upload your brand handbook once. Inkloom automatically extracts approved facts, forbidden terms, and official color palettes.
* **Guideline Rectification Loop (`#/knowledge/rectify`):** Audits your brand guidelines for confusing, conflicting, or outdated rules, allowing managers to edit and publish clearer wording (`v1.0 → v1.1`).
* **Live Coaching While Typing:** As you write in the New Review box, Inkloom alerts you to recurring mistakes before you even click submit.
* **Deterministic WCAG Contrast Checking:** Uploaded graphics are analyzed with mathematical luminance formulas to prevent unreadable text overlays.
* **Anti-Fabrication Protection:** The AI suggestions engine is programmatically forbidden from inventing fake specifications, prices, or product benefits.

---

## ❓ Frequently Asked Questions (FAQ)

#### Q: What file formats are supported?
* **Text:** Direct paste or typing up to 50,000 characters.
* **Images:** PNG, JPEG, WebP (up to 5MB).
* **Documents:** PDF (up to 10MB).
* *Note:* Microsoft Word (`.docx`) is not supported. Please save Word files as PDF or copy-paste the text.

#### Q: Why does the compliance check take a few seconds?
Inkloom does not use a shallow generic chatbot. It extracts text from your document, performs multi-query vector searches across your brand knowledge base, scans live external web sources, and verifies WCAG accessibility formulas. This usually completes in 3 to 6 seconds.

#### Q: What happens if an AI service is temporarily busy?
Inkloom features built-in backpressure protection. If an upstream AI provider reaches a rate limit, the system gracefully preserves all completed checks, alerts you with a clear retry cooldown timer, and allows you to retry the failed check with one click without losing your work.

#### Q: Is my company's draft data private?
Yes. Every organization (BrightLeaf, Nike, Inkloom) is partitioned by `org_id`. Submissions, version snapshots, and brand documents are strictly isolated; one organization can never see or search another organization's data.

---

## 💬 Support & Feedback
Built by **Team OFFSCRIPT**. If you encounter an issue, have feedback, or want to integrate Inkloom with your CMS, open an issue on GitHub or reach out to the team!
