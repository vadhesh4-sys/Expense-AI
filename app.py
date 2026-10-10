from flask import Flask, render_template, request, jsonify, redirect, url_for
from flask_login import (
    LoginManager,
    UserMixin,
    login_user,
    login_required,
    logout_user,
    current_user
)
import sqlite3
import re
import csv
from io import StringIO
from datetime import datetime, date, timedelta
from werkzeug.security import generate_password_hash, check_password_hash


# =========================================================
# APP CONFIG
# =========================================================

app = Flask(__name__)

app.secret_key = "expense_ai_secret_key_2026"

DATABASE = "expenses.db"


# =========================================================
# LOGIN MANAGER
# =========================================================

login_manager = LoginManager()

login_manager.init_app(app)

login_manager.login_view = "login"


# =========================================================
# USER CLASS
# =========================================================

class User(UserMixin):

    def __init__(self, user_id, username, password):

        self.id = user_id
        self.username = username
        self.password = password


# =========================================================
# DATABASE CONNECTION
# =========================================================

def get_connection():

    conn = sqlite3.connect(DATABASE)

    conn.row_factory = sqlite3.Row

    return conn


# =========================================================
# CREATE DATABASE
# =========================================================

def create_database():

    conn = get_connection()

    cursor = conn.cursor()

    # USERS
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )
    """)

    # EXPENSES
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            amount REAL NOT NULL,
            category TEXT NOT NULL,
            description TEXT,
            expense_date TEXT
        )
    """)

    # Check expense columns
    cursor.execute("PRAGMA table_info(expenses)")

    columns = [
        row["name"]
        for row in cursor.fetchall()
    ]

    # Add user_id to old database
    if "user_id" not in columns:

        cursor.execute("""
            ALTER TABLE expenses
            ADD COLUMN user_id INTEGER
        """)

    # BUDGETS
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS budgets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE NOT NULL,
            monthly_budget REAL DEFAULT 0
        )
    """)

    # Create default user for old expenses
    cursor.execute(
        "SELECT id FROM users WHERE username = ?",
        ("default_user",)
    )

    default_user = cursor.fetchone()

    if not default_user:

        password_hash = generate_password_hash(
            "default123"
        )

        cursor.execute("""
            INSERT INTO users
            (username, password)
            VALUES (?, ?)
        """, (
            "default_user",
            password_hash
        ))

        default_user_id = cursor.lastrowid

    else:

        default_user_id = default_user["id"]

    # Assign old expenses to default user
    cursor.execute("""
        UPDATE expenses
        SET user_id = ?
        WHERE user_id IS NULL
    """, (
        default_user_id,
    ))

    conn.commit()

    conn.close()


# =========================================================
# LOGIN LOADER
# =========================================================

@login_manager.user_loader
def load_user(user_id):

    conn = get_connection()

    cursor = conn.cursor()

    cursor.execute("""
        SELECT *
        FROM users
        WHERE id = ?
    """, (
        user_id,
    ))

    user = cursor.fetchone()

    conn.close()

    if user:

        return User(
            user["id"],
            user["username"],
            user["password"]
        )

    return None


# =========================================================
# AMOUNT EXTRACTION
# =========================================================

def extract_amount(text):

    text = text.lower()

    # Remove numbers that clearly belong to a time period
    # such as "7 days", "6 months", etc.
    cleaned_text = re.sub(
        r"\b\d+(?:\.\d+)?\s*(?:days?|weeks?|months?|day|week|month|naal|naatkal)\b",
        "",
        text,
        flags=re.IGNORECASE
    )

    patterns = [
        r"₹\s*(\d+(?:\.\d+)?)",
        r"rs\.?\s*(\d+(?:\.\d+)?)",
        r"rupees?\s*(\d+(?:\.\d+)?)",
        r"\b(\d+(?:\.\d+)?)\s*(?:rs|₹)\b",
        r"\b(\d+(?:\.\d+)?)\b"
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            cleaned_text,
            flags=re.IGNORECASE
        )

        if match:

            try:

                amount = float(match.group(1))

                if amount > 0:
                    return amount

            except ValueError:

                pass

    return None

# =========================================================
# CATEGORY DETECTION
# =========================================================

def detect_category(text):

    text = text.lower()

    categories = {

        "Food": [
            "food", "lunch", "dinner", "breakfast", "snack", "snacks",
            "restaurant", "hotel", "saapadu", "sapadu", "sappadu",
            "saptadhu", "saptathu", "biryani", "tea", "coffee", "juice",
            "tiffin", "mess", "swiggy", "zomato", "eat", "eating", "meal"
        ],

        "Travel": [
            "travel", "bus", "train", "auto", "cab", "taxi", "petrol",
            "fuel", "metro", "uber", "ola", "rapido", "ticket", "transport"
        ],

        "Shopping": [
            "shopping", "shop", "dress", "clothes", "shirt", "pant",
            "shoes", "shoe", "mall", "purchase", "bought", "buy",
            "amazon", "flipkart", "ajio", "myntra", "watch", "bag"
        ],

        "Entertainment": [
            "movie", "movies", "cinema", "game", "games", "entertainment",
            "netflix", "prime", "hotstar", "spotify", "concert", "outing"
        ],

        "Bills": [
            "bill", "bills", "electricity", "current", "internet", "wifi",
            "recharge", "phone", "mobile", "data", "water", "eb", "rent"
        ],

        "Education": [
            "college", "fees", "fee", "book", "books", "course",
            "education", "exam", "semester", "tuition", "study", "class"
        ],

        "Health": [
            "medical", "medicine", "hospital", "doctor", "health", "tablet",
            "pharmacy", "clinic", "treatment"
        ]
    }

    # Token-based matching avoids accidental matches inside unrelated words.
    tokens = set(re.findall(r"[a-z0-9]+", text))

    for category, keywords in categories.items():

        for keyword in keywords:

            keyword_tokens = re.findall(r"[a-z0-9]+", keyword.lower())

            if len(keyword_tokens) == 1:

                if keyword_tokens[0] in tokens:
                    return category

            elif keyword.lower() in text:

                return category

    return "Other"

# =========================================================
# DATE DETECTION
# =========================================================

def detect_expense_date(text):

    text = text.lower()

    today = date.today()

    yesterday_words = [
        "yesterday",
        "nethu",
        "netru",
        "neththu"
    ]

    if any(word in text for word in yesterday_words):

        return (
            today - timedelta(days=1)
        ).isoformat()

    return today.isoformat()

# =========================================================
# PERIOD DETECTION
# =========================================================

def detect_period(text):

    text = text.lower()

    if any(word in text for word in [
        "yesterday", "nethu", "netru", "neththu"
    ]):
        return "yesterday"

    if any(phrase in text for phrase in [
        "last 7 days", "past 7 days", "last seven days",
        "7 days", "7 day", "seven days", "7 naal", "7 naatkal",
        "last week", "previous week", "previous 7 days",
        "pona week", "pona vaaram", "last vaaram"
    ]):
        return "last7days"

    if any(phrase in text for phrase in [
        "this week", "current week", "this vaaram", "this week",
        "intha week", "indha week", "intha vaaram", "indha vaaram"
    ]):
        return "week"

    if any(phrase in text for phrase in [
        "last month", "previous month", "last maasam",
        "previous maasam", "pona month", "pona maasam"
    ]):
        return "lastmonth"

    if any(phrase in text for phrase in [
        "this month", "current month", "this maasam",
        "intha month", "indha month", "intha maasam", "indha maasam"
    ]):
        return "month"

    if any(phrase in text for phrase in [
        "today", "innaiku", "iniku", "indru", "today's"
    ]):
        return "today"

    return "all"

# =========================================================
# NORMALIZE TEXT
# =========================================================

def normalize_text(text):

    return text.lower().strip()


# =========================================================
# SAVE EXPENSE
# =========================================================

def save_expense(
    user_id,
    amount,
    category,
    description,
    expense_date=None
):

    if expense_date is None:

        expense_date = date.today().isoformat()

    conn = get_connection()

    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO expenses
        (
            amount,
            category,
            description,
            expense_date,
            user_id
        )
        VALUES (?, ?, ?, ?, ?)
    """, (
        amount,
        category,
        description,
        expense_date,
        user_id
    ))

    conn.commit()

    expense_id = cursor.lastrowid

    conn.close()

    return expense_id


