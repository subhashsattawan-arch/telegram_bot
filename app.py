import os
import re
import io
import html
import logging
from urllib.parse import urlparse, urlunparse

import requests
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFont
from flask import Flask, request, jsonify

# ------------------------------------------------------------
# Token aur Configuration
# ------------------------------------------------------------
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8857671703:AAHSIW_f1trqBwr43SyunwWUTjI8knMtipg").strip()
PORT = int(os.environ.get("PORT", "5000"))
BRAND = "SELECTION ROADMAP"
MARKS_CORRECT = float(os.environ.get("MARKS_CORRECT", "1"))
MARKS_WRONG = float(os.environ.get("MARKS_WRONG", "0.33"))

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("selection-roadmap")

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,hi;q=0.8",
})


# -------------------------- URL helpers --------------------------

def normalize_url(raw_url):
    raw_url = html.unescape((raw_url or "").strip())
    raw_url = raw_url.strip("<>()[]{}\"'.,;")
    raw_url = raw_url.replace("&amp;", "&")

    if not raw_url:
        raise ValueError("Link खाली है।")

    if not re.match(r"^https?://", raw_url, re.I):
        raw_url = "https://" + raw_url

    parsed = urlparse(raw_url)
    if not parsed.hostname:
        raise ValueError("URL सही नहीं लग रहा है।")

    host = parsed.hostname.lower()
    allowed = (
        host == "digialm.com"
        or host.endswith(".digialm.com")
        or host.endswith(".tcsion.com")
        or host == "tcsion.com"
    )
    if not allowed:
        raise ValueError("यह Digialm/TCS iON Answer Key लिंक नहीं लग रहा है।")

    return urlunparse((
        parsed.scheme, parsed.netloc, parsed.path,
        parsed.params, parsed.query, ""
    ))


def extract_url(message):
    if not message:
        return None
    matches = re.findall(r"https?://[^\s<>\"']+", message, flags=re.I)
    if not matches:
        matches = re.findall(
            r"(?:www\.)?(?:[a-z0-9.-]*digialm\.com|[a-z0-9.-]*tcsion\.com)/[^\s<>\"']*",
            message, flags=re.I
        )
    for candidate in matches:
        try:
            return normalize_url(candidate)
        except ValueError:
            continue
    return None


# -------------------------- Fetch and parse --------------------------

def fetch_answer_key(url):
    # Enhanced headers to prevent HTTP 400 Bad Request block from TCS iON
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,hi;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
    }
    
    response = SESSION.get(url, headers=headers, timeout=(15, 45), allow_redirects=True)
    log.info("Answer-key fetch: status=%s final_host=%s", response.status_code, urlparse(response.url).netloc)

    if response.status_code == 400:
        raise RuntimeError(
            "Digialm server ne HTTP 400 diya. "
            "Kripya answer key link ko dobara copy karke pura bhejein."
        )
    if response.status_code in (401, 403):
        raise RuntimeError(f"Answer Key server ne HTTP {response.status_code} diya.")
    if response.status_code == 404:
        raise RuntimeError("Answer Key page nahi mila (404).")
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    return soup


def norm_text(value):
    return re.sub(r"\s+", " ", (value or "")).strip()


def key_value(label):
    label = re.sub(r"[^a-z0-9]", "", label.lower())
    if "registrationnumber" in label or label in ("regno", "registrationno"):
        return "reg_no"
    if "rollnumber" in label or label in ("rollno", "roll"):
        return "roll_no"
    if "candidatename" in label or "participantname" in label or label == "name":
        return "candidate_name"
    if "community" in label or "category" == label:
        return "community"
    if "examdate" in label or label == "dateofexam":
        return "exam_date"
    if "examtime" in label or "examshift" in label or "shift" == label:
        return "exam_time"
    if "testname" in label or "examname" in label or label in ("subject", "exam"):
        return "subject"
    return None


