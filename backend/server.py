"""
Simple nutrition tracking web server.

This server provides endpoints to set daily/weekly nutrition goals, upload food images,
calculate macros (simulated AI using average image color), and retrieve daily and
weekly summaries. It uses only the Python standard library and Pillow for image
processing, so it runs in restricted environments without external packages.

Routes:
    GET /              – Home page with navigation links.
    GET /set_goals     – Display form to set goals.
    POST /set_goals    – Process goals form submission (JSON or form encoded).
    GET /upload        – Display form to upload food image.
    POST /upload       – Handle image upload and update daily log.
    GET /daily         – Return daily totals as JSON or HTML.
    GET /weekly_summary – Return weekly summary as JSON or HTML.

Database:
    A SQLite database (nutrition.db) with three tables:
        users(id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT)
        goals(
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
            daily_calories REAL, daily_protein REAL, daily_fat REAL, daily_carbs REAL,
            weekly_calories REAL, weekly_protein REAL, weekly_fat REAL, weekly_carbs REAL
        )
        logs(
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, date TEXT,
            calories REAL DEFAULT 0, protein REAL DEFAULT 0, fat REAL DEFAULT 0, carbs REAL DEFAULT 0
        )

The server assumes a single user (user_id=1). Multi-user support could be added by
expanding the logic to handle authentication and per-user data.

Author: ChatGPT
Date: 2026-05-15
"""

import io
import json
import os
import sqlite3
from datetime import datetime, timedelta, time as dt_time
from http import server
from urllib.parse import parse_qs

from PIL import Image


DB_PATH = os.path.join(os.path.dirname(__file__), 'nutrition.db')

# Directory to store uploaded images
UPLOAD_DIR = os.path.join(os.path.dirname(__file__), 'uploads')

# Hebrew day-of-week mapping (Python weekday: Monday=0 .. Sunday=6 -> Hebrew letters)
HEBREW_DAYS = {0: 'ב', 1: 'ג', 2: 'ד', 3: 'ה', 4: 'ו', 5: 'ש', 6: 'א'}

def hebrew_day_of_week(date_obj):
    """Return the Hebrew first letter for the day of week."""
    return HEBREW_DAYS.get(date_obj.weekday(), '')


def init_db():
    """Initialize the SQLite database if it doesn't exist."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS goals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            daily_calories REAL,
            daily_protein REAL,
            daily_fat REAL,
            daily_carbs REAL,
            weekly_calories REAL,
            weekly_protein REAL,
            weekly_fat REAL,
            weekly_carbs REAL
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            date TEXT,
            calories REAL DEFAULT 0,
            protein REAL DEFAULT 0,
            fat REAL DEFAULT 0,
            carbs REAL DEFAULT 0
        );
        """
    )
    # Insert default user if none exists
    cur.execute("SELECT COUNT(*) FROM users")
    if cur.fetchone()[0] == 0:
        cur.execute("INSERT INTO users (username) VALUES (?)", ("default_user",))
    conn.commit()
    conn.close()

    # Ensure upload directory exists
    os.makedirs(UPLOAD_DIR, exist_ok=True)


def get_connection():
    return sqlite3.connect(DB_PATH)


def get_start_of_day(now=None):
    """Return datetime for start of day (5:00) relative to 'now'."""
    if now is None:
        now = datetime.now()
    start = datetime.combine(now.date(), dt_time(5))
    if now < start:
        start -= timedelta(days=1)
    return start


