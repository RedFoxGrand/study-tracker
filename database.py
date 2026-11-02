import base64
import datetime
import glob
import hashlib
import json
import os
import shutil
import sqlite3
import urllib.error
import urllib.request
import zlib

from config import (
    BASE_DEFENSE_TITLE,
    DB_NAME,
    WEEKDAYS_FULL,
    days_until,
    format_date_ru,
    get_academic_week_number,
    parse_date_safe,
)

NON_LAB_SUBJECTS = {
    "физк",
    "инф. час",
    "инф.час",
    "к.ч.",
    "к.ч",
    "кураторский час",
    "информационный час",
}


def get_conn():
    conn = sqlite3.connect(DB_NAME)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.create_function("lower", 1, lambda s: str(s).casefold() if s is not None else "")
    return conn


def ensure_base_step_for_lab(cur, lab_id: int, status: int):
    is_defended = 1 if status == 3 else 0
    cur.execute(
        "SELECT id FROM lab_steps WHERE lab_id = ? AND title = ?",
        (lab_id, BASE_DEFENSE_TITLE),
    )
    row = cur.fetchone()
    if row:
        cur.execute(
            "UPDATE lab_steps SET step_order = 0, is_done = ? WHERE id = ?",
            (is_defended, row[0]),
        )
    else:
        cur.execute(
            "INSERT INTO lab_steps (lab_id, step_order, title, is_done) VALUES (?, 0, ?, ?)",
            (lab_id, BASE_DEFENSE_TITLE, is_defended),
        )


def cleanup_orphan_and_non_lab_subjects(cur):
    cur.execute("SELECT id, name FROM subjects")
    for s_id, s_name in cur.fetchall():
        if s_name.strip().casefold() in NON_LAB_SUBJECTS:
            cur.execute("DELETE FROM labs WHERE subject_id = ?", (s_id,))
            cur.execute("UPDATE subjects SET is_tracked = 0 WHERE id = ?", (s_id,))

    cur.execute("""
        DELETE FROM subjects
        WHERE is_tracked = 0
          AND from_api = 0
          AND id NOT IN (SELECT DISTINCT subject_id FROM schedule)
    """)