# =========================================================
# BUDGET FUNCTIONS
# =========================================================

def get_monthly_budget(user_id):

    conn = get_connection()

    cursor = conn.cursor()

    cursor.execute("""
        SELECT monthly_budget
        FROM budgets
        WHERE user_id = ?
    """, (
        user_id,
    ))

    row = cursor.fetchone()

    conn.close()

    if row:

        return float(
            row["monthly_budget"]
        )

    return 0.0


def set_monthly_budget(
    user_id,
    amount
):

    conn = get_connection()

    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO budgets
        (
            user_id,
            monthly_budget
        )
        VALUES (?, ?)

        ON CONFLICT(user_id)
        DO UPDATE SET
            monthly_budget = excluded.monthly_budget
    """, (
        user_id,
        amount
    ))

    conn.commit()

    conn.close()


# =========================================================
# CURRENT MONTH TOTAL
# =========================================================

def get_current_month_expense(user_id):

    today = date.today()

    first_day = today.replace(
        day=1
    ).isoformat()

    conn = get_connection()

    cursor = conn.cursor()

    cursor.execute("""
        SELECT COALESCE(SUM(amount), 0)
        FROM expenses
        WHERE user_id = ?
        AND expense_date >= ?
    """, (
        user_id,
        first_day
    ))

    result = cursor.fetchone()[0]

    conn.close()

    return float(result)


# =========================================================
# PERIOD TOTAL
# =========================================================

def get_period_total(
    user_id,
    period,
    category=None
):

    today = date.today()

    conn = get_connection()

    cursor = conn.cursor()

    query = """
        SELECT COALESCE(SUM(amount), 0)
        FROM expenses
        WHERE user_id = ?
    """

    params = [user_id]

    if period == "today":

        query += """
            AND expense_date = ?
        """

        params.append(
            today.isoformat()
        )

    elif period == "yesterday":

        yesterday = (
            today - timedelta(days=1)
        ).isoformat()

        query += """
            AND expense_date = ?
        """

        params.append(
            yesterday
        )

    elif period == "last7days":

        start_date = (
            today - timedelta(days=6)
        ).isoformat()

        query += """
            AND expense_date >= ?
            AND expense_date <= ?
        """

        params.extend([
            start_date,
            today.isoformat()
        ])

    elif period == "week":

        start_date = (
            today - timedelta(
                days=today.weekday()
            )
        ).isoformat()

        query += """
            AND expense_date >= ?
            AND expense_date <= ?
        """

        params.extend([
            start_date,
            today.isoformat()
        ])

    elif period == "month":

        start_date = today.replace(
            day=1
        ).isoformat()

        query += """
            AND expense_date >= ?
        """

        params.append(
            start_date
        )

    elif period == "lastmonth":

        first_day_current = today.replace(
            day=1
        )

        last_day_previous = (
            first_day_current
            - timedelta(days=1)
        )

        first_day_previous = (
            last_day_previous.replace(day=1)
        )

        query += """
            AND expense_date >= ?
            AND expense_date <= ?
        """

        params.extend([
            first_day_previous.isoformat(),
            last_day_previous.isoformat()
        ])

    if category:

        query += """
            AND category = ?
        """

        params.append(
            category
        )

    cursor.execute(
        query,
        params
    )

    result = cursor.fetchone()[0]

    conn.close()

    return float(result or 0)


# =========================================================
# ALL TOTAL
# =========================================================

def get_all_total(user_id):

    conn = get_connection()

    cursor = conn.cursor()

    cursor.execute("""
        SELECT COALESCE(SUM(amount), 0)
        FROM expenses
        WHERE user_id = ?
    """, (
        user_id,
    ))

    result = cursor.fetchone()[0]

    conn.close()

    return float(result or 0)


# =========================================================
# CATEGORY TOTALS
# =========================================================

def get_category_totals(
    user_id,
    period="month"
):

    conn = get_connection()

    cursor = conn.cursor()

    today = date.today()

    query = """
        SELECT
            category,
            SUM(amount) AS total
        FROM expenses
        WHERE user_id = ?
    """

    params = [user_id]

    if period == "month":

        first_day = today.replace(
            day=1
        ).isoformat()

        query += """
            AND expense_date >= ?
        """

        params.append(
            first_day
        )

    elif period == "week":

        start_date = (
            today - timedelta(
                days=today.weekday()
            )
        ).isoformat()

        query += """
            AND expense_date >= ?
        """

        params.append(
            start_date
        )

    query += """
        GROUP BY category
        ORDER BY total DESC
    """

    cursor.execute(
        query,
        params
    )

    rows = cursor.fetchall()

    conn.close()

    return [
        {
            "category": row["category"],
            "total": float(row["total"])
        }
        for row in rows
    ]


# =========================================================
# ADVANCED SPENDING INSIGHTS
# =========================================================

def get_advanced_insights(user_id):

    today = date.today()

    # -----------------------------------------
    # CURRENT MONTH
    # -----------------------------------------

    current_total = get_period_total(
        user_id,
        "month"
    )

    # -----------------------------------------
    # PREVIOUS MONTH
    # -----------------------------------------

    previous_total = get_period_total(
        user_id,
        "lastmonth"
    )

    # -----------------------------------------
    # CATEGORY DATA
    # -----------------------------------------

    categories = get_category_totals(
        user_id,
        "month"
    )

    highest_category = None
    highest_category_amount = 0

    lowest_category = None
    lowest_category_amount = 0

    if categories:

        highest_category = categories[0]["category"]

        highest_category_amount = categories[0]["total"]

        lowest_item = categories[-1]

        lowest_category = lowest_item["category"]

        lowest_category_amount = lowest_item["total"]

    # -----------------------------------------
    # AVERAGE DAILY SPENDING
    # -----------------------------------------

    elapsed_days = today.day

    if elapsed_days > 0:

        average_daily = (
            current_total / elapsed_days
        )

    else:

        average_daily = 0

    # -----------------------------------------
    # HIGHEST TRANSACTION
    # -----------------------------------------

    conn = get_connection()

    cursor = conn.cursor()

    first_day = today.replace(
        day=1
    ).isoformat()

    cursor.execute("""
        SELECT
            amount,
            category,
            description,
            expense_date
        FROM expenses
        WHERE user_id = ?
        AND expense_date >= ?
        ORDER BY amount DESC
        LIMIT 1
    """, (
        user_id,
        first_day
    ))

    highest_transaction = cursor.fetchone()

    conn.close()

    highest_transaction_data = None

    if highest_transaction:

        highest_transaction_data = {
            "amount": float(
                highest_transaction["amount"]
            ),
            "category": highest_transaction["category"],
            "description": highest_transaction["description"],
            "date": highest_transaction["expense_date"]
        }

    # -----------------------------------------
    # BUDGET
    # -----------------------------------------

    budget = get_monthly_budget(
        user_id
    )

    budget_percentage = 0

    if budget > 0:

        budget_percentage = (
            current_total / budget
        ) * 100

    # -----------------------------------------
    # MONTH COMPARISON
    # -----------------------------------------

    difference = (
        current_total
        - previous_total
    )

    if previous_total > 0:

        percentage_change = (
            difference
            / previous_total
        ) * 100

    else:

        percentage_change = 0

    # -----------------------------------------
    # WARNING
    # -----------------------------------------

    warning = None

    if budget > 0:

        if budget_percentage >= 100:

            warning = (
                "⚠️ Your monthly budget "
                "has been exceeded."
            )

        elif budget_percentage >= 80:

            warning = (
                "⚠️ You have used more "
                "than 80% of your monthly budget."
            )

    # -----------------------------------------
    # SUGGESTION
    # -----------------------------------------

    suggestion = None

    if highest_category:

        suggestion = (
            f"💡 {highest_category} is your "
            f"highest spending category this month. "
            f"You can review your {highest_category.lower()} "
            f"expenses to reduce spending."
        )

    return {

        "current_total": round(
            current_total,
            2
        ),

        "previous_total": round(
            previous_total,
            2
        ),

        "highest_category": highest_category,

        "highest_category_amount": round(
            highest_category_amount,
            2
        ),

        "lowest_category": lowest_category,

        "lowest_category_amount": round(
            lowest_category_amount,
            2
        ),

        "average_daily": round(
            average_daily,
            2
        ),

        "highest_transaction":
            highest_transaction_data,

        "budget": round(
            budget,
            2
        ),

        "budget_percentage": round(
            budget_percentage,
            2
        ),

        "difference": round(
            difference,
            2
        ),

        "percentage_change": round(
            percentage_change,
            2
        ),

        "warning": warning,

        "suggestion": suggestion,

        "categories": categories
    }


# =========================================================
# FORMAT ADVANCED INSIGHTS FOR CHAT
# =========================================================

def format_advanced_insights(
    user_id
):

    data = get_advanced_insights(
        user_id
    )

    response = """
    📊 <b>Your Spending Analysis</b>
    <br><br>
    """

    response += (
        f"💰 <b>This Month:</b> "
        f"₹{data['current_total']:.2f}"
    )

    response += "<br>"

    if data["highest_category"]:

        response += (
            f"🏆 <b>Highest Category:</b> "
            f"{data['highest_category']} "
            f"— ₹{data['highest_category_amount']:.2f}"
        )

        response += "<br>"

        response += (
            f"📉 <b>Lowest Category:</b> "
            f"{data['lowest_category']} "
            f"— ₹{data['lowest_category_amount']:.2f}"
        )

        response += "<br>"

    response += (
        f"📊 <b>Average Daily Spending:</b> "
        f"₹{data['average_daily']:.2f}"
    )

    response += "<br>"

    transaction = data[
        "highest_transaction"
    ]

    if transaction:

        response += (
            f"💸 <b>Highest Transaction:</b> "
            f"₹{transaction['amount']:.2f} "
            f"({transaction['category']})"
        )

        response += "<br>"

    if data["budget"] > 0:

        response += (
            f"💳 <b>Budget:</b> "
            f"₹{data['budget']:.2f}"
        )

        response += "<br>"

        response += (
            f"📈 <b>Budget Used:</b> "
            f"{data['budget_percentage']:.2f}%"
        )

        response += "<br>"

    else:

        response += (
            "💳 <b>Budget:</b> "
            "Not set yet."
        )

        response += "<br>"

    # Month comparison
    if data["previous_total"] > 0:

        if data["difference"] > 0:

            response += (
                f"📅 <b>Compared with last month:</b> "
                f"₹{data['difference']:.2f} more spent "
                f"({data['percentage_change']:.2f}%)"
            )

        elif data["difference"] < 0:

            response += (
                f"📅 <b>Compared with last month:</b> "
                f"₹{abs(data['difference']):.2f} less spent "
                f"({abs(data['percentage_change']):.2f}%)"
            )

        else:

            response += (
                "📅 <b>Compared with last month:</b> "
                "Almost the same spending."
            )

        response += "<br>"

    # Warning
    if data["warning"]:

        response += (
            "<br>"
            f"{data['warning']}"
        )

        response += "<br>"

    # Suggestion
    if data["suggestion"]:

        response += (
            "<br>"
            f"{data['suggestion']}"
        )

    return response


# =========================================================
# WHAT-IF ANALYSIS
# =========================================================

def process_what_if(
    text,
    user_id
):

    text_lower = text.lower()

    amount = extract_amount(
        text
    )

    # -----------------------------------------
    # MONTHLY SAVINGS
    # Example:
    # save 500 every month for 6 months
    # -----------------------------------------

    if (
        "save" in text_lower
        or "savings" in text_lower
    ):

        if amount is None:

            return (
                "💡 Please mention the amount. "
                "Example: <b>Save 500 every month "
                "for 6 months</b>"
            )

        month_match = re.search(
            r"(\d+)\s*months?",
            text_lower
        )

        if month_match:

            months = int(
                month_match.group(1)
            )

        else:

            months = 1

        total_savings = (
            amount * months
        )

        return (
            f"💰 <b>Savings Analysis</b>"
            f"<br><br>"
            f"Monthly saving: "
            f"<b>₹{amount:.2f}</b>"
            f"<br>"
            f"Duration: "
            f"<b>{months} month(s)</b>"
            f"<br><br>"
            f"🎯 Total possible savings: "
            f"<b>₹{total_savings:.2f}</b>"
        )

    # -----------------------------------------
    # CATEGORY REDUCTION
    # -----------------------------------------

    category = detect_category(
        text
    )

    reduction = amount

    if reduction is None:

        return (
            "💡 Please mention how much "
            "you want to reduce.<br><br>"
            "Example:<br>"
            "<b>If I reduce shopping by 1000?</b>"
        )

    category_total = get_period_total(
        user_id,
        "month",
        category
    )

    current_total = get_period_total(
        user_id,
        "month"
    )

    if category_total <= 0:

        return (
            f"📊 I couldn't find any "
            f"<b>{category}</b> spending "
            f"this month."
        )

    actual_reduction = min(
        reduction,
        category_total
    )

    new_total = (
        current_total
        - actual_reduction
    )

    remaining_category = (
        category_total
        - actual_reduction
    )

    response = (
        f"🔮 <b>What-If Analysis</b>"
        f"<br><br>"
        f"Current total: "
        f"<b>₹{current_total:.2f}</b>"
        f"<br>"
        f"{category} spending: "
        f"<b>₹{category_total:.2f}</b>"
        f"<br>"
        f"Planned reduction: "
        f"<b>₹{reduction:.2f}</b>"
        f"<br><br>"
        f"📉 Estimated new total: "
        f"<b>₹{new_total:.2f}</b>"
        f"<br>"
        f"Remaining {category} spending: "
        f"<b>₹{remaining_category:.2f}</b>"
    )

    if reduction > category_total:

        response += (
            "<br><br>"
            "ℹ️ The requested reduction is "
            "higher than your current category "
            "spending, so I capped the calculation "
            "at the available amount."
        )

    return response


# =========================================================
# INTENT DETECTION
# =========================================================

def detect_intent(text):

    text_lower = text.lower()

    # Advanced insights
    advanced_words = [
        "advanced insights", "detailed insights", "analyze my spending",
        "analyse my spending", "spending analysis", "spending pattern",
        "average daily spending", "average spending", "highest transaction",
        "highest expense", "biggest expense", "budget percentage",
        "how am i spending"
    ]

    if any(word in text_lower for word in advanced_words):
        return "advanced_insights"

    # What-if / savings
    what_if_words = [
        "what if", "if i reduce", "reduce", "save every month",
        "save monthly", "savings"
    ]

    if any(word in text_lower for word in what_if_words):
        return "what_if"

    # Set budget
    if (
        "set my budget" in text_lower
        or "set budget" in text_lower
        or "budget to" in text_lower
    ):
        return "set_budget"

    # Budget query
    if "budget" in text_lower:
        return "budget"

    # Basic insights
    if any(word in text_lower for word in [
        "where am i spending more", "highest category",
        "spending more", "category wise", "category breakdown"
    ]):
        return "insights"

    # Help should be checked before generic word matching.
    if (
        "help" in text_lower
        or "what can you do" in text_lower
    ):
        return "help"

    amount = extract_amount(text)

    # Expense action phrases.
    expense_words = [
        "spent", "spend", "bought", "purchase", "panninen",
        "paninen", "pannitu", "selavu", "selavu panninen",
        "expense added"
    ]

    if amount is not None and any(
        word in text_lower for word in expense_words
    ):
        return "add_expense"

    # Spending queries.
    query_words = [
        "how much", "how much did", "total", "spend", "spent",
        "expense", "expenses", "evlo", "selavu", "how much i spent"
    ]

    if any(word in text_lower for word in query_words):
        return "spending_query"

    # A message containing an amount and a category can be treated as an expense.
    if amount is not None:
        category = detect_category(text)

        if category != "Other":
            return "add_expense"

    return "unknown"

# =========================================================
# PROCESS CHAT MESSAGE
# =========================================================

def process_chat_message(
    text,
    user_id
):

    text = normalize_text(
        text
    )

    if not text:

        return "Please type something."

    intent = detect_intent(
        text
    )

    # =====================================================
    # ADVANCED INSIGHTS
    # =====================================================

    if intent == "advanced_insights":

        return format_advanced_insights(
            user_id
        )

    # =====================================================
    # WHAT IF
    # =====================================================

    if intent == "what_if":

        return process_what_if(
            text,
            user_id
        )

    # =====================================================
    # SET BUDGET
    # =====================================================

    if intent == "set_budget":

        amount = extract_amount(
            text
        )

        if amount is None:

            return (
                "💳 Please mention your "
                "monthly budget.<br><br>"
                "Example:<br>"
                "<b>Set my budget to 5000</b>"
            )

        set_monthly_budget(
            user_id,
            amount
        )

        return (
            f"✅ Your monthly budget has "
            f"been set to <b>₹{amount:.2f}</b>."
        )

    # =====================================================
    # BUDGET QUERY
    # =====================================================

    if intent == "budget":

        budget = get_monthly_budget(
            user_id
        )

        spent = get_current_month_expense(
            user_id
        )

        if budget <= 0:

            return (
                "💳 You haven't set a monthly "
                "budget yet.<br><br>"
                "Example:<br>"
                "<b>Set my budget to 5000</b>"
            )

        percentage = (
            spent / budget
        ) * 100

        remaining = (
            budget - spent
        )

        response = (
            f"💳 <b>Monthly Budget</b>"
            f"<br><br>"
            f"Budget: <b>₹{budget:.2f}</b>"
            f"<br>"
            f"Spent: <b>₹{spent:.2f}</b>"
            f"<br>"
            f"Used: <b>{percentage:.2f}%</b>"
            f"<br>"
        )

        if remaining >= 0:

            response += (
                f"Remaining: "
                f"<b>₹{remaining:.2f}</b>"
            )

        else:

            response += (
                f"Exceeded by: "
                f"<b>₹{abs(remaining):.2f}</b>"
            )

        return response

    # =====================================================
    # BASIC INSIGHTS
    # =====================================================

    if intent == "insights":

        categories = get_category_totals(
            user_id,
            "month"
        )

        if not categories:

            return (
                "📊 No expenses found "
                "for this month yet."
            )

        response = (
            "📊 <b>This Month's Spending</b>"
            "<br><br>"
        )

        for item in categories:

            response += (
                f"• {item['category']}: "
                f"<b>₹{item['total']:.2f}</b>"
                "<br>"
            )

        highest = categories[0]

        response += (
            "<br>"
            f"🏆 Highest spending category: "
            f"<b>{highest['category']}</b>"
        )

        return response

    # =====================================================
    # SPENDING QUERY
    # =====================================================

    if intent == "spending_query":

        period = detect_period(
            text
        )

        category = None

        detected_category = detect_category(
            text
        )

        # Use a detected category only when the message
        # contains a known category keyword.
        if detected_category != "Other":

            category = detected_category

        total = get_period_total(
            user_id,
            period,
            category
        )

        period_names = {

            "today": "today",

            "yesterday": "yesterday",

            "last7days": "the last 7 days",

            "week": "this week",

            "month": "this month",

            "lastmonth": "last month",

            "all": "all time"
        }

        period_name = period_names.get(
            period,
            "this period"
        )

        if category:

            return (
                f"💰 Your {category} spending "
                f"for {period_name} is "
                f"<b>₹{total:.2f}</b>."
            )

        return (
            f"💰 Your total spending "
            f"for {period_name} is "
            f"<b>₹{total:.2f}</b>."
        )

    # =====================================================
    # ADD EXPENSE
    # =====================================================

    if intent == "add_expense":

        amount = extract_amount(
            text
        )

        if amount is None:

            return (
                "I couldn't find the amount. "
                "Example: <b>₹500 food-ku "
                "spend panninen</b>"
            )

        category = detect_category(
            text
        )

        expense_date = detect_expense_date(
            text
        )

        save_expense(
            user_id=user_id,
            amount=amount,
            category=category,
            description=text,
            expense_date=expense_date
        )

        if expense_date != date.today().isoformat():

            date_text = "yesterday"

        else:

            date_text = "today"

        budget = get_monthly_budget(
            user_id
        )

        current_month_total = (
            get_current_month_expense(
                user_id
            )
        )

        response = (
            f"✅ Expense added successfully!"
            f"<br><br>"
            f"💰 Amount: <b>₹{amount:.2f}</b>"
            f"<br>"
            f"📂 Category: <b>{category}</b>"
            f"<br>"
            f"📅 Date: <b>{date_text}</b>"
        )

        if budget > 0:

            percentage = (
                current_month_total
                / budget
            ) * 100

            if percentage >= 80:

                response += (
                    "<br><br>"
                    f"⚠️ You've used "
                    f"<b>{percentage:.1f}%</b> "
                    f"of your monthly budget."
                )

        return response

    # =====================================================
    # HELP
    # =====================================================

    if intent == "help":

        return """
        🤖 <b>I can help you with:</b>
        <br><br>

        💰 Add expenses
        <br>
        📊 Check total spending
        <br>
        📅 Check daily/weekly/monthly spending
        <br>
        📂 Category-wise spending
        <br>
        💳 Set and check budget
        <br>
        🧠 Advanced spending analysis
        <br>
        🔮 What-if savings analysis
        <br><br>

        <b>Examples:</b>
        <br>
        ₹500 food-ku spend panninen
        <br>
        How much did I spend this month?
        <br>
        Where am I spending more?
        <br>
        Set my budget to 5000
        <br>
        Analyze my spending
        <br>
        If I reduce shopping by 1000?
        <br>
        Save 500 every month for 6 months
        """

    # =====================================================
    # UNKNOWN
    # =====================================================

    return """
    🤔 I couldn't understand that.
    <br><br>

    Try something like:
    <br>
    • ₹500 food-ku spend panninen
    <br>
    • How much did I spend this month?
    <br>
    • Where am I spending more?
    <br>
    • What is my average daily spending?
    <br>
    • What is my highest transaction?
    <br>
    • Analyze my spending
    <br>
    • Set my budget to 5000
    <br>
    • If I reduce shopping by 1000?
    """


# =========================================================
# HOME
# =========================================================

@app.route("/")
@login_required
def home():

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, username
        FROM users
        WHERE id != ?
        ORDER BY username
    """, (current_user.id,))

    other_accounts = cursor.fetchall()
    conn.close()

    return render_template(
        "index.html",
        username=current_user.username,
        other_accounts=other_accounts
    )