def analyze_image(file_data):
    """
    Simulate AI-based food recognition.

    Uses the average color of the uploaded image to classify it into one of three
    categories and returns approximate macro values. This is a placeholder for
    integration with a real food-recognition model.
    """
    try:
        with Image.open(io.BytesIO(file_data)) as img:
            img = img.resize((64, 64))  # Resize for efficiency
            pixels = list(img.getdata())
            avg_r = sum(p[0] for p in pixels) / len(pixels)
            avg_g = sum(p[1] for p in pixels) / len(pixels)
            avg_b = sum(p[2] for p in pixels) / len(pixels)
    except Exception:
        # In case of any error, return neutral macros
        return {'calories': 100, 'protein': 5, 'fat': 5, 'carbs': 15, 'category': 'unknown'}

    # Basic classification: red-dominant = meat, green-dominant = vegetable, otherwise = carb
    if avg_r > avg_g and avg_r > avg_b:
        return {'calories': 250, 'protein': 30, 'fat': 15, 'carbs': 5, 'category': 'meat-like'}
    elif avg_g > avg_r and avg_g > avg_b:
        return {'calories': 90, 'protein': 3, 'fat': 2, 'carbs': 12, 'category': 'vegetable-like'}
    else:
        return {'calories': 200, 'protein': 5, 'fat': 3, 'carbs': 30, 'category': 'carb-like'}