def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS subjects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_name TEXT NOT NULL,
            name TEXT NOT NULL,
            is_tracked INTEGER NOT NULL DEFAULT 1,
            from_api INTEGER NOT NULL DEFAULT 0,
            UNIQUE(group_name, name)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS labs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject_id INTEGER NOT NULL,
            lab_num INTEGER NOT NULL,
            status INTEGER DEFAULT 0,
            deadline TEXT DEFAULT '',
            planned_date TEXT DEFAULT '',
            completed_date TEXT DEFAULT '',
            title TEXT DEFAULT '',
            goal TEXT DEFAULT '',
            description TEXT DEFAULT '',
            comment TEXT DEFAULT '',
            FOREIGN KEY (subject_id) REFERENCES subjects (id) ON DELETE CASCADE
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS lab_steps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lab_id INTEGER NOT NULL,
            step_order INTEGER NOT NULL,
            title TEXT NOT NULL,
            is_done INTEGER DEFAULT 0,
            FOREIGN KEY (lab_id) REFERENCES labs (id) ON DELETE CASCADE
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS schedule (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_name TEXT NOT NULL,
            subject_id INTEGER NOT NULL,
            day_of_week INTEGER NOT NULL,
            weeks TEXT NOT NULL DEFAULT '1,2,3,4',
            lesson_date TEXT DEFAULT '',
            subgroup INTEGER DEFAULT 0,
            lesson_type TEXT DEFAULT 'ЛР',
            start_time TEXT DEFAULT '08:30',
            end_time TEXT DEFAULT '09:55',
            room TEXT DEFAULT '',
            teacher TEXT DEFAULT '',
            note TEXT DEFAULT '',
            is_api_synced INTEGER DEFAULT 1,
            FOREIGN KEY (subject_id) REFERENCES subjects (id) ON DELETE CASCADE
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS schedule_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_name TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            event_date TEXT DEFAULT '',
            day_of_week INTEGER DEFAULT 0,
            weeks TEXT DEFAULT '1,2,3,4',
            start_time TEXT DEFAULT '08:30',
            end_time TEXT DEFAULT '09:55',
            teacher TEXT DEFAULT '',
            room TEXT DEFAULT '',
            is_api_synced INTEGER DEFAULT 0
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS saved_groups (
            group_name TEXT PRIMARY KEY,
            is_initialized INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT DEFAULT '',
            schedule_hash TEXT DEFAULT ''
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS app_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)

    cur.execute("PRAGMA table_info(custom_themes)")
    cols = [col[1] for col in cur.fetchall()]
    if cols and "url" not in cols:
        cur.execute("DROP TABLE custom_themes")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS custom_themes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            url TEXT NOT NULL
        )
    """)

    cur.execute("SELECT value FROM app_settings WHERE key = 'bg_image_url'")
    row = cur.fetchone()
    if row and row[0] and (row[0].startswith("data:image") or row[0].startswith("/data")):
        cur.execute("UPDATE app_settings SET value = '/space.jpg' WHERE key = 'bg_image_url'")

    default_settings = {
        "semester_start": "2026-09-01",
        "semester_end": "2026-12-26",
        "main_group": "",
        "main_subgroup": "1",
        "view_group": "",
        "view_subgroup": "0",
        "is_onboarded": "0",
    }
    for k, v in default_settings.items():
        cur.execute("INSERT OR IGNORE INTO app_settings (key, value) VALUES (?, ?)", (k, v))

    cur.execute("SELECT COUNT(*) FROM subjects WHERE is_tracked = 1")
    if cur.fetchone()[0] > 0:
        cur.execute("UPDATE app_settings SET value = '1' WHERE key = 'is_onboarded'")

    cur.execute("PRAGMA table_info(schedule)")
    sched_cols = [c[1] for c in cur.fetchall()]
    if "orig_slot" not in sched_cols:
        cur.execute("ALTER TABLE schedule ADD COLUMN orig_slot TEXT DEFAULT ''")

    cleanup_orphan_and_non_lab_subjects(cur)
    cur.execute("DELETE FROM schedule_events WHERE id = 13 OR title = 'выаыва'")
    conn.commit()
    conn.close()


_SETTINGS_CACHE = {}


def get_setting(key: str, default: str = "") -> str:
    if key in _SETTINGS_CACHE:
        return _SETTINGS_CACHE[key]
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT value FROM app_settings WHERE key = ?", (key,))
    row = cur.fetchone()
    conn.close()
    val = row[0] if row else default
    _SETTINGS_CACHE[key] = val
    return val


def set_setting(key: str, value: str):
    _SETTINGS_CACHE[key] = value
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("INSERT OR REPLACE INTO app_settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()


def ensure_group_labs_initialized(group_name: str):
    """Универсальная генерация 4 лаб по умолчанию для любой группы БГУИР."""
    grp = group_name.strip()
    if not grp:
        return
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT DISTINCT s.id, s.name FROM schedule sc
        JOIN subjects s ON s.id = sc.subject_id
        WHERE sc.group_name = ? AND sc.lesson_type = 'ЛР' AND s.is_tracked = 1
    """, (grp,))
    lr_subjects = cur.fetchall()

    for s_id, s_name in lr_subjects:
        low = s_name.strip().casefold()
        if low in NON_LAB_SUBJECTS:
            continue
        cur.execute("SELECT COUNT(*) FROM labs WHERE subject_id = ?", (s_id,))
        if cur.fetchone()[0] == 0:
            for i in range(1, 5):
                cur.execute("INSERT INTO labs (subject_id, lab_num, status) VALUES (?, ?, 0)", (s_id, i))
                ensure_base_step_for_lab(cur, cur.lastrowid, 0)
            cur.execute("UPDATE subjects SET is_tracked = 1 WHERE id = ?", (s_id,))

    cur.execute("UPDATE saved_groups SET is_initialized = 1 WHERE group_name = ?", (grp,))
    conn.commit()
    conn.close()