# =========================================================
# REGISTER
# =========================================================

@app.route(
    "/register",
    methods=["GET", "POST"]
)
def register():

    if request.method == "POST":

        username = request.form.get(
            "username",
            ""
        ).strip()

        password = request.form.get(
            "password",
            ""
        )

        if not username or not password:

            return render_template(
                "register.html",
                error="Username and password are required."
            )

        conn = get_connection()

        cursor = conn.cursor()

        try:

            password_hash = generate_password_hash(
                password
            )

            cursor.execute("""
                INSERT INTO users
                (username, password)
                VALUES (?, ?)
            """, (
                username,
                password_hash
            ))

            conn.commit()

        except sqlite3.IntegrityError:

            conn.close()

            return render_template(
                "register.html",
                error="Username already exists."
            )

        conn.close()

        return redirect(
            url_for("login")
        )

    return render_template(
        "register.html"
    )


# =========================================================
# LOGIN
# =========================================================

@app.route(
    "/login",
    methods=["GET", "POST"]
)
def login():

    if request.method == "POST":

        username = request.form.get(
            "username",
            ""
        ).strip()

        password = request.form.get(
            "password",
            ""
        )

        conn = get_connection()

        cursor = conn.cursor()

        cursor.execute("""
            SELECT *
            FROM users
            WHERE username = ?
        """, (
            username,
        ))

        user = cursor.fetchone()

        conn.close()

        if (
            user
            and check_password_hash(
                user["password"],
                password
            )
        ):

            login_user(
                User(
                    user["id"],
                    user["username"],
                    user["password"]
                )
            )

            return redirect(
                url_for("home")
            )

        return render_template(
            "login.html",
            error="Invalid username or password."
        )

    selected_username = request.args.get("username", "").strip()

    return render_template(
        "login.html",
        selected_username=selected_username
    )