def extract_candidate_info(soup):
    info = {
        "reg_no": "N/A",
        "roll_no": "N/A",
        "candidate_name": "N/A",
        "community": "N/A",
        "exam_date": "N/A",
        "exam_time": "N/A",
        "subject": "N/A",
    }

    for row in soup.find_all("tr"):
        cells = row.find_all(["th", "td"], recursive=False)
        if len(cells) >= 2:
            label = norm_text(cells[0].get_text(" ", strip=True))
            value = norm_text(cells[1].get_text(" ", strip=True))
            target = key_value(label)
            if target and value and value != ":":
                info[target] = value

    if info["subject"] == "N/A" and soup.title:
        title = norm_text(soup.title.get_text(" ", strip=True))
        if title:
            info["subject"] = title[:120]

    return info


def classify_section(text, current_section):
    t = text.lower()
    if any(k in t for k in ("general science", "science")):
        return "General Science"
    if any(k in t for k in ("mathematics", "maths", "quantitative aptitude")):
        return "Mathematics"
    if any(k in t for k in ("general intelligence", "reasoning", "logical ability")):
        return "General Intelligence and Reasoning"
    if any(k in t for k in ("general awareness", "current affairs", "general knowledge", "gk")):
        return "General Awareness and Current Affairs"
    return current_section or "Other"


def extract_question_blocks(soup):
    questions = []
    current_section = None
    seen = set()

    for node in soup.find_all(["h1", "h2", "h3", "h4", "caption", "b", "strong"]):
        text = norm_text(node.get_text(" ", strip=True))
        updated = classify_section(text, None)
        if updated != "Other":
            current_section = updated

    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        headers = []
        if rows:
            headers = [
                norm_text(c.get_text(" ", strip=True)).lower()
                for c in rows[0].find_all(["th", "td"], recursive=False)
            ]

        table_section = current_section
        caption = table.find("caption")
        if caption:
            table_section = classify_section(caption.get_text(" ", strip=True), table_section)

        for row in rows:
            cells = row.find_all(["th", "td"], recursive=False)
            if not cells:
                continue
            values = [norm_text(c.get_text(" ", strip=True)) for c in cells]
            row_text = " | ".join(values)
            maybe_section = classify_section(row_text, None)
            if maybe_section != "Other":
                table_section = maybe_section

            low = [v.lower() for v in values]
            joined = " ".join(low)
            if not any(k in joined for k in ("question id", "question no", "question number", "question")):
                continue

            chosen_idx = next((i for i, h in enumerate(headers)
                               if any(k in h for k in ("chosen option", "your answer", "candidate response",
                                                       "selected option", "chosen answer"))), None)
            correct_idx = next((i for i, h in enumerate(headers)
                                if any(k in h for k in ("correct option", "correct answer", "official answer"))), None)
            status_idx = next((i for i, h in enumerate(headers)
                               if any(k in h for k in ("status", "question status"))), None)

            details = {}
            for cell in cells:
                txt = norm_text(cell.get_text(" ", strip=True))
                if ":" in txt:
                    left, right = txt.split(":", 1)
                    l = left.lower()
                    if "chosen option" in l or "your answer" in l or "candidate response" in l:
                        details["chosen"] = right.strip()
                    elif "correct option" in l or "correct answer" in l or "official answer" in l:
                        details["correct"] = right.strip()
                    elif "question status" in l or l.strip() == "status":
                        details["status"] = right.strip()

            chosen = values[chosen_idx] if chosen_idx is not None and chosen_idx < len(values) else details.get("chosen")
            correct = values[correct_idx] if correct_idx is not None and correct_idx < len(values) else details.get("correct")
            status = values[status_idx] if status_idx is not None and status_idx < len(values) else details.get("status", "")

            if not chosen and not correct:
                continue

            qid = values[0] if values else str(len(questions) + 1)
            key = (qid, chosen or "", correct or "")
            if key in seen:
                continue
            seen.add(key)

            def clean_answer(value):
                value = norm_text(value or "")
                value = re.sub(r"^(?:option|answer)\s*[:\-]?\s*", "", value, flags=re.I)
                if value.lower() in ("--", "-", "not answered", "not attempted", "na", "n/a", ""):
                    return ""
                return value

            chosen = clean_answer(chosen)
            correct = clean_answer(correct)
            status_low = (status or "").lower()
            if any(x in status_low for x in ("not answered", "not attempted", "unattempted")):
                chosen = ""

            questions.append({
                "section": table_section or "Other",
                "chosen": chosen,
                "correct": correct,
                "status": status,
            })

    return questions