def cycle_lab_status(lab_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT status FROM labs WHERE id = ?", (lab_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return
    cur_status = row[0]
    next_status = (cur_status + 1) % 4
    comp_date = datetime.date.today().isoformat() if next_status == 3 else ""
    cur.execute("UPDATE labs SET status = ?, completed_date = ? WHERE id = ?", (next_status, comp_date, lab_id))
    ensure_base_step_for_lab(cur, lab_id, next_status)
    conn.commit()
    conn.close()

def get_saved_groups() -> list:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT group_name, is_initialized, updated_at FROM saved_groups ORDER BY group_name ASC")
    rows = cur.fetchall()
    conn.close()
    return rows


def delete_saved_group_schedule(group_name: str):
    grp = group_name.strip()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM schedule WHERE group_name = ?", (grp,))
    cur.execute("DELETE FROM schedule_events WHERE group_name = ?", (grp,))
    cur.execute("DELETE FROM saved_groups WHERE group_name = ?", (grp,))
    cur.execute("DELETE FROM subjects WHERE group_name = ? AND is_tracked = 0", (grp,))
    conn.commit()
    conn.close()


def renumber_subject_labs(conn, subject_id: int):
    cur = conn.cursor()
    cur.execute(
        "SELECT id FROM labs WHERE subject_id = ? ORDER BY lab_num ASC, id ASC",
        (subject_id,),
    )
    rows = cur.fetchall()
    for new_num, (l_id,) in enumerate(rows, start=1):
        cur.execute("UPDATE labs SET lab_num = ? WHERE id = ?", (new_num, l_id))


def resolve_subject_for_schedule(
    cur, group_name: str, raw_name: str, has_labs: bool
) -> int:
    clean_name = raw_name.strip()
    low_name = clean_name.casefold()

    cur.execute("SELECT id, name FROM subjects WHERE group_name = ?", (group_name,))
    for s_id, s_name in cur.fetchall():
        if s_name.strip().casefold() == low_name:
            cur.execute("UPDATE subjects SET from_api = 1 WHERE id = ?", (s_id,))
            return s_id

    should_track = bool(has_labs and (low_name not in NON_LAB_SUBJECTS))
    cur.execute(
        "INSERT INTO subjects (group_name, name, is_tracked, from_api) VALUES (?, ?, ?, 1)",
        (group_name, clean_name, 1 if should_track else 0),
    )
    return cur.lastrowid


def import_schedule_from_bsuir_api(group_number: str) -> tuple[bool, str]:
    grp = (group_number or "").strip()
    if not grp.isdigit() or len(grp) != 6:
        return False, "Указанная группа не найдена"

    url = f"https://iis.bsuir.by/api/v1/schedule?studentGroup={grp}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            raw_body = resp.read().decode("utf-8").strip()
            if not raw_body:
                return False, "Указанная группа не найдена"
            data = json.loads(raw_body)
    except urllib.error.HTTPError as e:
        if e.code in (400, 404):
            return False, "Указанная группа не найдена"
        return False, f"Ошибка сервера ИИС БГУИР (код {e.code})"
    except urllib.error.URLError:
        return False, "Нет подключения к ИИС БГУИР. Сохранённое расписание работает офлайн."
    except Exception:
        return False, "Указанная группа не найдена"

    if not isinstance(data, dict):
        return False, "Указанная группа не найдена"

    schedules_dict = data.get("schedules") or {}
    if not schedules_dict:
        return False, "Указанная группа не найдена"

    day_name_to_idx = {name: idx for idx, name in enumerate(WEEKDAYS_FULL[:6])}

    subjects_with_lr = set()
    for day_name, lessons in schedules_dict.items():
        for item in lessons or []:
            if not item.get("announcement") and (item.get("lessonTypeAbbrev") or "").upper() == "ЛР":
                s_ab = (item.get("subject") or "").strip().casefold()
                if s_ab:
                    subjects_with_lr.add(s_ab)

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT s.name, sc.day_of_week, sc.start_time, sc.lesson_type, sc.subgroup, sc.note
        FROM schedule sc
        JOIN subjects s ON s.id = sc.subject_id
        WHERE sc.group_name = ? AND sc.is_api_synced = 1 AND sc.note != ''
    """, (grp,))
    saved_notes = {
        (r[0].strip().casefold(), r[1], r[2], r[3], r[4]): r[5]
        for r in cur.fetchall()
    }

    cur.execute("DELETE FROM schedule WHERE group_name = ? AND is_api_synced = 1", (grp,))
    cur.execute("DELETE FROM schedule_events WHERE group_name = ? AND is_api_synced = 1", (grp,))

    for day_name, lessons in schedules_dict.items():
        dow = day_name_to_idx.get(day_name)
        if dow is None or not lessons:
            continue
        for item in lessons:
            wk_list = item.get("weekNumber") or [1, 2, 3, 4]
            wks_clean = sorted({str(w) for w in wk_list if w in (1, 2, 3, 4)})
            weeks_str = ",".join(wks_clean) if wks_clean else "1,2,3,4"

            st_time = (item.get("startLessonTime") or "08:30").strip()
            end_time = (item.get("endLessonTime") or "09:55").strip()
            if len(st_time) == 4:
                st_time = "0" + st_time
            if len(end_time) == 4:
                end_time = "0" + end_time

            auditories = item.get("auditories") or []
            room_str = ", ".join(auditories).replace(" к.", "").strip() if auditories else ""

            employees = item.get("employees") or []
            teacher_names = []
            for emp in employees:
                last_n = emp.get("lastName", "")
                first_i = (emp.get("firstName", "")[:1] + ".") if emp.get("firstName") else ""
                mid_i = (emp.get("middleName", "")[:1] + ".") if emp.get("middleName") else ""
                teacher_names.append(f"{last_n} {first_i} {mid_i}".strip())
            teacher_str = ", ".join(teacher_names)

            is_announcement = bool(item.get("announcement"))
            l_type_raw = (item.get("lessonTypeAbbrev") or "").upper()

            if is_announcement or l_type_raw not in ("ЛР", "ПЗ", "ЛК"):
                raw_subj = (item.get("subject") or "").strip()
                raw_note = (item.get("note") or item.get("subjectFullName") or "").strip()

                ev_title = raw_subj if (raw_subj and len(raw_subj) <= 22 and raw_subj != raw_note) else "Событие"
                ev_desc = raw_note

                start_d = (item.get("startLessonDate") or "").strip()
                end_d = (item.get("endLessonDate") or "").strip()
                if start_d and end_d:
                    sd_short = start_d[:5] if len(start_d) >= 5 else start_d
                    ed_short = end_d[:5] if len(end_d) >= 5 else end_d
                    date_range_tag = f"{sd_short}–{ed_short}"
                    ev_desc = f"{ev_desc} [{date_range_tag}]".strip()

                ev_date_iso = ""
                if item.get("dateLesson") and not (start_d and end_d):
                    dt_parsed = parse_date_safe(item.get("dateLesson"))
                    if dt_parsed:
                        ev_date_iso = dt_parsed.isoformat()

                cur.execute(
                    """
                    SELECT id FROM schedule_events
                    WHERE group_name = ? AND day_of_week = ? AND start_time = ? AND is_api_synced = 0
                    """,
                    (grp, dow, st_time),
                )
                if cur.fetchone():
                    continue

                cur.execute(
                    """
                    INSERT INTO schedule_events
                    (group_name, title, description, event_date, day_of_week, weeks,
                     start_time, end_time, teacher, room, is_api_synced)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                    """,
                    (grp, ev_title, ev_desc, ev_date_iso, dow, weeks_str, st_time, end_time, teacher_str, room_str),
                )
                continue

            subj_abbrev = (item.get("subject") or "").strip()
            if not subj_abbrev:
                continue

            has_lr = subj_abbrev.casefold() in subjects_with_lr
            s_id = resolve_subject_for_schedule(cur, grp, subj_abbrev, has_labs=has_lr)
            subg = int(item.get("numSubgroup") or 0)

            preserved_note = saved_notes.get((subj_abbrev.casefold(), dow, st_time, l_type_raw, subg), "")
            note_str = preserved_note or (item.get("note") or "").strip()

            slot_key = f"{subj_abbrev.casefold()}_{dow}_{st_time}_{subg}_{l_type_raw}"

            cur.execute(
                """
                SELECT id FROM schedule
                WHERE group_name = ?
                  AND is_api_synced = 0
                  AND (
                      orig_slot = ?
                      OR (day_of_week = ? AND start_time = ? AND (subgroup = ? OR subgroup = 0 OR ? = 0))
                  )
                """,
                (grp, slot_key, dow, st_time, subg, subg),
            )
            if cur.fetchone():
                continue

            cur.execute(
                """
                INSERT INTO schedule
                (group_name, subject_id, day_of_week, weeks, lesson_date, subgroup, lesson_type,
                 start_time, end_time, room, teacher, note, is_api_synced, orig_slot)
                VALUES (?, ?, ?, ?, '', ?, ?, ?, ?, ?, ?, ?, 1, ?)
                """,
                (grp, s_id, dow, weeks_str, subg, l_type_raw, st_time, end_time, room_str, teacher_str, note_str, slot_key),
            )

    sched_hash = hashlib.md5(json.dumps(schedules_dict, sort_keys=True).encode("utf-8")).hexdigest()
    today_str = datetime.date.today().isoformat()
    cur.execute(
        "INSERT OR REPLACE INTO saved_groups (group_name, is_initialized, updated_at, schedule_hash) VALUES (?, 0, ?, ?)",
        (grp, today_str, sched_hash),
    )

    cleanup_orphan_and_non_lab_subjects(cur)
    conn.commit()
    conn.close()

    ensure_group_labs_initialized(grp)
    return True, f"Расписание {grp} загружено!"


def check_and_sync_all_saved_groups() -> list[str]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT group_name, schedule_hash FROM saved_groups")
    saved = cur.fetchall()
    conn.close()

    updated_groups = []
    for grp, old_hash in saved:
        url = f"https://iis.bsuir.by/api/v1/schedule?studentGroup={grp}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=6) as resp:
                raw_body = resp.read().decode("utf-8").strip()
                if not raw_body:
                    continue
                data = json.loads(raw_body)
            schedules_dict = data.get("schedules") or {}
            if not schedules_dict:
                continue
            new_hash = hashlib.md5(json.dumps(schedules_dict, sort_keys=True).encode("utf-8")).hexdigest()
            if not old_hash:
                conn2 = get_conn()
                conn2.execute("UPDATE saved_groups SET schedule_hash = ? WHERE group_name = ?", (new_hash, grp))
                conn2.commit()
                conn2.close()
            elif new_hash != old_hash:
                ok, _ = import_schedule_from_bsuir_api(grp)
                if ok:
                    updated_groups.append(grp)
        except Exception:
            continue
    return updated_groups


def get_summary_counts() -> dict:
    main_grp = get_setting("main_group", "")
    if not main_grp:
        return {0: 0, 1: 0, 2: 0, 3: 0}
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT l.status, COUNT(*)
        FROM labs l
        JOIN subjects s ON s.id = l.subject_id
        WHERE s.group_name = ? AND s.is_tracked = 1
        GROUP BY l.status
    """, (main_grp,))
    counts = {0: 0, 1: 0, 2: 0, 3: 0}
    for st, cnt in cur.fetchall():
        counts[st] = cnt
    conn.close()
    return counts