# =========================================================
# LOGOUT
# =========================================================

@app.route("/logout")
@login_required
def logout():

    logout_user()

    return redirect(
        url_for("login")
    )


# =========================================================
# SWITCH ACCOUNT
# =========================================================

@app.route("/switch-account/<int:user_id>")
@login_required
def switch_account(user_id):

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT username
        FROM users
        WHERE id = ?
    """, (user_id,))

    account = cursor.fetchone()
    conn.close()

    if not account:
        return redirect(url_for("home"))

    target_username = account["username"]

    logout_user()

    return redirect(
        url_for("login", username=target_username)
    )


# =========================================================
# CHAT API
# =========================================================

@app.route(
    "/chat",
    methods=["POST"]
)
@login_required
def chat():

    data = request.get_json(
        silent=True
    ) or {}

    message = data.get(
        "message",
        ""
    ).strip()

    print("=" * 40)

    print(
        "MESSAGE RECEIVED:",
        message
    )

    print(
        "USER ID:",
        current_user.id
    )

    print("=" * 40)

    response = process_chat_message(
        message,
        current_user.id
    )

    return jsonify({
        "response": response
    })


# =========================================================
# ADD EXPENSE API
# =========================================================

@app.route(
    "/add_expense",
    methods=["POST"]
)
@login_required
def add_expense():

    data = request.get_json(
        silent=True
    ) or {}

    amount = data.get(
        "amount"
    )

    category = data.get(
        "category",
        "Other"
    )

    description = data.get(
        "description",
        ""
    )

    if amount is None:

        return jsonify({
            "success": False,
            "message": "Amount is required."
        })

    try:

        amount = float(
            amount
        )

    except ValueError:

        return jsonify({
            "success": False,
            "message": "Invalid amount."
        })

    expense_id = save_expense(
        user_id=current_user.id,
        amount=amount,
        category=category,
        description=description
    )

    return jsonify({
        "success": True,
        "expense_id": expense_id
    })


# =========================================================
# TOTAL EXPENSE
# =========================================================

@app.route("/total_expense")
@login_required
def total_expense():

    total = get_all_total(
        current_user.id
    )

    return jsonify({
        "total": total
    })


# =========================================================
# CATEGORY EXPENSE
# =========================================================

@app.route(
    "/category_expense/<category>"
)
@login_required
def category_expense(category):

    total = get_period_total(
        current_user.id,
        "all",
        category
    )

    return jsonify({
        "category": category,
        "total": total
    })


# =========================================================
# PERIOD EXPENSE
# =========================================================

@app.route(
    "/period_expense/<period>"
)
@login_required
def period_expense(period):

    total = get_period_total(
        current_user.id,
        period
    )

    return jsonify({
        "period": period,
        "total": total
    })


# =========================================================
# BASIC INSIGHTS API
# =========================================================

@app.route("/insights")
@login_required
def insights():

    categories = get_category_totals(
        current_user.id,
        "month"
    )

    return jsonify({
        "categories": categories
    })


# =========================================================
# ADVANCED INSIGHTS API
# =========================================================

@app.route("/advanced_insights")
@login_required
def advanced_insights():

    data = get_advanced_insights(
        current_user.id
    )

    return jsonify(data)


# =========================================================
# BUDGET SET API
# =========================================================

@app.route(
    "/set_budget",
    methods=["POST"]
)
@login_required
def set_budget_api():

    data = request.get_json(
        silent=True
    ) or {}

    amount = data.get(
        "amount"
    )

    try:

        amount = float(
            amount
        )

    except (
        TypeError,
        ValueError
    ):

        return jsonify({
            "success": False,
            "message": "Invalid budget amount."
        })

    set_monthly_budget(
        current_user.id,
        amount
    )

    return jsonify({
        "success": True,
        "budget": amount
    })


# =========================================================
# BUDGET API
# =========================================================

@app.route("/budget")
@login_required
def budget_api():

    budget = get_monthly_budget(
        current_user.id
    )

    spent = get_current_month_expense(
        current_user.id
    )

    percentage = 0

    if budget > 0:

        percentage = (
            spent / budget
        ) * 100

    return jsonify({
        "budget": budget,
        "spent": spent,
        "percentage": round(
            percentage,
            2
        ),
        "remaining": round(
            budget - spent,
            2
        )
    })


# =========================================================
# BUDGET STATUS API
# =========================================================

@app.route("/budget_status")
@login_required
def budget_status():

    budget = get_monthly_budget(
        current_user.id
    )

    spent = get_current_month_expense(
        current_user.id
    )

    if budget <= 0:

        status = "not_set"

        percentage = 0

    else:

        percentage = (
            spent / budget
        ) * 100

        if percentage >= 100:

            status = "exceeded"

        elif percentage >= 80:

            status = "warning"

        else:

            status = "safe"

    return jsonify({
        "budget": budget,
        "spent": spent,
        "percentage": round(
            percentage,
            2
        ),
        "status": status
    })


# =========================================================
# SUMMARY API
# =========================================================

@app.route("/summary")
@login_required
def summary():

    budget = get_monthly_budget(
        current_user.id
    )

    spent = get_current_month_expense(
        current_user.id
    )

    categories = get_category_totals(
        current_user.id,
        "month"
    )

    percentage = 0

    if budget > 0:

        percentage = (
            spent / budget
        ) * 100

    return jsonify({

        "total": spent,

        "budget": budget,

        "budget_percentage":
            round(
                percentage,
                2
            ),

        "categories":
            categories
    })


# =========================================================
# SMART SPENDING ALERTS
# =========================================================

@app.route("/smart_alerts")
@login_required
def smart_alerts():

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT category, SUM(amount) AS total
        FROM expenses
        WHERE user_id = ?
          AND strftime('%Y-%m', expense_date) = strftime('%Y-%m', 'now', 'localtime')
        GROUP BY category
        ORDER BY total DESC
    """, (current_user.id,))

    rows = cursor.fetchall()

    cursor.execute("""
        SELECT COALESCE(SUM(amount), 0) AS total
        FROM expenses
        WHERE user_id = ?
          AND strftime('%Y-%m', expense_date) = strftime('%Y-%m', 'now', 'localtime')
    """, (current_user.id,))

    month_total = float(cursor.fetchone()["total"] or 0)

    cursor.execute("""
        SELECT monthly_budget
        FROM budgets
        WHERE user_id = ?
    """, (current_user.id,))

    budget_row = cursor.fetchone()
    budget = float(budget_row["monthly_budget"] or 0) if budget_row else 0
    conn.close()

    alerts = []

    if budget > 0 and month_total >= budget:
        alerts.append({
            "level": "danger",
            "title": "Budget exceeded",
            "message": f"This month you have spent ₹{month_total:.0f} against a budget of ₹{budget:.0f}."
        })
    elif budget > 0 and month_total >= budget * 0.80:
        alerts.append({
            "level": "warning",
            "title": "Budget getting close",
            "message": f"You have used {month_total / budget * 100:.0f}% of your monthly budget."
        })

    if month_total > 0 and rows:
        top = rows[0]
        top_category = top["category"] or "Other"
        top_amount = float(top["total"] or 0)
        share = top_amount / month_total
        if share >= 0.40:
            alerts.append({
                "level": "info",
                "title": f"High {top_category} spending",
                "message": f"{top_category} accounts for {share * 100:.0f}% of your spending this month (₹{top_amount:.0f})."
            })

    if not alerts:
        alerts.append({
            "level": "safe",
            "title": "Spending looks balanced",
            "message": "No unusual spending alert was triggered for this month."
        })

    return jsonify({"alerts": alerts})


