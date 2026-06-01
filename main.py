import os
import httpx
import threading
import schedule
import time
from flask import Flask, request, jsonify
from datetime import datetime, timedelta

app = Flask(__name__)

B24_WEBHOOK = os.environ.get("B24_WEBHOOK", "").strip()
REPORT_USER_ID = "226"  # Твой личный ID в Битрикс24

# ===================== БИТРИКС API =====================

def b24_call(method, params=None):
    try:
        url = f"{B24_WEBHOOK}/{method}.json"
        resp = httpx.post(url, json=params or {}, timeout=30)
        data = resp.json()
        return data.get("result", [])
    except Exception as e:
        print(f"Ошибка B24 API {method}: {e}")
        return []

def send_b24_message(dialog_id, text):
    try:
        url = f"{B24_WEBHOOK}/im.message.add.json"
        resp = httpx.post(url, json={"DIALOG_ID": dialog_id, "MESSAGE": text}, timeout=10)
        print(f"Ответ Битрикс: {resp.status_code}")
    except Exception as e:
        print(f"Ошибка отправки: {e}")

# ===================== ЗАДАЧИ =====================

def get_users():
    """Получаем всех сотрудников"""
    result = b24_call("user.get", {"ACTIVE": True, "USER_TYPE": "employee"})
    users = {}
    if isinstance(result, list):
        for u in result:
            uid = str(u.get("ID", ""))
            name = f"{u.get('NAME', '')} {u.get('LAST_NAME', '')}".strip()
            if uid and name:
                users[uid] = name
    return users

def get_tasks_for_user(user_id):
    """Получаем задачи сотрудника за сегодня"""
    today = datetime.now().strftime("%Y-%m-%dT00:00:00+03:00")
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%dT00:00:00+03:00")

    # Выполненные задачи
    done = b24_call("tasks.task.list", {
        "filter": {
            "RESPONSIBLE_ID": user_id,
            "STATUS": 5,  # завершена
            ">=CLOSED_DATE": today,
            "<CLOSED_DATE": tomorrow,
        },
        "select": ["ID", "TITLE", "STATUS"]
    })

    # Просроченные / не выполненные задачи (дедлайн сегодня или раньше)
    overdue = b24_call("tasks.task.list", {
        "filter": {
            "RESPONSIBLE_ID": user_id,
            "!STATUS": [4, 5],  # не в работе и не завершена
            "<=DEADLINE": today,
        },
        "select": ["ID", "TITLE", "STATUS", "DEADLINE"]
    })

    # Задачи в работе
    in_progress = b24_call("tasks.task.list", {
        "filter": {
            "RESPONSIBLE_ID": user_id,
            "STATUS": 3,  # в работе
        },
        "select": ["ID", "TITLE", "STATUS", "DEADLINE"]
    })

    done_list = []
    if isinstance(done, dict):
        done_list = [t["title"] for t in done.get("tasks", [])]
    elif isinstance(done, list):
        done_list = [t.get("title", t.get("TITLE", "")) for t in done]

    overdue_list = []
    if isinstance(overdue, dict):
        overdue_list = [t["title"] for t in overdue.get("tasks", [])]
    elif isinstance(overdue, list):
        overdue_list = [t.get("title", t.get("TITLE", "")) for t in overdue]

    in_progress_list = []
    if isinstance(in_progress, dict):
        in_progress_list = [t["title"] for t in in_progress.get("tasks", [])]
    elif isinstance(in_progress, list):
        in_progress_list = [t.get("title", t.get("TITLE", "")) for t in in_progress]

    return done_list, in_progress_list, overdue_list

def generate_report():
    """Генерируем и отправляем ежедневный отчёт"""
    print(f"Генерация отчёта: {datetime.now()}")

    users = get_users()
    if not users:
        print("Нет сотрудников")
        send_b24_message(REPORT_USER_ID, "⚠️ Не удалось получить список сотрудников из Битрикс24.")
        return

    today_str = datetime.now().strftime("%d.%m.%Y")
    report_lines = [f"📊 *Отчёт по задачам за {today_str}*\n"]

    for user_id, name in users.items():
        if user_id == REPORT_USER_ID:
            continue  # пропускаем себя

        done, in_progress, overdue = get_tasks_for_user(user_id)

        lines = [f"\n👤 *{name}*"]

        if done:
            lines.append(f"✅ Выполнено ({len(done)}):")
            for t in done[:5]:
                lines.append(f"  • {t}")
            if len(done) > 5:
                lines.append(f"  ...и ещё {len(done)-5}")

        if in_progress:
            lines.append(f"🔄 В работе ({len(in_progress)}):")
            for t in in_progress[:5]:
                lines.append(f"  • {t}")
            if len(in_progress) > 5:
                lines.append(f"  ...и ещё {len(in_progress)-5}")

        if overdue:
            lines.append(f"❌ Просрочено ({len(overdue)}):")
            for t in overdue[:5]:
                lines.append(f"  • {t}")
            if len(overdue) > 5:
                lines.append(f"  ...и ещё {len(overdue)-5}")

        if not done and not in_progress and not overdue:
            lines.append("  — нет активных задач")

        report_lines.extend(lines)

    report = "\n".join(report_lines)
    send_b24_message(REPORT_USER_ID, report)
    print("Отчёт отправлен")

# ===================== FLASK =====================

@app.route("/", methods=["GET"])
def index():
    return "JOTO Tasks Report работает ✓"

@app.route("/report-now", methods=["GET"])
def report_now():
    threading.Thread(target=generate_report).start()
    return jsonify({"ok": True, "message": "Отчёт генерируется"})

# ===================== ЗАПУСК =====================

def run_scheduler():
    schedule.every().day.at("15:00").do(generate_report)  # 15:00 UTC = 18:00 МСК
    print("Планировщик запущен — отчёт каждый день в 18:00 МСК")
    while True:
        schedule.run_pending()
        time.sleep(60)

if __name__ == "__main__":
    threading.Thread(target=run_scheduler, daemon=True).start()
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