def answers_equal(chosen, correct):
    def canonical(s):
        s = norm_text(s).lower()
        s = re.sub(r"^(?:option|answer)\s*[:\-]?\s*", "", s)
        s = re.sub(r"[^a-z0-9]+", "", s)
        return s
    return canonical(chosen) == canonical(correct)


def calculate_results(questions):
    if not questions:
        raise RuntimeError("Answer key se questions aur responses nahi mil paye.")

    section_order = [
        "General Science",
        "Mathematics",
        "General Intelligence and Reasoning",
        "General Awareness and Current Affairs",
        "Other",
    ]
    stats = {}
    for q in questions:
        sec = q["section"] or "Other"
        stats.setdefault(sec, {"section": sec, "total": 0, "na": 0,
                               "right": 0, "wrong": 0, "marks": 0.0})
        item = stats[sec]
        item["total"] += 1
        if not q["chosen"]:
            item["na"] += 1
        elif answers_equal(q["chosen"], q["correct"]):
            item["right"] += 1
            item["marks"] += MARKS_CORRECT
        else:
            item["wrong"] += 1
            item["marks"] -= MARKS_WRONG

    sections = [stats[k] for k in section_order if k in stats]
    sections.extend(v for k, v in stats.items() if k not in section_order)

    totals = {
        "total": sum(s["total"] for s in sections),
        "na": sum(s["na"] for s in sections),
        "right": sum(s["right"] for s in sections),
        "wrong": sum(s["wrong"] for s in sections),
        "marks": sum(s["marks"] for s in sections),
    }
    for s in sections:
        s["marks"] = round(s["marks"], 2)
    totals["marks"] = round(totals["marks"], 2)
    return {"sections": sections, "totals": totals}


# -------------------------- HD scorecard image --------------------------

def load_font(size, bold=False):
    candidates = (
        [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
            "arialbd.ttf",
        ] if bold else [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
            "arial.ttf",
        ]
    )
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            pass
    return ImageFont.load_default()


def fit_text(draw, text, font, max_width):
    text = str(text)
    if draw.textbbox((0, 0), text, font=font)[2] <= max_width:
        return text
    while text and draw.textbbox((0, 0), text + "…", font=font)[2] > max_width:
        text = text[:-1]
    return text + "…"