# =========================================================
# PERSONALIZED SAVING TIPS
# =========================================================

@app.route("/saving_tips")
@login_required
def saving_tips():

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT category, SUM(amount) AS total
        FROM expenses
        WHERE user_id = ?
          AND strftime('%Y-%m', expense_date) = strftime('%Y-%m', 'now', 'localtime')
        GROUP BY category
        ORDER BY total DESC
    """, (current_user.id,))
    categories = cursor.fetchall()

    cursor.execute("""
        SELECT COALESCE(SUM(amount), 0) AS total
        FROM expenses
        WHERE user_id = ?
          AND strftime('%Y-%m', expense_date) = strftime('%Y-%m', 'now', 'localtime')
    """, (current_user.id,))
    month_total = float(cursor.fetchone()["total"] or 0)

    cursor.execute("""
        SELECT monthly_budget
        FROM budgets
        WHERE user_id = ?
    """, (current_user.id,))
    budget_row = cursor.fetchone()
    budget = float(budget_row["monthly_budget"] or 0) if budget_row else 0

    conn.close()

    tips = []

    if not categories:
        tips.append("Add a few expenses to get personalized saving tips.")
    else:
        top = categories[0]
        category = top["category"] or "Other"
        amount = float(top["total"] or 0)
        share = amount / month_total if month_total else 0

        if share >= 0.40:
            tips.append(f"Your highest spending is {category}. Review a few {category.lower()} expenses and look for items you can reduce.")
        else:
            tips.append(f"{category} is your highest spending category at ₹{amount:.0f}. Keep an eye on it as the month continues.")

        if len(categories) >= 2:
            second = categories[1]
            second_category = second["category"] or "Other"
            second_amount = float(second["total"] or 0)
            tips.append(f"Your next biggest category is {second_category} at ₹{second_amount:.0f}. A small reduction here can add to your monthly savings.")

        if budget > 0:
            remaining = budget - month_total
            if remaining > 0:
                tips.append(f"You have about ₹{remaining:.0f} left in your monthly budget. Set a simple daily spending limit for the remaining days.")
            else:
                tips.append("Your spending has reached the monthly budget. Consider postponing non-essential purchases until the next budget period.")
        else:
            tips.append("Set a monthly budget to make your saving target easier to track.")

    return jsonify({"tips": tips[:3]})


# =========================================================
# TRANSACTIONS
# =========================================================

@app.route("/transactions")
@login_required
def transactions():

    conn = get_connection()

    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            id,
            amount,
            category,
            description,
            expense_date
        FROM expenses
        WHERE user_id = ?
        ORDER BY expense_date DESC, id DESC
    """, (
        current_user.id,
    ))

    rows = cursor.fetchall()

    conn.close()

    result = []

    for row in rows:

        result.append({

            "id": row["id"],

            "amount":
                float(row["amount"]),

            "category":
                row["category"],

            "description":
                row["description"],

            "expense_date":
                row["expense_date"]
        })

    return jsonify(result)