class NutritionHandler(server.BaseHTTPRequestHandler):
    """HTTP request handler for the nutrition tracking app."""

    def _send_response(self, content, status=200, content_type='text/html'):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self):
        if self.path.startswith('/set_goals'):
            self._serve_set_goals_form()
        elif self.path.startswith('/upload'):
            self._serve_upload_form()
        elif self.path.startswith('/add_food'):
            self._serve_add_food_form()
        elif self.path.startswith('/daily'):
            self._serve_daily_summary()
        elif self.path.startswith('/weekly_summary'):
            self._serve_weekly_summary()
        elif self.path.startswith('/uploads/'):
            # Serve uploaded images statically
            self._serve_upload_file()
        else:
            self._serve_home()

    def do_POST(self):
        if self.path.startswith('/set_goals'):
            self._handle_set_goals()
        elif self.path.startswith('/upload'):
            self._handle_upload()
        elif self.path.startswith('/add_food'):
            self._handle_add_food()
        else:
            self._send_response(b'Not Found', 404)

    # HTML templates
    def _html_page(self, title, body):
        """Wrap body content in a styled HTML page."""
        # Global CSS for modern, centered design
        styles = """
        body { font-family: 'Segoe UI', Tahoma, sans-serif; background: #f0f2f5; margin: 0; padding: 40px; display: flex; justify-content: center; direction: rtl; }
        .container { width: 100%; max-width: 800px; background: #ffffff; padding: 24px 32px; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.05); text-align: right; }
        h1 { color: #333333; margin-top: 0; }
        label { display: block; margin-top: 12px; font-weight: bold; }
        input[type=number], input[type=text], input[type=file] { width: 100%; padding: 10px; margin-top: 6px; border: 1px solid #cccccc; border-radius: 6px; box-sizing: border-box; }
        button { background: #007bff; color: #ffffff; border: none; border-radius: 6px; padding: 10px 16px; font-size: 16px; cursor: pointer; margin-top: 20px; }
        button:hover { background: #0056b3; }
        .nav { display: flex; justify-content: center; flex-wrap: wrap; gap: 10px; margin-top: 30px; }
        .nav a { background: #6c757d; color: #ffffff; padding: 10px 20px; border-radius: 6px; text-decoration: none; transition: background 0.3s; }
        .nav a:hover { background: #495057; }
        .summary-list { list-style: none; padding-left: 0; }
        .summary-list li { background: #f8f9fa; margin: 6px 0; padding: 12px; border-radius: 6px; display: flex; justify-content: space-between; align-items: center; }
        .summary-list li span { font-weight: bold; }
        .upload-preview { margin-top: 12px; }
        img.preview { max-width: 100%; border-radius: 8px; margin-top: 12px; }
        form { margin-top: 20px; }
        .intro { font-size: 18px; margin-bottom: 20px; color: #555; line-height: 1.4; }
        .card-buttons { display: flex; flex-direction: column; gap: 15px; margin-top: 30px; }
        .card-buttons a { display: block; text-align: center; background: #17a2b8; color: #fff; padding: 14px 20px; border-radius: 8px; font-size: 18px; text-decoration: none; transition: background 0.3s; }
        .card-buttons a:hover { background: #117a8b; }
        /* Macro progress bar styles */
        .macro-bar { margin-bottom: 20px; }
        .macro-bar-label { font-weight: bold; margin-bottom: 4px; text-align: right; }
        .macro-bar-track { background: #e9ecef; border-radius: 10px; height: 20px; width: 100%; overflow: hidden; }
        .macro-bar-fill { height: 100%; border-radius: 10px 0 0 10px; }
        .macro-bar-info { font-size: 14px; margin-top: 4px; color: #555; text-align: right; }
        /* Weekly day card styles */
        .day-card { background: #f8f9fa; border: 1px solid #dee2e6; border-radius: 10px; padding: 16px 20px; margin-bottom: 20px; }
        .day-card h2 { margin-top: 0; margin-bottom: 12px; font-size: 20px; color: #333; text-align: right; }
        """
        nav_html = """
        <div class='nav'>
            <a href='/'>דף הבית</a>
            <a href='/set_goals'>הגדרת מטרות</a>
            <a href='/upload'>העלאת תמונה</a>
            <a href='/add_food'>הוספת מאכל</a>
            <a href='/daily'>סיכום יומי</a>
            <a href='/weekly_summary'>סיכום שבועי</a>
        </div>
        """
        return f"""<!DOCTYPE html>
<html lang='he'>
<head>
    <meta charset='UTF-8'>
    <meta name='viewport' content='width=device-width, initial-scale=1.0'>
    <title>{title}</title>
    <style>{styles}</style>
</head>
<body>
    <div class='container'>
        {body}
        {nav_html}
    </div>
</body>
</html>"""

    def _serve_home(self):
        body = """
        <h1>ברוכים הבאים!</h1>
        <p class='intro'>אפליקציית ניטור התזונה שלך כאן. עקוב אחרי הקלוריות והמאקרו‑נוטריינטים שלך באמצעות הגדרת יעדים, העלאת תמונות, הזנת מאכלים והצגת סיכומים.</p>
        <div class='card-buttons'>
            <a href='/set_goals'>הגדרת מטרות</a>
            <a href='/upload'>העלאת תמונה</a>
            <a href='/add_food'>הוספת מאכל ידנית</a>
            <a href='/daily'>סיכום יומי</a>
            <a href='/weekly_summary'>סיכום שבועי</a>
        </div>
        """
        page = self._html_page('דף הבית', body)
        self._send_response(page.encode('utf-8'))

    def _serve_set_goals_form(self):
        # Retrieve existing goals for display
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT daily_calories, daily_protein, daily_fat, daily_carbs, weekly_calories, weekly_protein, weekly_fat, weekly_carbs FROM goals WHERE user_id=1 ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
        conn.close()
        daily_cal, daily_prot, daily_fat, daily_carbs, weekly_cal, weekly_prot, weekly_fat, weekly_carbs = row if row else (2000, 150, 70, 250, 14000, 1050, 490, 1750)
        body = f"""
        <h1>הגדרת מטרות</h1>
        <p class='intro'>הזן את היעדים היומיים והשבועיים שלך כדי שנוכל לעזור לך לעקוב אחרי המאקרו‑נוטריינטים והקלוריות.</p>
        <form method='post' action='/set_goals'>
            <label for='daily_calories'>קלוריות יומיות:</label>
            <input type='number' id='daily_calories' name='daily_calories' value='{daily_cal}' required>
            <label for='daily_protein'>חלבון יומי (גרם):</label>
            <input type='number' id='daily_protein' name='daily_protein' value='{daily_prot}' required>
            <label for='daily_fat'>שומן יומי (גרם):</label>
            <input type='number' id='daily_fat' name='daily_fat' value='{daily_fat}' required>
            <label for='daily_carbs'>פחמימות יומיות (גרם):</label>
            <input type='number' id='daily_carbs' name='daily_carbs' value='{daily_carbs}' required>
            <label for='weekly_calories'>קלוריות שבועיות:</label>
            <input type='number' id='weekly_calories' name='weekly_calories' value='{weekly_cal}' required>
            <label for='weekly_protein'>חלבון שבועי (גרם):</label>
            <input type='number' id='weekly_protein' name='weekly_protein' value='{weekly_prot}' required>
            <label for='weekly_fat'>שומן שבועי (גרם):</label>
            <input type='number' id='weekly_fat' name='weekly_fat' value='{weekly_fat}' required>
            <label for='weekly_carbs'>פחמימות שבועיות (גרם):</label>
            <input type='number' id='weekly_carbs' name='weekly_carbs' value='{weekly_carbs}' required>
            <button type='submit'>שמירה</button>
        </form>
        """
        page = self._html_page('הגדרת מטרות', body)
        self._send_response(page.encode('utf-8'))

    def _handle_set_goals(self):
        # Handle form submission for goals
        length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(length)
        # Parse form data
        parsed = parse_qs(post_data.decode('utf-8'))
        try:
            daily_cal = float(parsed.get('daily_calories', ['0'])[0])
            daily_prot = float(parsed.get('daily_protein', ['0'])[0])
            daily_fat = float(parsed.get('daily_fat', ['0'])[0])
            daily_carbs = float(parsed.get('daily_carbs', ['0'])[0])
            weekly_cal = float(parsed.get('weekly_calories', ['0'])[0])
            weekly_prot = float(parsed.get('weekly_protein', ['0'])[0])
            weekly_fat = float(parsed.get('weekly_fat', ['0'])[0])
            weekly_carbs = float(parsed.get('weekly_carbs', ['0'])[0])
        except Exception:
            self._send_response(b'Invalid input', 400)
            return
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO goals (user_id, daily_calories, daily_protein, daily_fat, daily_carbs, weekly_calories, weekly_protein, weekly_fat, weekly_carbs) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (1, daily_cal, daily_prot, daily_fat, daily_carbs, weekly_cal, weekly_prot, weekly_fat, weekly_carbs)
        )
        conn.commit()
        conn.close()
        # Redirect back to set_goals page
        self.send_response(303)
        self.send_header('Location', '/set_goals')
        self.end_headers()

    def _serve_upload_form(self):
        body = """
        <h1>העלאת תמונה</h1>
        <p class='intro'>צלם או בחר תמונה של המנה שברצונך לנתח. נשתמש ב‑AI כדי להעריך את הערכים התזונתיים ולצרף אותם ליומן היומי שלך.</p>
        <form method='post' action='/upload' enctype='multipart/form-data' id='uploadForm'>
            <label for='image'>בחר תמונה:</label>
            <input type='file' id='image' name='image' accept='image/*' required onchange='previewImage(event)'>
            <div class='upload-preview' id='previewContainer'></div>
            <button type='submit'>העלה ונתח</button>
        </form>
        <script>
        function previewImage(event) {
            const file = event.target.files[0];
            if (!file) return;
            const reader = new FileReader();
            reader.onload = function(e) {
                const preview = document.getElementById('previewContainer');
                preview.innerHTML = `<img src="${e.target.result}" alt="preview" class="preview">`;
            };
            reader.readAsDataURL(file);
        }
        </script>
        """
        page = self._html_page('העלאת תמונה', body)
        self._send_response(page.encode('utf-8'))

    def _handle_upload(self):
        # Handle file upload; extract file from multipart form
        content_type = self.headers.get('Content-Type', '')
        if 'multipart/form-data' not in content_type:
            self._send_response(b'Unsupported Media Type', 415)
            return
        length = int(self.headers.get('Content-Length', 0))
        data = self.rfile.read(length)
        # parse multipart
        boundary = content_type.split('boundary=')[-1].encode()
        parts = data.split(b'--' + boundary)
        file_data = None
        for part in parts:
            if b'Content-Disposition' in part and b'name="image"' in part:
                # skip headers to get to file content
                headers_end = part.find(b'\r\n\r\n')
                if headers_end != -1:
                    file_data = part[headers_end + 4:-2]  # skip final \r\n
                    break
        if not file_data:
            self._send_response(b'No file uploaded', 400)
            return
        # Analyze image and update daily log
        macros = analyze_image(file_data)
        # Save uploaded file for preview
        from datetime import datetime
        # Use timestamp to generate unique filename
        ts = datetime.now().strftime('%Y%m%d%H%M%S%f')
        # Default extension is jpg
        filename = f"upload_{ts}.jpg"
        save_path = os.path.join(UPLOAD_DIR, filename)
        try:
            with open(save_path, 'wb') as f_out:
                f_out.write(file_data)
        except Exception:
            filename = None
        conn = get_connection()
        cur = conn.cursor()
        start_day = get_start_of_day().date().isoformat()
        cur.execute("SELECT id, calories, protein, fat, carbs FROM logs WHERE user_id=? AND date=?", (1, start_day))
        row = cur.fetchone()
        if row:
            log_id, cal, prot, fat, carb = row
            cal += macros['calories']
            prot += macros['protein']
            fat += macros['fat']
            carb += macros['carbs']
            cur.execute(
                "UPDATE logs SET calories=?, protein=?, fat=?, carbs=? WHERE id=?",
                (cal, prot, fat, carb, log_id)
            )
        else:
            cur.execute(
                "INSERT INTO logs (user_id, date, calories, protein, fat, carbs) VALUES (?, ?, ?, ?, ?, ?)",
                (1, start_day, macros['calories'], macros['protein'], macros['fat'], macros['carbs'])
            )
        conn.commit()
        conn.close()
        # Respond with result summary
        response = {
            'category': macros.get('category'),
            'added': {k: macros[k] for k in ['calories', 'protein', 'fat', 'carbs']}
        }
        # Provide HTML feedback with image preview
        img_html = f"<img src='/uploads/{filename}' alt='preview' class='preview'>" if filename else ""
        body = f"""
        <h1>התמונה נותחה</h1>
        {img_html}
        <p class='intro'>קטגוריית הערכה: <strong>{response['category']}</strong></p>
        <p class='intro'>הערכים שנוספו:</p>
        <ul class='summary-list'>
            <li><span>קלוריות:</span> {macros['calories']}</li>
            <li><span>חלבון:</span> {macros['protein']} גרם</li>
            <li><span>שומן:</span> {macros['fat']} גרם</li>
            <li><span>פחמימות:</span> {macros['carbs']} גרם</li>
        </ul>
        <div class='card-buttons'>
            <a href='/upload'>העלאה נוספת</a>
            <a href='/daily'>עבור לסיכום יומי</a>
        </div>
        """
        page = self._html_page('תוצאה', body)
        self._send_response(page.encode('utf-8'))

    def _serve_add_food_form(self):
        """Serve form to manually add a food item with nutritional values."""
        body = """
        <h1>הוספת מאכל ידנית</h1>
        <p class='intro'>הכנס שם מאכל ואת הערכים התזונתיים שלו כדי להוסיף אותם לתיעוד היומי שלך.</p>
        <form method='post' action='/add_food'>
            <label for='food_name'>שם מאכל:</label>
            <input type='text' id='food_name' name='food_name' placeholder='למשל: סלט קצוץ' required>
            <label for='calories'>קלוריות:</label>
            <input type='number' id='calories' name='calories' step='any' required>
            <label for='protein'>חלבון (גרם):</label>
            <input type='number' id='protein' name='protein' step='any' required>
            <label for='fat'>שומן (גרם):</label>
            <input type='number' id='fat' name='fat' step='any' required>
            <label for='carbs'>פחמימות (גרם):</label>
            <input type='number' id='carbs' name='carbs' step='any' required>
            <button type='submit'>הוסף מאכל</button>
        </form>
        """
        page = self._html_page('הוספת מאכל', body)
        self._send_response(page.encode('utf-8'))

    def _handle_add_food(self):
        """Process manual food entry and update daily log."""
        length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(length)
        parsed = parse_qs(post_data.decode('utf-8'))
        try:
            # ignore name; we could store food_name in future
            calories = float(parsed.get('calories', ['0'])[0])
            protein = float(parsed.get('protein', ['0'])[0])
            fat = float(parsed.get('fat', ['0'])[0])
            carbs = float(parsed.get('carbs', ['0'])[0])
        except Exception:
            self._send_response(b'Invalid input', 400)
            return
        # Update daily log
        conn = get_connection()
        cur = conn.cursor()
        start_day = get_start_of_day().date().isoformat()
        cur.execute("SELECT id, calories, protein, fat, carbs FROM logs WHERE user_id=? AND date=?", (1, start_day))
        row = cur.fetchone()
        if row:
            log_id, cal, prot, fat_val, carb = row
            cal += calories
            prot += protein
            fat_val += fat
            carb += carbs
            cur.execute(
                "UPDATE logs SET calories=?, protein=?, fat=?, carbs=? WHERE id=?",
                (cal, prot, fat_val, carb, log_id)
            )
        else:
            cur.execute(
                "INSERT INTO logs (user_id, date, calories, protein, fat, carbs) VALUES (?, ?, ?, ?, ?, ?)",
                (1, start_day, calories, protein, fat, carbs)
            )
        conn.commit()
        conn.close()
        # Redirect to daily summary
        self.send_response(303)
        self.send_header('Location', '/daily')
        self.end_headers()

    def _serve_daily_summary(self):
        # Compute start day and summary
        start_day_date = get_start_of_day().date()
        start_day = start_day_date.isoformat()
        conn = get_connection()
        cur = conn.cursor()
        # Get daily totals
        cur.execute("SELECT calories, protein, fat, carbs FROM logs WHERE user_id=? AND date=?", (1, start_day))
        row = cur.fetchone()
        totals = {'calories': 0, 'protein': 0, 'fat': 0, 'carbs': 0}
        if row:
            totals = {'calories': row[0], 'protein': row[1], 'fat': row[2], 'carbs': row[3]}
        # Get daily goals
        cur.execute("SELECT daily_calories, daily_protein, daily_fat, daily_carbs FROM goals WHERE user_id=? ORDER BY id DESC LIMIT 1", (1,))
        row = cur.fetchone()
        goals = {'calories': None, 'protein': None, 'fat': None, 'carbs': None}
        if row:
            goals = {'calories': row[0], 'protein': row[1], 'fat': row[2], 'carbs': row[3]}
        conn.close()
        # Generate progress bars
        bars_html = []
        macro_labels = {'calories': 'קלוריות', 'protein': 'חלבון', 'fat': 'שומן', 'carbs': 'פחמימות'}
        macro_colors = {'calories': '#fd7e14', 'protein': '#007bff', 'fat': '#dc3545', 'carbs': '#20c997'}
        for key in ['calories', 'protein', 'fat', 'carbs']:
            total = totals[key]
            goal = goals.get(key)
            # Avoid division by zero
            if goal and goal > 0:
                percent = min(100, (total / goal) * 100)
            else:
                percent = 0
            # Format numbers nicely (no trailing .0 if integer)
            def fmt(x):
                return int(x) if x == int(x) else round(x, 2)
            goal_text = fmt(goal) if goal else '—'
            total_text = fmt(total)
            percent_text = fmt(percent)
            bar = f"""
            <div class='macro-bar'>
                <div class='macro-bar-label'>{macro_labels[key]}</div>
                <div class='macro-bar-track'>
                    <div class='macro-bar-fill' style='width: {percent}%; background: {macro_colors[key]};'></div>
                </div>
                <div class='macro-bar-info'>{total_text} / {goal_text} ({percent_text}%)</div>
            </div>
            """
            bars_html.append(bar)
        # Determine day-of-week
        heb_day = hebrew_day_of_week(start_day_date)
        date_str = start_day_date.strftime('%d/%m/%y')
        body = f"""
        <h1>סיכום יומי</h1>
        <p class='intro'>יום {heb_day} – {date_str}</p>
        <div>
            {''.join(bars_html)}
        </div>
        <div class='card-buttons'>
            <a href='/upload'>העלה מנה נוספת</a>
            <a href='/add_food'>הוסף מאכל ידנית</a>
            <a href='/weekly_summary'>עבור לסיכום שבועי</a>
        </div>
        """
        page = self._html_page('סיכום יומי', body)
        self._send_response(page.encode('utf-8'))

    def _serve_weekly_summary(self):
        """
        Serve a detailed weekly summary showing each day of the current week with progress bars.

        The summary begins on the week's first day (Monday) and includes today. For each day,
        the user's totals are compared against the latest daily goals, and progress bars
        illustrate consumption. Hebrew letters denote the day of the week.
        """
        # Determine the start of the week (Monday) and the current start of day (5 AM boundary)
        today = datetime.now().date()
        start_of_week = today - timedelta(days=today.weekday())
        # Fetch latest daily goals for comparison
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT daily_calories, daily_protein, daily_fat, daily_carbs, weekly_calories, weekly_protein, weekly_fat, weekly_carbs FROM goals WHERE user_id=? ORDER BY id DESC LIMIT 1", (1,))
        row = cur.fetchone()
        if row:
            daily_goals = {'calories': row[0], 'protein': row[1], 'fat': row[2], 'carbs': row[3]}
            weekly_goals = {'calories': row[4], 'protein': row[5], 'fat': row[6], 'carbs': row[7]}
        else:
            # Default goals if none exist
            daily_goals = {'calories': 2000, 'protein': 150, 'fat': 70, 'carbs': 250}
            weekly_goals = {'calories': daily_goals['calories'] * 7, 'protein': daily_goals['protein'] * 7, 'fat': daily_goals['fat'] * 7, 'carbs': daily_goals['carbs'] * 7}
        # Prepare weekly totals for final comparison
        weekly_totals = {'calories': 0, 'protein': 0, 'fat': 0, 'carbs': 0}
        # Generate per-day cards
        cards_html = []
        current_date = start_of_week
        while current_date <= today:
            date_iso = current_date.isoformat()
            # Sum macros for this date
            cur.execute("SELECT calories, protein, fat, carbs FROM logs WHERE user_id=? AND date=?", (1, date_iso))
            row = cur.fetchone()
            totals = {'calories': 0, 'protein': 0, 'fat': 0, 'carbs': 0}
            if row:
                totals = {'calories': row[0] or 0, 'protein': row[1] or 0, 'fat': row[2] or 0, 'carbs': row[3] or 0}
            # Accumulate weekly totals
            for k in weekly_totals:
                weekly_totals[k] += totals[k]
            # Build progress bars for this day
            macro_labels = {'calories': 'קלוריות', 'protein': 'חלבון', 'fat': 'שומן', 'carbs': 'פחמימות'}
            macro_colors = {'calories': '#fd7e14', 'protein': '#007bff', 'fat': '#dc3545', 'carbs': '#20c997'}
            bars = []
            for key in ['calories', 'protein', 'fat', 'carbs']:
                total = totals[key]
                goal = daily_goals.get(key)
                if goal and goal > 0:
                    percent = min(100, (total / goal) * 100)
                else:
                    percent = 0
                # Format numbers
                def fmt(x):
                    try:
                        return int(x) if float(x).is_integer() else round(x, 2)
                    except Exception:
                        return x
                goal_text = fmt(goal) if goal else '—'
                total_text = fmt(total)
                percent_text = fmt(percent)
                bars.append(f"""
                <div class='macro-bar'>
                    <div class='macro-bar-label'>{macro_labels[key]}</div>
                    <div class='macro-bar-track'>
                        <div class='macro-bar-fill' style='width: {percent}%; background: {macro_colors[key]};'></div>
                    </div>
                    <div class='macro-bar-info'>{total_text} / {goal_text} ({percent_text}%)</div>
                </div>
                """)
            # Day header with Hebrew letter and date
            heb_day = hebrew_day_of_week(current_date)
            date_str = current_date.strftime('%d/%m/%y')
            card = f"""
            <div class='day-card'>
                <h2>יום {heb_day} – {date_str}</h2>
                {''.join(bars)}
            </div>
            """
            cards_html.append(card)
            current_date += timedelta(days=1)
        # After building per-day cards, build overall weekly comparison vs weekly goals
        def format_week_status(total, goal, label):
            # Provide feedback whether the weekly goal has been met or not
            if goal is None:
                return f"<li>{label}: {total}</li>"
            diff = goal - total
            if diff >= 0:
                return f"<li>{label}: {total} / {goal} (נותרו {diff})</li>"
            else:
                return f"<li>{label}: {total} / {goal} (חרגתם ב {abs(diff)})</li>"
        week_status_items = [
            format_week_status(weekly_totals['calories'], weekly_goals['calories'], 'קלוריות'),
            format_week_status(weekly_totals['protein'], weekly_goals['protein'], 'חלבון'),
            format_week_status(weekly_totals['fat'], weekly_goals['fat'], 'שומן'),
            format_week_status(weekly_totals['carbs'], weekly_goals['carbs'], 'פחמימות'),
        ]
        conn.close()
        body = f"""
        <h1>סיכום שבועי</h1>
        <p class='intro'>להלן פירוט צריכת המאקרו‑נוטריינטים בכל יום בשבוע הנוכחי:</p>
        {''.join(cards_html)}
        <h2 style='text-align:right;'>סיכום שבועי לעומת היעדים:</h2>
        <ul class='summary-list'>
            {''.join(week_status_items)}
        </ul>
        <div class='card-buttons'>
            <a href='/upload'>העלה מנה נוספת</a>
            <a href='/add_food'>הוסף מאכל ידנית</a>
            <a href='/daily'>עבור לסיכום יומי</a>
        </div>
        """
        page = self._html_page('סיכום שבועי', body)
        self._send_response(page.encode('utf-8'))

    def _serve_upload_file(self):
        """Serve files from the uploads directory."""
        # Prevent directory traversal attacks
        file_path = self.path[len('/uploads/'):]
        # Only allow alphanumeric, underscore, dash and dot characters
        import re
        if not re.match(r'^[A-Za-z0-9_.-]+$', file_path):
            self._send_response(b'Not Found', 404)
            return
        fs_path = os.path.join(UPLOAD_DIR, file_path)
        if not os.path.isfile(fs_path):
            self._send_response(b'Not Found', 404)
            return
        # Determine content type by extension
        ext = os.path.splitext(fs_path)[1].lower()
        if ext in ('.jpg', '.jpeg'):
            content_type = 'image/jpeg'
        elif ext == '.png':
            content_type = 'image/png'
        else:
            content_type = 'application/octet-stream'
        with open(fs_path, 'rb') as f:
            data = f.read()
        self._send_response(data, 200, content_type)


def run_server(port=None):
    init_db()
    httpd = server.HTTPServer(('', port), NutritionHandler)
    print(f"Server running on http://localhost:{port}")
    httpd.serve_forever()


if __name__ == '__main__':
    run_server()
