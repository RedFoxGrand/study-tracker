import datetime
import os
import subprocess
import sys
import threading

BASE_DEFENSE_TITLE = "Защита у преподавателя"

STATUS_CONFIG = {
    0: {"label": "Не сделано", "color": "#EF4444", "text_color": "#FFFFFF"},
    1: {"label": "Частично сделано", "color": "#F97316", "text_color": "#FFFFFF"},
    2: {"label": "Сделано, но не сдано", "color": "#EAB308", "text_color": "#000000"},
    3: {"label": "Сдано", "color": "#22C55E", "text_color": "#FFFFFF"},
}

LESSON_TYPE_CONFIG = {
    "ЛР": {"label": "Лабораторная (ЛР)", "color": "#22C55E", "bg": "#14532D"},
    "ПЗ": {"label": "Практическая (ПЗ)", "color": "#38BDF8", "bg": "#0C4A6E"},
    "ЛК": {"label": "Лекция (ЛК)", "color": "#C084FC", "bg": "#3B0764"},
    "СОБ": {"label": "Событие", "color": "#A5B4FC", "bg": "#1E293B"},
}

BELL_PRESETS = [
    ("08:30", "09:55"),
    ("10:05", "11:30"),
    ("12:00", "13:25"),
    ("13:35", "15:00"),
    ("15:30", "16:55"),
    ("17:05", "18:30"),
    ("19:00", "20:25"),
    ("20:35", "22:00"),
]

MONTHS_NOMINATIVE = [
    "", "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"
]

MONTHS_GENITIVE = [
    "", "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря"
]

WEEKDAYS_SHORT = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
WEEKDAYS_FULL = [
    "Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"
]


def get_db_path():
    # Если запущено на телефоне в APK — пишем в закрытое хранилище Android
    app_storage = os.environ.get("FLET_APP_STORAGE_DATA")
    if app_storage:
        os.makedirs(app_storage, exist_ok=True)
        return os.path.join(app_storage, "labs_tracker.db")
    # На компьютере при разработке сохраняем рядом с main.py
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "labs_tracker.db")

DB_NAME = get_db_path()


def parse_date_safe(date_str: str):
    if not date_str:
        return None
    s = date_str.strip()
    try:
        return datetime.date.fromisoformat(s)
    except ValueError:
        pass
    for fmt in ("%d.%m.%Y", "%d.%m.%y"):
        try:
            return datetime.datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


def format_date_ru(iso_date: str) -> str:
    if not iso_date:
        return "не указано"
    dt = parse_date_safe(iso_date)
    if dt:
        return f"{dt.day} {MONTHS_GENITIVE[dt.month]} {dt.year} г."
    return iso_date


def format_short_date_ru(dt: datetime.date) -> str:
    return f"{WEEKDAYS_SHORT[dt.weekday()]}, {dt.day} {MONTHS_GENITIVE[dt.month]}"


def days_until(iso_date: str):
    dt = parse_date_safe(iso_date)
    if not dt:
        return None
    return (dt - datetime.date.today()).days


def get_academic_week_number(target_date: datetime.date, sem_start_date: datetime.date) -> int:
    monday_start = sem_start_date - datetime.timedelta(days=sem_start_date.weekday())
    monday_target = target_date - datetime.timedelta(days=target_date.weekday())
    weeks_passed = (monday_target - monday_start).days // 7
    if weeks_passed < 0:
        return 1
    return (weeks_passed % 4) + 1


def send_os_notification(title: str, message: str):
    if sys.platform != "win32":
        return

    def _worker():
        try:
            safe_title = title.replace("'", "`'")
            safe_msg = message.replace("'", "`'")
            ps_script = (
                "Add-Type -AssemblyName System.Windows.Forms; "
                "Add-Type -AssemblyName System.Drawing; "
                "$n = New-Object System.Windows.Forms.NotifyIcon; "
                "$n.Icon = [System.Drawing.SystemIcons]::Warning; "
                "$n.BalloonTipTitle = '" + safe_title + "'; "
                "$n.BalloonTipText = '" + safe_msg + "'; "
                "$n.Visible =$True; "
                "$n.ShowBalloonTip(5000); "
                "Start-Sleep -Seconds 6; "
                "$n.Dispose();"
            )
            subprocess.Popen(
                ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps_script],
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception:
            pass

    threading.Thread(target=_worker, daemon=True).start()