# =========================================================
# DELETE EXPENSE
# =========================================================

@app.route(
    "/delete_expense/<int:expense_id>",
    methods=["DELETE"]
)
@login_required
def delete_expense(
    expense_id
):

    conn = get_connection()

    cursor = conn.cursor()

    cursor.execute("""
        DELETE FROM expenses
        WHERE id = ?
        AND user_id = ?
    """, (
        expense_id,
        current_user.id
    ))

    conn.commit()

    deleted = cursor.rowcount

    conn.close()

    if deleted:

        return jsonify({
            "success": True,
            "message": "Expense deleted."
        })

    return jsonify({
        "success": False,
        "message": "Expense not found."
    })


# =========================================================
# EXPORT REPORT
# =========================================================

@app.route("/export_report")
@login_required
def export_report():

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT expense_date, description, category, amount
        FROM expenses
        WHERE user_id = ?
        ORDER BY expense_date DESC, id DESC
    """, (current_user.id,))

    rows = cursor.fetchall()
    conn.close()

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["Date", "Description", "Category", "Amount (INR)"])

    for row in rows:
        writer.writerow([
            row["expense_date"],
            row["description"] or "Expense",
            row["category"] or "Other",
            float(row["amount"])
        ])

    response = app.response_class(
        output.getvalue(),
        mimetype="text/csv",
        headers={
            "Content-Disposition": "attachment; filename=expense_report.csv"
        }
    )

    return response


# =========================================================
# DASHBOARD
# =========================================================

@app.route("/dashboard")
@login_required
def dashboard():

    return render_template(
        "dashboard.html",
        username=current_user.username
    )
create_database()

# =========================================================
# START APPLICATION
# =========================================================

if __name__ == "__main__":

    create_database()

    print("=" * 40)

    print(
        "       EXPENSE AI ASSISTANT"
    )

    print("=" * 40)

    print(
        "Using database:",
        DATABASE
    )

    print(
        "Chatbot ready!"
    )

    print("=" * 40)

    app.run(
        debug=True
    )