def get_subjects_with_labs() -> list:
    main_grp = get_setting("main_group", "")
    if not main_grp:
        return []
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, name FROM subjects WHERE group_name = ? AND is_tracked = 1 ORDER BY id ASC",
        (main_grp,),
    )
    subjects = cur.fetchall()
    result = []
    for s_id, s_name in subjects:
        if s_name.strip().casefold() in NON_LAB_SUBJECTS:
            continue
        cur.execute(
            """
            SELECT l.id, l.lab_num, l.status, l.deadline, l.planned_date, l.completed_date,
                   l.title, l.goal, l.description, l.comment,
                   (SELECT COUNT(*) FROM lab_steps ls WHERE ls.lab_id = l.id AND ls.is_done = 1),
                   (SELECT COUNT(*) FROM lab_steps ls WHERE ls.lab_id = l.id)
            FROM labs l
            WHERE l.subject_id = ?
            ORDER BY l.lab_num ASC
            """,
            (s_id,),
        )
        labs = cur.fetchall()
        result.append((s_id, s_name, labs))
    conn.close()
    return result


def get_dropdown_subjects_for_schedule(group_name: str, include_subj_id=None) -> list:
    conn = get_conn()
    cur = conn.cursor()
    if include_subj_id is not None:
        cur.execute(
            """
            SELECT id, name FROM subjects
            WHERE group_name = ?
              AND (
                  is_tracked = 1
                  OR id IN (SELECT DISTINCT subject_id FROM schedule WHERE group_name = ? AND lesson_date = '')
                  OR id = ?
              )
            ORDER BY name ASC
            """,
            (group_name, group_name, include_subj_id),
        )
    else:
        cur.execute(
            """
            SELECT id, name FROM subjects
            WHERE group_name = ?
              AND (
                  is_tracked = 1
                  OR id IN (SELECT DISTINCT subject_id FROM schedule WHERE group_name = ? AND lesson_date = '')
              )
            ORDER BY name ASC
            """,
            (group_name, group_name),
        )
    rows = cur.fetchall()
    conn.close()
    return rows