def generate_hd_scorecard(info, results):
    W = 1800
    margin = 48
    inner_w = W - 2 * margin
    navy = (24, 43, 73)
    red = (185, 28, 28)
    yellow = (250, 204, 21)
    black = (30, 30, 30)
    grey = (90, 90, 90)
    white = (255, 255, 255)

    title_font = load_font(43, True)
    sub_font = load_font(25, False)
    label_font = load_font(27, True)
    value_font = load_font(28, False)
    table_font = load_font(24, False)
    table_bold = load_font(25, True)
    small_font = load_font(22, False)

    info_rows = [
        ("Registration Number", info.get("reg_no", "N/A")),
        ("Roll Number", info.get("roll_no", "N/A")),
        ("Candidate Name", info.get("candidate_name", "N/A")),
        ("Community", info.get("community", "N/A")),
        ("Exam Date", info.get("exam_date", "N/A")),
        ("Exam Time / Shift", info.get("exam_time", "N/A")),
        ("Exam Name / Subject", info.get("subject", "N/A")),
    ]
    info_h = 88
    header_h = 82
    row_h = 100
    total_h = 88
    footer_h = 105
    H = 165 + 72 + len(info_rows) * info_h + 24 + header_h + len(results["sections"]) * row_h + total_h + footer_h + 70

    img = Image.new("RGB", (H if H > 0 else 1500, W), white) if False else Image.new("RGB", (W, H), white)
    draw = ImageDraw.Draw(img)

    draw.rectangle((12, 12, W - 12, H - 12), outline=red, width=7)
    draw.rectangle((margin, 35, W - margin, 150), fill=navy)
    title = "EXAM SCORECARD & ANALYSIS"
    draw.text((W // 2, 53), title, fill=white, font=title_font, anchor="mt")
    draw.text((W // 2, 108), BRAND, fill=(255, 230, 90), font=sub_font, anchor="mt")

    y = 175
    label_w = 570
    for label, value in info_rows:
        draw.rectangle((margin, y, margin + label_w, y + info_h), outline=(55, 55, 55), width=3)
        draw.rectangle((margin + label_w, y, W - margin, y + info_h), outline=(55, 55, 55), width=3)
        draw.text((margin + 22, y + info_h // 2), label, fill=black, font=label_font, anchor="lm")
        max_val_width = inner_w - label_w - 42
        value = fit_text(draw, value, value_font, max_val_width)
        draw.text((margin + label_w + 22, y + info_h // 2), value, fill=black, font=value_font, anchor="lm")
        y += info_h

    y += 24
    widths = [660, 190, 170, 210, 210, inner_w - 1440]
    headers = ["Section", "Total", "NA", "Right", "Wrong", "Marks"]
    x = margin
    draw.rectangle((margin, y, W - margin, y + header_h), fill=red, outline=black, width=3)
    for heading, cw in zip(headers, widths):
        draw.rectangle((x, y, x + cw, y + header_h), outline=black, width=3)
        draw.text((x + cw / 2, y + header_h / 2), heading, fill=white, font=table_bold, anchor="mm")
        x += cw
    y += header_h

    def draw_table_row(values, fill, bold=False, height=row_h):
        nonlocal y
        font = table_bold if bold else table_font
        x = margin
        for i, (value, cw) in enumerate(zip(values, widths)):
            draw.rectangle((x, y, x + cw, y + height), fill=fill, outline=(55, 55, 55), width=3)
            if i == 0:
                text = str(value)
                maxw = cw - 28
                words = text.split()
                lines, line = [], ""
                for word in words:
                    test = (line + " " + word).strip()
                    if draw.textbbox((0, 0), test, font=font)[2] <= maxw:
                        line = test
                    else:
                        if line:
                            lines.append(line)
                        line = word
                if line:
                    lines.append(line)
                if len(lines) > 2:
                    lines = lines[:2]
                    lines[-1] = fit_text(draw, lines[-1], font, maxw)
                line_h = 31
                start_y = y + (height - line_h * len(lines)) / 2
                for j, ln in enumerate(lines):
                    draw.text((x + 16, start_y + j * line_h), ln, fill=black, font=font)
            else:
                draw.text((x + cw / 2, y + height / 2), str(value),
                          fill=black, font=font, anchor="mm")
            x += cw
        y += height

    for sec in results["sections"]:
        draw_table_row([
            sec["section"], sec["total"], sec["na"], sec["right"],
            sec["wrong"], f'{sec["marks"]:.2f}'
        ], white)

    totals = results["totals"]
    draw_table_row([
        "TOTAL", totals["total"], totals["na"], totals["right"],
        totals["wrong"], f'{totals["marks"]:.2f}'
    ], yellow, bold=True, height=total_h)

    y += 22
    draw.text((W // 2, y),
              f"Marking Scheme: +{MARKS_CORRECT:g} for Correct, -{MARKS_WRONG:g} for Incorrect",
              fill=grey, font=small_font, anchor="mt")
    y += 34
    draw.text((W // 2, y), f"Generated by {BRAND} | Verify with the official response sheet",
              fill=grey, font=small_font, anchor="mt")

    output = io.BytesIO()
    img.save(output, format="PNG", optimize=True, dpi=(300, 300))
    output.seek(0)
    return output


# -------------------------- Telegram Bot API --------------------------

def telegram_api(method, data=None, files=None, timeout=45):
    if not TOKEN:
        raise RuntimeError("Telegram Bot Token सेट नहीं है।")
    endpoint = f"https://api.telegram.org/bot{TOKEN}/{method}"
    response = requests.post(endpoint, data=data, files=files, timeout=timeout)
    try:
        payload = response.json()
    except ValueError:
        payload = {"ok": False, "description": response.text[:500]}
    if response.status_code >= 400 or not payload.get("ok"):
        log.error("Telegram API %s failed: %s", method, payload)
        raise RuntimeError(payload.get("description", f"Telegram API HTTP {response.status_code}"))
    return payload


def send_message(chat_id, text, reply_to=None):
    data = {"chat_id": chat_id, "text": text}
    if reply_to:
        data["reply_to_message_id"] = reply_to
    return telegram_api("sendMessage", data=data)


def send_photo(chat_id, photo_buffer, caption, reply_to=None):
    data = {"chat_id": chat_id, "caption": caption}
    if reply_to:
        data["reply_to_message_id"] = reply_to
    files = {"photo": ("selection_roadmap_scorecard.png", photo_buffer, "image/png")}
    return telegram_api("sendPhoto", data=data, files=files, timeout=90)


def process_telegram_update(update):
    message = update.get("message") or update.get("edited_message")
    if not message:
        return
    chat = message.get("chat", {}).get("id")
    message_id = message.get("message_id")
    text = message.get("text", "") or ""
    if not chat:
        return

    if text.strip().startswith("/start"):
        send_message(
            chat,
            "🤖 Welcome to SELECTION ROADMAP!\n\n"
            "अपनी TCS iON / Digialm Answer Key का पूरा link भेजें।",
            message_id
        )
        return

    url = extract_url(text)
    if not url:
        send_message(
            chat,
            "⚠️ कृपया पूरा Digialm/TCS iON Answer Key URL भेजें।",
            message_id
        )
        return

    send_message(chat, "⏳ Answer Key पढ़ रहा हूँ और HD scorecard बना रहा हूँ…", message_id)
    try:
        soup = fetch_answer_key(url)
        info = extract_candidate_info(soup)
        questions = extract_question_blocks(soup)
        results = calculate_results(questions)
        image_buffer = generate_hd_scorecard(info, results)
        send_photo(
            chat,
            image_buffer,
            f"✅ Scorecard generated by {BRAND}\n"
            f"Total: {results['totals']['total']} | "
            f"Right: {results['totals']['right']} | "
            f"Wrong: {results['totals']['wrong']} | "
            f"NA: {results['totals']['na']} | "
            f"Marks: {results['totals']['marks']:.2f}",
            message_id
        )
    except Exception as exc:
        log.exception("Scorecard generation failed")
        send_message(chat, f"❌ {str(exc)[:900]}", message_id)


# -------------------------- Flask webhook --------------------------

@app.route("/", methods=["GET"])
def index():
    return jsonify({
        "status": "running",
        "service": "Selection Roadmap Scorecard Bot",
        "token_configured": bool(TOKEN),
    }), 200


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"ok": True}), 200


@app.route("/" + TOKEN, methods=["POST"])
def telegram_webhook():
    if not TOKEN:
        return jsonify({"ok": False, "error": "Token is not configured"}), 500
    update = request.get_json(silent=True)
    if not isinstance(update, dict):
        return jsonify({"ok": False, "error": "Invalid JSON update"}), 400

    try:
        process_telegram_update(update)
    except Exception:
        log.exception("Webhook processing failed")
    return jsonify({"ok": True}), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)