def add_lab_to_subject_db(subject_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT COALESCE(MAX(lab_num), 0) FROM labs WHERE subject_id = ?", (subject_id,))
    next_num = cur.fetchone()[0] + 1
    cur.execute(
        "INSERT INTO labs (subject_id, lab_num, status) VALUES (?, ?, 0)",
        (subject_id, next_num),
    )
    new_lab_id = cur.lastrowid
    ensure_base_step_for_lab(cur, new_lab_id, 0)
    conn.commit()
    conn.close()


def get_categorized_alerts():
    main_grp = get_setting("main_group", "")
    if not main_grp:
        return [], []
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT l.id, s.id, s.name, l.lab_num, l.deadline, l.planned_date, l.title
        FROM labs l
        JOIN subjects s ON s.id = l.subject_id
        WHERE s.group_name = ? AND s.is_tracked = 1 AND l.status < 3
    """, (main_grp,))
    rows = cur.fetchall()
    conn.close()

    deadline_alerts = []
    planned_alerts = []

    for l_id, s_id, s_name, l_num, dl, pl, title in rows:
        d_dl = days_until(dl)
        d_pl = days_until(pl)

        if d_dl is not None and d_dl <= 3:
            if d_dl < 0:
                msg = f"🔥 {s_name} (Лаба №{l_num}): дедлайн просрочен на {abs(d_dl)} дн.! ({format_date_ru(dl)})"
            elif d_dl == 0:
                msg = f"🔥 {s_name} (Лаба №{l_num}): дедлайн сегодня! ({format_date_ru(dl)})"
            elif d_dl == 1:
                msg = f"🔥 {s_name} (Лаба №{l_num}): дедлайн завтра! ({format_date_ru(dl)})"
            else:
                msg = f"🔥 {s_name} (Лаба №{l_num}): до дедлайна осталось {d_dl} дн. ({format_date_ru(dl)})"
            deadline_alerts.append({
                "key": f"dl_{l_id}_{dl}_{d_dl}",
                "type": "deadline",
                "days": d_dl,
                "lab_id": l_id,
                "subj_id": s_id,
                "subj_name": s_name,
                "lab_num": l_num,
                "text": msg,
            })

        if d_pl is not None and 0 <= d_pl <= 1:
            when_word = "сегодня" if d_pl == 0 else "завтра"
            msg = f"⏰ {s_name} (Лаба №{l_num}): плановая сдача {when_word} ({format_date_ru(pl)})"
            planned_alerts.append({
                "key": f"pl_{l_id}_{pl}_{d_pl}",
                "type": "planned",
                "days": d_pl,
                "lab_id": l_id,
                "subj_id": s_id,
                "subj_name": s_name,
                "lab_num": l_num,
                "text": msg,
            })

    deadline_alerts.sort(key=lambda x: (x["days"], x["subj_name"], x["lab_num"]))
    planned_alerts.sort(key=lambda x: (x["days"], x["subj_name"], x["lab_num"]))

    return deadline_alerts, planned_alerts


def compute_subject_lr_analytics() -> dict:
    sem_start = parse_date_safe(get_setting("semester_start", "2026-09-01")) or datetime.date(2026, 9, 1)
    sem_end = parse_date_safe(get_setting("semester_end", "2026-12-26")) or datetime.date(2026, 12, 26)
    main_grp = get_setting("main_group", "")
    if not main_grp:
        return {}
    main_sub = int(get_setting("main_subgroup", "1") or 0)

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT subject_id, day_of_week, weeks, lesson_date, subgroup, start_time, end_time, room
        FROM schedule
        WHERE group_name = ? AND lesson_type = 'ЛР'
        ORDER BY start_time ASC
    """, (main_grp,))
    lr_slots = cur.fetchall()
    conn.close()

    by_subj = {}
    for s_id, dow, weeks_str, l_date, subg, st_time, end_time, room in lr_slots:
        if main_sub in (1, 2) and subg not in (0, main_sub):
            continue
        weeks_set = {int(x) for x in weeks_str.split(",") if x.strip().isdigit()}
        by_subj.setdefault(s_id, []).append({
            "dow": dow,
            "weeks": weeks_set,
            "lesson_date": (l_date or "").strip(),
            "start_time": st_time,
            "end_time": end_time,
            "room": room,
            "subgroup": subg,
        })

    today = datetime.date.today()
    max_scan_date = max(sem_end, today + datetime.timedelta(days=60))
    analytics = {}

    for s_id, slots in by_subj.items():
        upcoming_list = []
        remaining_in_sem = 0
        cur_dt = today
        while cur_dt <= max_scan_date:
            wk = get_academic_week_number(cur_dt, sem_start)
            dow = cur_dt.weekday()
            iso_cur = cur_dt.isoformat()
            now_str = datetime.datetime.now().strftime("%H:%M")
            for sl in slots:
                is_match = (
                    (sl["lesson_date"] == iso_cur)
                    or (not sl["lesson_date"] and sl["dow"] == dow and wk in sl["weeks"])
                )
                if is_match and cur_dt == today and now_str > sl["end_time"]:
                    continue

                if is_match:
                    if cur_dt <= sem_end:
                        remaining_in_sem += 1
                    if len(upcoming_list) < 5:
                        upcoming_list.append({
                            "date": cur_dt,
                            "iso": iso_cur,
                            "week": wk,
                            "start_time": sl["start_time"],
                            "end_time": sl["end_time"],
                            "room": sl["room"],
                        })
            cur_dt += datetime.timedelta(days=1)

        analytics[s_id] = {
            "next_lr": upcoming_list[0] if upcoming_list else None,
            "upcoming_lrs": upcoming_list,
            "remaining_lr_count": remaining_in_sem,
        }

    return analytics


def get_custom_themes() -> list:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, name, url FROM custom_themes ORDER BY id DESC")
    rows = cur.fetchall()
    conn.close()
    return rows


def add_custom_theme(name: str, url: str) -> tuple[bool, str]:
    clean_name = name.strip()
    clean_url = url.strip()
    if not clean_name:
        return False, "Введите название темы!"
    clean_name = clean_name[0].upper() + clean_name[1:]
    if not clean_url.startswith(("http://", "https://")):
        return False, "Ссылка должна начинаться с http:// или https://"

    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO custom_themes (name, url) VALUES (?, ?)",
        (clean_name, clean_url),
    )
    conn.commit()
    conn.close()
    return True, clean_url


def delete_custom_theme(theme_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM custom_themes WHERE id = ?", (theme_id,))
    conn.commit()
    conn.close()

def export_db_to_downloads() -> tuple[bool, str]:
    from config import get_db_path
    db_path = get_db_path()
    if not os.path.exists(db_path):
        return False, "Файл базы данных не найден."

    dl_dir = "/storage/emulated/0/Download"
    if not os.path.exists(dl_dir):
        dl_dir = os.path.expanduser("~/Downloads")
        if not os.path.exists(dl_dir):
            dl_dir = os.path.dirname(db_path)

    dest_file = os.path.join(dl_dir, "study_tracker_backup.db")
    try:
        shutil.copyfile(db_path, dest_file)
        return True, "Файл labs_tracker_backup.db сохранён в Загрузки!"
    except Exception as ex:
        return False, f"Ошибка записи файла: {ex}"


def import_db_from_downloads() -> tuple[bool, str]:
    from config import get_db_path
    db_path = get_db_path()

    dl_dir = "/storage/emulated/0/Download"
    if not os.path.exists(dl_dir):
        dl_dir = os.path.expanduser("~/Downloads")
        if not os.path.exists(dl_dir):
            dl_dir = os.path.dirname(db_path)

    source_file = os.path.join(dl_dir, "study_tracker_backup.db")
    if not os.path.exists(source_file):
        return False, "Файл study_tracker_backup.db в папке Загрузки не найден!"

    try:
        shutil.copyfile(source_file, db_path)
        _SETTINGS_CACHE.clear()
        return True, "База успешно восстановлена из файла!"
    except Exception as ex:
        return False, f"Ошибка восстановления из файла: {ex}"

def export_db_to_json() -> str:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
    tables = [r[0] for r in cur.fetchall()]
    data = {}
    for t in tables:
        cur.execute(f"PRAGMA table_info({t})")
        cols = [c[1] for c in cur.fetchall()]
        cur.execute(f"SELECT * FROM {t}")
        rows = cur.fetchall()
        data[t] = {"cols": cols, "rows": rows}
    conn.close()

    raw_json = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    compressed = zlib.compress(raw_json.encode("utf-8"), level=9)
    return base64.b64encode(compressed).decode("utf-8")


def import_db_from_json(raw_input: str) -> tuple[bool, str]:
    s = raw_input.strip()
    if not s:
        return False, "Строка бэкапа пуста."

    try:
        if s.startswith("{"):
            data = json.loads(s)
        else:
            decompressed = zlib.decompress(base64.b64decode(s.encode("utf-8")))
            data = json.loads(decompressed.decode("utf-8"))
        if not isinstance(data, dict):
            return False, "Неверный формат данных бэкапа."
    except Exception as ex:
        return False, f"Ошибка расшифровки бэкапа: {ex}"

    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("PRAGMA foreign_keys = OFF")
        for table, content in data.items():
            cols = content.get("cols", [])
            rows = content.get("rows", [])
            if not cols:
                continue
            cur.execute(f"DELETE FROM {table}")
            placeholders = ", ".join(["?"] * len(cols))
            col_names = ", ".join([f'"{c}"' for c in cols])
            cur.executemany(f"INSERT OR REPLACE INTO {table} ({col_names}) VALUES ({placeholders})", rows)
        conn.commit()
        cur.execute("PRAGMA foreign_keys = ON")
    except Exception as ex:
        conn.rollback()
        conn.close()
        return False, f"Ошибка восстановления: {ex}"

    conn.close()
    _SETTINGS_CACHE.clear()
    return True, "Все данные успешно восстановлены!"

def search_all_data(query: str) -> tuple[list, list, list]:
    clean_q = query.strip()
    if not clean_q:
        return [], [], []

    q_pattern = f"%{clean_q.casefold()}%"
    main_grp = get_setting("main_group", "")
    view_grp = get_setting("view_group", main_grp)

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT l.id, s.id, s.name, l.lab_num, l.status, l.title, l.goal, l.description, l.comment
        FROM labs l
        JOIN subjects s ON s.id = l.subject_id
        WHERE s.group_name = ? AND s.is_tracked = 1
          AND (
              LOWER(s.name) LIKE ?
              OR LOWER(l.title) LIKE ?
              OR LOWER(l.goal) LIKE ?
              OR LOWER(l.description) LIKE ?
              OR LOWER(l.comment) LIKE ?
              OR CAST(l.lab_num AS TEXT) = ?
          )
        ORDER BY s.name ASC, l.lab_num ASC
    """, (main_grp, q_pattern, q_pattern, q_pattern, q_pattern, q_pattern, clean_q))
    found_labs = cur.fetchall()

    cur.execute("""
        SELECT sc.id, s.name, sc.day_of_week, sc.weeks, sc.lesson_date,
               sc.lesson_type, sc.start_time, sc.end_time, sc.room, sc.teacher, sc.note
        FROM schedule sc
        JOIN subjects s ON s.id = sc.subject_id
        WHERE sc.group_name = ?
          AND (
              LOWER(s.name) LIKE ?
              OR LOWER(sc.teacher) LIKE ?
              OR LOWER(sc.room) LIKE ?
              OR LOWER(sc.note) LIKE ?
          )
        ORDER BY sc.day_of_week ASC, sc.start_time ASC
    """, (view_grp, q_pattern, q_pattern, q_pattern, q_pattern))
    found_slots = cur.fetchall()

    cur.execute("""
        SELECT id, title, description, event_date, day_of_week, weeks,
               start_time, end_time, teacher, room
        FROM schedule_events
        WHERE group_name = ?
          AND (
              LOWER(title) LIKE ?
              OR LOWER(description) LIKE ?
              OR LOWER(teacher) LIKE ?
              OR LOWER(room) LIKE ?
          )
        ORDER BY day_of_week ASC, start_time ASC
    """, (view_grp, q_pattern, q_pattern, q_pattern, q_pattern))
    found_events = cur.fetchall()

    conn.close()
    return found_labs, found_slots, found_events

def reset_database_to_clean_slate():
    """Полная очистка всех данных приложения до чистой установки."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("PRAGMA foreign_keys = OFF")
    tables = [
        "subjects",
        "labs",
        "lab_steps",
        "schedule",
        "schedule_events",
        "saved_groups",
        "app_settings",
        "custom_themes",
    ]
    for t in tables:
        cur.execute(f"DELETE FROM {t}")
    conn.commit()
    cur.execute("PRAGMA foreign_keys = ON")
    conn.close()
    _SETTINGS_CACHE.clear()