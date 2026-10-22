import asyncio
import datetime
import flet as ft

from components import build_collapsible_alert_box, make_badged_icon
from config import (
    LESSON_TYPE_CONFIG,
    MONTHS_GENITIVE,
    STATUS_CONFIG,
    WEEKDAYS_FULL,
    days_until,
    format_date_ru,
    format_short_date_ru,
    get_academic_week_number,
    parse_date_safe,
    send_os_notification,
)
from database import (
    add_lab_to_subject_db,
    check_and_sync_all_saved_groups,
    compute_subject_lr_analytics,
    get_categorized_alerts,
    get_conn,
    get_saved_groups,
    get_setting,
    get_subjects_with_labs,
    get_summary_counts,
    init_db,
    set_setting,
)
from dialogs import (
    open_add_subject_dialog,
    open_edit_subject_dialog,
    open_event_dialog,
    open_lab_editor,
    open_my_group_dialog,
    open_notifications_dialog,
    open_onboarding_dialog,
    open_schedule_item_dialog,
    open_schedule_settings_dialog,
)


def main(page: ft.Page):
    page.title = "Трекер лаб"
    page.theme_mode = ft.ThemeMode.DARK
    page.window.width = 440
    page.window.height = 880
    page.padding = ft.Padding.only(top=10, left=10, right=4, bottom=4)

    page.theme = ft.Theme(
        scrollbar_theme=ft.ScrollbarTheme(
            thickness=3,
            radius=4,
            main_axis_margin=2,
            cross_axis_margin=1,
        )
    )

    if not hasattr(page, "clipboard"):
        try:
            setattr(page, "clipboard", None)
        except Exception:
            pass

    init_db()

    list_filter_state = {"mode": "unsubmitted"}
    schedule_filter_state = {"view": "all", "days_limit": 14}
    alerts_expanded_state = {"deadline": False, "planned": False}
    urgent_tiles_refs = []
    notified_alert_keys = set()

    toast_icon = ft.Icon(ft.Icons.NOTIFICATIONS_ACTIVE_ROUNDED, color="#FDE047", size=20)
    toast_text = ft.Text("", size=12, weight=ft.FontWeight.W_600, color="white", expand=True)
    toast_banner = ft.Container(
        visible=False,
        bgcolor="#DC2626",
        margin=ft.Margin.only(right=6),
        padding=ft.Padding.symmetric(horizontal=10, vertical=8),
        border_radius=10,
        border=ft.Border.all(1, "#FCA5A5"),
        shadow=ft.BoxShadow(spread_radius=1, blur_radius=10, color="#7F1D1D"),
        content=ft.Row(
            controls=[
                toast_icon,
                toast_text,
                ft.IconButton(
                    icon=ft.Icons.CLOSE_ROUNDED,
                    icon_size=18,
                    icon_color="white",
                    on_click=lambda e: hide_toast(),
                ),
            ],
            spacing=6,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
    )

    def hide_toast():
        toast_banner.visible = False
        page.update()

    async def _auto_hide_toast():
        await asyncio.sleep(6)
        if toast_banner.visible:
            toast_banner.visible = False
            try:
                page.update()
            except Exception:
                pass

    def show_in_app_toast(msg: str, is_urgent: bool = True):
        toast_text.value = msg
        if is_urgent:
            toast_banner.bgcolor = "#DC2626"
            toast_banner.border = ft.Border.all(1, "#FCA5A5")
            toast_icon.name = ft.Icons.LOCAL_FIRE_DEPARTMENT_ROUNDED
            toast_icon.color = "#FDE047"
        else:
            toast_banner.bgcolor = "#0369A1"
            toast_banner.border = ft.Border.all(1, "#38BDF8")
            toast_icon.name = ft.Icons.INFO_OUTLINE_ROUNDED
            toast_icon.color = "#7DD3FC"

        toast_banner.visible = True
        page.update()
        try:
            page.run_task(_auto_hide_toast)
        except Exception:
            pass

    content_area = ft.ListView(expand=True, spacing=10)
    content_wrapper = ft.Container(
        expand=True,
        padding=ft.Padding.only(right=8),
        content=content_area,
    )

    def check_and_trigger_notifications():
        deadline_alerts, planned_alerts = get_categorized_alerts()
        all_alerts = deadline_alerts + planned_alerts
        new_alerts = [a for a in all_alerts if a["key"] not in notified_alert_keys]

        if new_alerts:
            for a in new_alerts:
                notified_alert_keys.add(a["key"])
            new_dl = [a for a in new_alerts if a["type"] == "deadline"]
            new_pl = [a for a in new_alerts if a["type"] == "planned"]

            if new_dl:
                first_msg = new_dl[0]["text"]
                extra_cnt = len(new_alerts) - 1
                if extra_cnt > 0:
                    first_msg += f" (и ещё {extra_cnt} уведомл.)"
                show_in_app_toast(first_msg, is_urgent=True)
                send_os_notification("🔥 Горящий дедлайн!", first_msg)
            elif new_pl:
                first_msg = new_pl[0]["text"]
                extra_cnt = len(new_pl) - 1
                if extra_cnt > 0:
                    first_msg += f" (и ещё {extra_cnt} напомин.)"
                show_in_app_toast(first_msg, is_urgent=False)
                send_os_notification("ℹ️ Напоминание о плановой сдаче", first_msg)

        return deadline_alerts, planned_alerts

    # --- ВКЛАДКА 1: СВОДКА И ТАБЛИЦА ЛАБ ---
    def render_subjects_tab(deadline_alerts, planned_alerts):
        urgent_tiles_refs.clear()
        main_grp = get_setting("main_group", "")
        main_sub = int(get_setting("main_subgroup", "1") or 0)
        sub_txt = "обе подгр." if main_sub == 0 else f"{main_sub} подгр."

        if not main_grp:
            empty_welcome_card = ft.Card(
                content=ft.Container(
                    padding=20,
                    content=ft.Column(
                        controls=[
                            ft.Icon(ft.Icons.SCHOOL_ROUNDED, size=46, color="#38BDF8"),
                            ft.Text("Учебная группа не выбрана", weight=ft.FontWeight.BOLD, size=17),
                            ft.Text(
                                "Укажите свою учебную группу, чтобы загрузить расписание из ИИС БГУИР и сформировать список лабораторных работ:",
                                size=13,
                                color=ft.Colors.GREY_300,
                            ),
                            ft.FilledButton(
                                "Выбрать группу 🚀",
                                icon=ft.Icons.LOGIN_ROUNDED,
                                on_click=lambda e: open_onboarding_dialog(page, refresh_ui, show_in_app_toast),
                            ),
                        ],
                        spacing=10,
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                )
            )
            content_area.controls.append(empty_welcome_card)
            return

        counts = get_summary_counts()
        total = sum(counts.values())
        done_ratio = counts[3] / total if total > 0 else 0
        total_alerts = len(deadline_alerts) + len(planned_alerts)
        lr_analytics = compute_subject_lr_analytics()

        bell_color = "#FDE047" if deadline_alerts else ("#38BDF8" if planned_alerts else ft.Colors.GREY_400)

        bell_widget = ft.IconButton(
            icon=ft.Icons.NOTIFICATIONS_OUTLINED if total_alerts == 0 else ft.Icons.NOTIFICATIONS_ACTIVE_ROUNDED,
            icon_color=bell_color,
            icon_size=22,
            visual_density=ft.VisualDensity.COMPACT,
            tooltip=f"Уведомления ({total_alerts})",
            on_click=lambda e: open_notifications_dialog(page, refresh_ui),
        )

        summary_card = ft.Card(
            content=ft.Container(
                padding=12,
                content=ft.Column(
                    controls=[
                        ft.Row(
                            controls=[
                                ft.Row(
                                    controls=[
                                        ft.Text("📊 Прогресс семестра:", weight=ft.FontWeight.BOLD, size=16, color="#FFFFFF"),
                                        ft.Text(f"{counts[3]}/{total}", weight=ft.FontWeight.BOLD, size=16, color="#4ADE80"),
                                    ],
                                    spacing=6,
                                ),
                                bell_widget,
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        ft.Row(
                            controls=[
                                ft.Text(f"Моя группа: {main_grp} ({sub_txt})", size=12.5, color="#38BDF8", weight=ft.FontWeight.W_600, expand=True),
                                ft.Container(
                                    bgcolor="#1E293B",
                                    padding=ft.Padding.symmetric(horizontal=10, vertical=4),
                                    border_radius=6,
                                    border=ft.Border.all(1, "#38BDF8"),
                                    on_click=lambda e: open_my_group_dialog(page, refresh_ui),
                                    content=ft.Row(
                                        controls=[
                                            ft.Icon(ft.Icons.EDIT_OUTLINED, size=15, color="#7DD3FC"),
                                            ft.Text("Изменить", size=11.5, color="#7DD3FC", weight=ft.FontWeight.W_600),
                                        ],
                                        spacing=4,
                                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                    ),
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        ft.Row(
                            controls=[
                                ft.ProgressBar(value=done_ratio, color="#22C55E", bgcolor="#334155", height=8, expand=True),
                                ft.Text(f"{int(done_ratio * 100)}%", size=12, weight=ft.FontWeight.BOLD, color="#4ADE80"),
                            ],
                            spacing=8,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        ft.Row(
                            controls=[
                                ft.Container(expand=1, alignment=ft.Alignment.CENTER, bgcolor="#1E293B", border=ft.Border.all(1, "#EF4444"), padding=ft.Padding.symmetric(vertical=5), border_radius=8, content=ft.Text(f"🔴 {counts[0]}", size=12, color="#EF4444", weight=ft.FontWeight.W_600)),
                                ft.Container(expand=1, alignment=ft.Alignment.CENTER, bgcolor="#1E293B", border=ft.Border.all(1, "#F97316"), padding=ft.Padding.symmetric(vertical=5), border_radius=8, content=ft.Text(f"🟠 {counts[1]}", size=12, color="#F97316", weight=ft.FontWeight.W_600)),
                                ft.Container(expand=1, alignment=ft.Alignment.CENTER, bgcolor="#1E293B", border=ft.Border.all(1, "#EAB308"), padding=ft.Padding.symmetric(vertical=5), border_radius=8, content=ft.Text(f"🟡 {counts[2]}", size=12, color="#EAB308", weight=ft.FontWeight.W_600)),
                                ft.Container(expand=1, alignment=ft.Alignment.CENTER, bgcolor="#1E293B", border=ft.Border.all(1, "#22C55E"), padding=ft.Padding.symmetric(vertical=5), border_radius=8, content=ft.Text(f"🟢 {counts[3]}", size=12, color="#22C55E", weight=ft.FontWeight.W_600)),
                            ],
                            spacing=6,
                        ),
                    ],
                    spacing=9,
                ),
            ),
        )
        content_area.controls.append(summary_card)

        for s_id, s_name, labs in get_subjects_with_labs():
            done_in_subj = sum(1 for l in labs if l[2] == 3)
            unsubmitted_in_subj = len(labs) - done_in_subj
            lab_tiles = []

            for l_id, l_num, st, dl, pl_dt, comp_dt, title, goal, desc, comm, done_steps, total_steps in labs:
                cfg = STATUS_CONFIG[st]
                d_dl = days_until(dl) if st < 3 else None
                d_pl = days_until(pl_dt) if st < 3 else None

                is_urgent_dl = st < 3 and d_dl is not None and d_dl <= 3
                is_soon_pl = st < 3 and d_pl is not None and 0 <= d_pl <= 1
                has_meta = bool(comp_dt or title or goal or desc or comm) if st == 3 else bool(dl or pl_dt or title or goal or desc or comm)

                tooltip_lines = [f"Лаба №{l_num}: {cfg['label']}"]
                if title:
                    tooltip_lines.append(f"Тема: {title}")
                if total_steps > 0:
                    tooltip_lines.append(f"Этапы: {done_steps}/{total_steps}")
                if st == 3 and comp_dt:
                    tooltip_lines.append(f"✅ Дата сдачи: {format_date_ru(comp_dt)}")
                elif st < 3:
                    if dl:
                        tooltip_lines.append(f"📅 Дедлайн: {format_date_ru(dl)}")
                    if pl_dt:
                        tooltip_lines.append(f"⏳ Планирую сдать: {format_date_ru(pl_dt)}")
                if comm:
                    tooltip_lines.append(f"💬 Заметка: {comm}")

                if is_urgent_dl:
                    tile_border = ft.Border.all(3, "#FDE047")
                    tile_shadow = ft.BoxShadow(spread_radius=2, blur_radius=12, color="#FF4500")
                elif is_soon_pl:
                    tile_border = ft.Border.all(2, "#38BDF8")
                    tile_shadow = ft.BoxShadow(spread_radius=1, blur_radius=8, color="#0284C7")
                elif has_meta:
                    tile_border = ft.Border.all(2, "#FFFFFF")
                    tile_shadow = None
                else:
                    tile_border = None
                    tile_shadow = None

                inner_box = ft.Container(
                    width=44,
                    height=44,
                    bgcolor=cfg["color"],
                    border_radius=8,
                    alignment=ft.Alignment.CENTER,
                    border=tile_border,
                    shadow=tile_shadow,
                    animate=ft.Animation(500, ft.AnimationCurve.EASE_IN_OUT),
                    content=ft.Column(
                        controls=[
                            ft.Text(str(l_num), color=cfg["text_color"], weight=ft.FontWeight.BOLD, size=16),
                            ft.Text(f"{done_steps}/{total_steps}", color=cfg["text_color"], size=10.5) if total_steps > 0 else ft.Container(),
                        ],
                        alignment=ft.MainAxisAlignment.CENTER,
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=0,
                    ),
                )

                if is_urgent_dl:
                    urgent_tiles_refs.append(inner_box)

                badge_emoji = "🔥" if is_urgent_dl else ("⏰" if is_soon_pl else None)
                tile_widget = (
                    ft.Stack(
                        controls=[inner_box, ft.Container(right=-2, top=-4, content=ft.Text(badge_emoji, size=12))],
                        width=46,
                        height=46,
                    )
                    if badge_emoji
                    else inner_box
                )

                lab_tiles.append(
                    ft.GestureDetector(
                        content=ft.Container(content=tile_widget, tooltip="\n".join(tooltip_lines)),
                        on_tap=lambda e, lid=l_id, sid=s_id, sn=s_name: open_lab_editor(page, refresh_ui, lid, sid, sn),
                    )
                )

            lab_tiles.append(
                ft.Container(
                    width=44,
                    height=44,
                    bgcolor="#1E293B",
                    border_radius=8,
                    border=ft.Border.all(1, "#475569"),
                    alignment=ft.Alignment.CENTER,
                    tooltip="Добавить лабу к предмету",
                    content=ft.Icon(ft.Icons.ADD, color=ft.Colors.GREY_300, size=24),
                    on_click=lambda e, sid=s_id: (add_lab_to_subject_db(sid), refresh_ui()),
                )
            )

            card_rows = [
                ft.Row([
                    ft.Row([
                        ft.Text(
                            s_name + (" ✓" if (len(labs) > 0 and unsubmitted_in_subj == 0) else ""),
                            size=18,
                            weight=ft.FontWeight.BOLD,
                            color="#4ADE80" if (len(labs) > 0 and unsubmitted_in_subj == 0) else "#F8FAFC",
                        ),
                        ft.IconButton(
                            icon=ft.Icons.EDIT_OUTLINED,
                            icon_size=18,
                            visual_density=ft.VisualDensity.COMPACT,
                            icon_color=ft.Colors.GREY_400,
                            tooltip="Переименовать или убрать предмет из лаб",
                            on_click=lambda e, sid=s_id, sn=s_name: open_edit_subject_dialog(page, refresh_ui, sid, sn),
                        ),
                    ], spacing=2, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                    ft.Text(f"{done_in_subj}/{len(labs)} сдано", size=12, color=ft.Colors.GREY_400),
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ft.Row(lab_tiles, wrap=True, spacing=8, run_spacing=8),
            ]

            subj_sched = lr_analytics.get(s_id)
            if unsubmitted_in_subj > 0 and subj_sched:
                next_lr = subj_sched.get("next_lr")
                rem_lrs = subj_sched.get("remaining_lr_count", 0)
                sched_lines = []
                if next_lr:
                    room_str = f", ауд. {next_lr['room']}" if next_lr["room"] else ""
                    sched_lines.append(
                        ft.Text(
                            f"🎓 Ближайшая защита (ЛР): {format_short_date_ru(next_lr['date'])} ({next_lr['start_time']}{room_str})",
                            size=11,
                            color="#38BDF8",
                            weight=ft.FontWeight.W_600,
                        )
                    )
                if rem_lrs > 0:
                    pace = round(unsubmitted_in_subj / rem_lrs, 1)
                    pace_color = "#4ADE80" if pace <= 1.0 else ("#FBBF24" if pace <= 1.5 else "#FCA5A5")
                    warn_icon = "📊" if pace <= 1.0 else "⚠️"
                    sched_lines.append(
                        ft.Text(
                            f"{warn_icon} До конца семестра ({sub_txt}): {rem_lrs} пар ЛР на {unsubmitted_in_subj} лаб (темп: {pace} лабы/пару)",
                            size=11,
                            color=pace_color,
                        )
                    )
                if sched_lines:
                    card_rows.append(ft.Divider(height=4, color="#334155"))
                    card_rows.extend(sched_lines)

            content_area.controls.append(
                ft.Card(content=ft.Container(padding=12, content=ft.Column(card_rows, spacing=6)))
            )

    # --- ВКЛАДКА 2: ДЕДЛАЙНЫ И ОЧЕРЕДЬ СДАЧИ ---
    def render_deadlines_tab(deadline_alerts, planned_alerts):
        urgent_tiles_refs.clear()
        main_grp = get_setting("main_group", "")

        if not main_grp:
            empty_deadlines_card = ft.Card(
                content=ft.Container(
                    padding=20,
                    content=ft.Column(
                        controls=[
                            ft.Icon(ft.Icons.EVENT_BUSY_ROUNDED, size=46, color=ft.Colors.GREY_400),
                            ft.Text("Группа не выбрана", weight=ft.FontWeight.BOLD, size=17),
                            ft.Text("Выберите свою учебную группу в Таблице лаб, чтобы отслеживать дедлайны.", size=13, color=ft.Colors.GREY_400),
                        ],
                        spacing=8,
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                )
            )
            content_area.controls.append(empty_deadlines_card)
            return

        counts = get_summary_counts()
        unsubmitted_cnt = counts[0] + counts[1] + counts[2]
        submitted_cnt = counts[3]
        total_cnt = unsubmitted_cnt + submitted_cnt
        lr_analytics = compute_subject_lr_analytics()
        cur_mode = list_filter_state["mode"]

        def make_filter_chip(mode_key: str, label: str):
            is_active = cur_mode == mode_key
            return ft.Container(
                bgcolor="#2563EB" if is_active else "#1E293B",
                padding=ft.Padding.symmetric(horizontal=10, vertical=7),
                border_radius=8,
                border=ft.Border.all(1, "#38BDF8" if is_active else "#334155"),
                content=ft.Text(
                    label,
                    size=12,
                    weight=ft.FontWeight.BOLD if is_active else ft.FontWeight.NORMAL,
                    color="white" if is_active else ft.Colors.GREY_300,
                ),
                on_click=lambda e, m=mode_key: (list_filter_state.update({"mode": m}), refresh_ui()),
            )

        content_area.controls.append(
            ft.Row(
                controls=[
                    make_filter_chip("unsubmitted", f"Несданные ({unsubmitted_cnt})"),
                    make_filter_chip("submitted", f"Сданные ({submitted_cnt})"),
                    make_filter_chip("all", f"Все лабы ({total_cnt})"),
                ],
                spacing=6,
                wrap=True,
            )
        )

        if cur_mode != "submitted":
            if deadline_alerts:
                content_area.controls.append(
                    build_collapsible_alert_box(
                        alerts_expanded_state, "deadline", "Горящие дедлайны",
                        deadline_alerts, "#EF4444", "#451A1A", "#FDE047",
                        ft.Icons.LOCAL_FIRE_DEPARTMENT_ROUNDED, refresh_ui,
                        lambda a: open_lab_editor(page, refresh_ui, a["lab_id"], a["subj_id"], a["subj_name"]),
                    )
                )
            if planned_alerts:
                content_area.controls.append(
                    build_collapsible_alert_box(
                        alerts_expanded_state, "planned", "Плановые сдачи",
                        planned_alerts, "#38BDF8", "#0C2D48", "#7DD3FC",
                        ft.Icons.INFO_OUTLINE_ROUNDED, refresh_ui,
                        lambda a: open_lab_editor(page, refresh_ui, a["lab_id"], a["subj_id"], a["subj_name"]),
                    )
                )

        conn = get_conn()
        cur = conn.cursor()
        today_iso = datetime.date.today().isoformat()

        base_select = """
            SELECT l.id, s.id, s.name, l.lab_num, l.status, l.deadline, l.planned_date, l.completed_date,
                   l.title, l.goal, l.description, l.comment,
                   (SELECT COUNT(*) FROM lab_steps ls WHERE ls.lab_id = l.id AND ls.is_done = 1),
                   (SELECT COUNT(*) FROM lab_steps ls WHERE ls.lab_id = l.id)
            FROM labs l
            JOIN subjects s ON s.id = l.subject_id
            WHERE s.group_name = ? AND s.is_tracked = 1
        """

        if cur_mode == "unsubmitted":
            header_title = f"Очередь сдачи ({main_grp})"
            cur.execute(
                base_select + """
                  AND l.status < 3
                ORDER BY
                    CASE WHEN l.deadline != '' THEN 0 ELSE 1 END ASC,
                    l.deadline ASC,
                    CASE
                        WHEN l.planned_date != '' AND l.planned_date >= ? THEN 0
                        WHEN l.planned_date != '' AND l.planned_date < ? THEN 1
                        ELSE 2
                    END ASC,
                    CASE WHEN l.planned_date >= ? THEN l.planned_date END ASC,
                    CASE WHEN l.planned_date < ? THEN l.planned_date END DESC,
                    l.status DESC,
                    s.name ASC,
                    l.lab_num ASC
                """,
                (main_grp, today_iso, today_iso, today_iso, today_iso),
            )
        elif cur_mode == "submitted":
            header_title = f"История сданных лабораторных ({main_grp})"
            cur.execute(
                base_select + """
                  AND l.status = 3
                ORDER BY
                    CASE WHEN l.completed_date = '' THEN 1 ELSE 0 END ASC,
                    l.completed_date DESC,
                    s.name ASC,
                    l.lab_num DESC
                """,
                (main_grp,),
            )
        else:
            header_title = f"Все лабораторные ({main_grp})"
            cur.execute(
                base_select + """
                ORDER BY
                    CASE WHEN l.status < 3 THEN 0 ELSE 1 END ASC,
                    CASE WHEN l.status < 3 AND l.deadline != '' THEN 0 ELSE 1 END ASC,
                    CASE WHEN l.status < 3 THEN l.deadline END ASC,
                    CASE
                        WHEN l.status < 3 AND l.planned_date != '' AND l.planned_date >= ? THEN 0
                        WHEN l.status < 3 AND l.planned_date != '' AND l.planned_date < ? THEN 1
                        ELSE 2
                    END ASC,
                    CASE WHEN l.status < 3 AND l.planned_date >= ? THEN l.planned_date END ASC,
                    CASE WHEN l.status < 3 AND l.planned_date < ? THEN l.planned_date END DESC,
                    CASE WHEN l.status < 3 THEN -l.status END ASC,
                    CASE WHEN l.status = 3 AND l.completed_date != '' THEN 0 ELSE 1 END ASC,
                    CASE WHEN l.status = 3 THEN l.completed_date END DESC,
                    s.name ASC,
                    l.lab_num ASC
                """,
                (main_grp, today_iso, today_iso, today_iso, today_iso),
            )

        labs_list = cur.fetchall()
        conn.close()

        content_area.controls.append(ft.Text(header_title, size=16, weight=ft.FontWeight.BOLD))

        for l_id, s_id, s_name, l_num, st, dl, pl_dt, comp_dt, title, goal, desc, comm, done_steps, total_steps in labs_list:
            cfg = STATUS_CONFIG[st]
            d_dl = days_until(dl) if st < 3 else None
            d_pl = days_until(pl_dt) if st < 3 else None

            is_urgent_dl = st < 3 and d_dl is not None and d_dl <= 3
            is_soon_pl = st < 3 and d_pl is not None and 0 <= d_pl <= 1

            fire_prefix = "🔥 " if is_urgent_dl else ("⏰ " if is_soon_pl else "")
            header_text = f"{fire_prefix}{s_name} — Лаба №{l_num}" + (f": {title}" if title else "")

            sub_items = [ft.Text(f"{cfg['label']} • Этапы: {done_steps}/{total_steps}", size=12, color=cfg["color"])]

            if st == 3:
                comp_str = f"✅ Дата сдачи: {format_date_ru(comp_dt)}" if comp_dt else "✅ Сдано (дата не указана)"
                sub_items.append(ft.Text(comp_str, size=12, color="#4ADE80", weight=ft.FontWeight.W_600))
            else:
                if dl:
                    if is_urgent_dl:
                        dl_str = (
                            f"🔥 Дедлайн просрочен на {abs(d_dl)} дн.! ({format_date_ru(dl)})" if d_dl < 0
                            else (f"🔥 Дедлайн сегодня! ({format_date_ru(dl)})" if d_dl == 0 else f"🔥 Дедлайн через {d_dl} дн.! ({format_date_ru(dl)})")
                        )
                        sub_items.append(ft.Text(dl_str, size=12, color="#FCA5A5", weight=ft.FontWeight.BOLD))
                    elif d_dl is not None:
                        sub_items.append(ft.Text(f"📅 Дедлайн: {format_date_ru(dl)} (осталось {d_dl} дн.)", size=12))
                else:
                    sub_items.append(ft.Text("📅 Дедлайн не назначен", size=12, color=ft.Colors.GREY_400))

                if pl_dt:
                    if is_soon_pl:
                        when_w = "сегодня" if d_pl == 0 else "завтра"
                        sub_items.append(ft.Text(f"⏰ Планирую сдать {when_w}: {format_date_ru(pl_dt)}", size=12, color="#38BDF8", weight=ft.FontWeight.BOLD))
                    else:
                        sub_items.append(ft.Text(f"⏳ Планирую сдать: {format_date_ru(pl_dt)}", size=12, color="#93C5FD"))

                subj_sched = lr_analytics.get(s_id)
                if subj_sched and subj_sched.get("next_lr"):
                    nlr = subj_sched["next_lr"]
                    rm_txt = f", ауд. {nlr['room']}" if nlr["room"] else ""
                    sub_items.append(ft.Text(f"🎓 Ближ. пара ЛР: {format_short_date_ru(nlr['date'])} ({nlr['start_time']}{rm_txt})", size=11, color="#4ADE80"))

            if goal:
                sub_items.append(ft.Text(f"🎯 Цель: {goal}", size=12, color=ft.Colors.GREY_200))
            if desc:
                sub_items.append(ft.Text(f"📝 Описание: {desc}", size=12, color=ft.Colors.GREY_300))
            if comm:
                sub_items.append(ft.Text(f"💬 {comm}", size=12, italic=True, color=ft.Colors.GREY_400))

            card_border = ft.Border.all(1.5, "#EF4444") if is_urgent_dl else (ft.Border.all(1.5, "#38BDF8") if is_soon_pl else None)

            content_area.controls.append(
                ft.Card(
                    content=ft.Container(
                        border=card_border,
                        border_radius=12,
                        content=ft.ListTile(
                            leading=ft.Container(
                                width=38, height=38, bgcolor=cfg["color"], border_radius=8,
                                alignment=ft.Alignment.CENTER,
                                content=ft.Text(str(l_num), color=cfg["text_color"], weight=ft.FontWeight.BOLD),
                            ),
                            title=ft.Text(header_text, weight=ft.FontWeight.BOLD, size=14),
                            subtitle=ft.Column(sub_items, spacing=3),
                            on_click=lambda e, lid=l_id, sid=s_id, sn=s_name: open_lab_editor(page, refresh_ui, lid, sid, sn),
                        ),
                    )
                )
            )

    # --- ВКЛАДКА 3: ПРОСМОТР РАСПИСАНИЯ ---
    def render_schedule_tab():
        urgent_tiles_refs.clear()
        today = datetime.date.today()
        sem_start = parse_date_safe(get_setting("semester_start", "2026-09-01")) or datetime.date(2026, 9, 1)
        sem_end = parse_date_safe(get_setting("semester_end", "2026-12-26")) or datetime.date(2026, 12, 26)
        main_grp = get_setting("main_group", "")
        view_grp = get_setting("view_group", main_grp)
        view_sub = int(get_setting("view_subgroup", "0") or 0)
        cur_week_num = get_academic_week_number(today, sem_start)

        saved_group_names = [r[0] for r in get_saved_groups()]
        if view_grp not in saved_group_names and saved_group_names:
            view_grp = saved_group_names[0]
            set_setting("view_group", view_grp)

        if not view_grp:
            empty_schedule_card = ft.Card(
                content=ft.Container(
                    padding=20,
                    content=ft.Column(
                        controls=[
                            ft.Icon(ft.Icons.CALENDAR_MONTH_ROUNDED, size=46, color=ft.Colors.GREY_400),
                            ft.Text("Расписание не загружено", weight=ft.FontWeight.BOLD, size=17),
                            ft.Text("Загрузите расписание вашей учебной группы из ИИС БГУИР:", size=13, color=ft.Colors.GREY_400),
                            ft.FilledButton(
                                "Загрузить расписание 🌐",
                                icon=ft.Icons.DOWNLOAD_ROUNDED,
                                on_click=lambda e: open_onboarding_dialog(page, refresh_ui, show_in_app_toast),
                            ),
                        ],
                        spacing=8,
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                )
            )
            content_area.controls.append(empty_schedule_card)
            return

        group_switch_chips = []
        for g_name in saved_group_names:
            is_active_g = g_name == view_grp
            group_switch_chips.append(
                ft.Container(
                    bgcolor="#2563EB" if is_active_g else "#1E293B",
                    padding=ft.Padding.symmetric(horizontal=10, vertical=5),
                    border_radius=6,
                    border=ft.Border.all(1, "#38BDF8" if is_active_g else "#334155"),
                    content=ft.Text(
                        f"👥 {g_name}",
                        size=11,
                        weight=ft.FontWeight.BOLD if is_active_g else ft.FontWeight.NORMAL,
                        color="white" if is_active_g else ft.Colors.GREY_300,
                    ),
                    on_click=lambda e, gn=g_name: (set_setting("view_group", gn), refresh_ui(check_alerts=False)),
                )
            )

        sub_filter_chips = []
        for s_key, s_lbl in [("0", "Обе подгруппы"), ("1", "1-я подгруппа"), ("2", "2-я подгруппа")]:
            is_act_s = str(view_sub) == s_key
            sub_filter_chips.append(
                ft.Container(
                    expand=1,
                    alignment=ft.Alignment.CENTER,
                    bgcolor="#0C4A6E" if is_act_s else "#1E293B",
                    padding=ft.Padding.symmetric(horizontal=6, vertical=5),
                    border_radius=6,
                    border=ft.Border.all(1, "#38BDF8" if is_act_s else "#334155"),
                    content=ft.Text(
                        s_lbl,
                        size=11,
                        no_wrap=True,
                        weight=ft.FontWeight.BOLD if is_act_s else ft.FontWeight.NORMAL,
                        color="#7DD3FC" if is_act_s else ft.Colors.GREY_400,
                    ),
                    on_click=lambda e, sk=s_key: (set_setting("view_subgroup", sk), refresh_ui(check_alerts=False)),
                )
            )

        top_info_card = ft.Card(
            content=ft.Container(
                padding=12,
                content=ft.Column(
                    controls=[
                        ft.Row(
                            controls=[
                                ft.Column(
                                    controls=[
                                        ft.Text(f"🎓 Идёт {cur_week_num}-я учебная неделя", weight=ft.FontWeight.BOLD, size=15, color="#38BDF8"),
                                        ft.Text(f"Сегодня: {WEEKDAYS_FULL[today.weekday()]}, {format_date_ru(today.isoformat())}", size=11, color=ft.Colors.GREY_300),
                                    ],
                                    spacing=2,
                                    expand=True,
                                ),
                                ft.IconButton(
                                    icon=ft.Icons.SETTINGS_OUTLINED,
                                    icon_color=ft.Colors.GREY_300,
                                    tooltip="Управление группами и настройками",
                                    on_click=lambda e: open_schedule_settings_dialog(page, refresh_ui, show_in_app_toast),
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                        ft.Row(group_switch_chips, wrap=True, spacing=6, run_spacing=6),
                        ft.Divider(height=4, color="#334155"),
                        ft.Row(sub_filter_chips, spacing=6),
                        ft.Row(
                            controls=[
                                ft.OutlinedButton(
                                    "➕ Пара",
                                    icon=ft.Icons.SCHOOL_ROUNDED,
                                    expand=True,
                                    on_click=lambda e: open_schedule_item_dialog(page, refresh_ui, show_in_app_toast, None),
                                ),
                                ft.OutlinedButton(
                                    "📌 Событие",
                                    icon=ft.Icons.EVENT_AVAILABLE_ROUNDED,
                                    expand=True,
                                    on_click=lambda e: open_event_dialog(page, refresh_ui, None),
                                ),
                            ],
                            spacing=6,
                        ),
                    ],
                    spacing=8,
                ),
            )
        )
        content_area.controls.append(top_info_card)

        cur_view = schedule_filter_state["view"]

        def make_week_chip(key_val: str, txt: str, is_current_wk: bool = False):
            is_sel = cur_view == key_val
            return ft.Container(
                bgcolor="#2563EB" if is_sel else "#1E293B",
                padding=ft.Padding.symmetric(horizontal=10, vertical=7),
                border_radius=8,
                border=ft.Border.all(1.5, "#38BDF8" if is_current_wk else ("#3B82F6" if is_sel else "#334155")),
                content=ft.Text(
                    txt,
                    size=11,
                    weight=ft.FontWeight.BOLD if (is_sel or is_current_wk) else ft.FontWeight.NORMAL,
                    color="white" if is_sel else ("#7DD3FC" if is_current_wk else ft.Colors.GREY_300),
                ),
                on_click=lambda e, kv=key_val: (schedule_filter_state.update({"view": kv}), refresh_ui(check_alerts=False)),
            )

        content_area.controls.append(
            ft.Row(
                controls=[
                    make_week_chip("all", "Текущее"),
                    make_week_chip("1", "1 нед." + (" •" if cur_week_num == 1 else ""), cur_week_num == 1),
                    make_week_chip("2", "2 нед." + (" •" if cur_week_num == 2 else ""), cur_week_num == 2),
                    make_week_chip("3", "3 нед." + (" •" if cur_week_num == 3 else ""), cur_week_num == 3),
                    make_week_chip("4", "4 нед." + (" •" if cur_week_num == 4 else ""), cur_week_num == 4),
                ],
                spacing=6,
                wrap=True,
            )
        )

        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT sc.id, sc.subject_id, s.name, sc.day_of_week, sc.weeks, sc.lesson_date, sc.subgroup,
                   sc.lesson_type, sc.start_time, sc.end_time, sc.room, sc.teacher, sc.note,
                   s.is_tracked,
                   (SELECT COUNT(*) FROM labs l WHERE l.subject_id = s.id AND l.status < 3),
                   (SELECT COUNT(*) FROM labs l WHERE l.subject_id = s.id AND l.status = 2)
            FROM schedule sc
            JOIN subjects s ON s.id = sc.subject_id
            WHERE sc.group_name = ?
            ORDER BY sc.day_of_week ASC, sc.start_time ASC
            """,
            (view_grp,),
        )
        all_slots = cur.fetchall()

        cur.execute(
            """
            SELECT id, title, description, event_date, day_of_week, weeks,
                   start_time, end_time, teacher, room
            FROM schedule_events
            WHERE group_name = ?
            ORDER BY start_time ASC
            """,
            (view_grp,),
        )
        all_events = cur.fetchall()
        conn.close()

        filtered_slots = [
            r for r in all_slots
            if not (view_sub in (1, 2) and r[6] not in (0, view_sub))
        ]

        is_viewing_my_group = (view_grp == main_grp)

        def build_lesson_row(slot_row):
            (
                sc_id, s_id, s_name, dow, weeks_str, l_date, subg,
                l_type, st_time, end_time, room, teacher, note, is_tracked, unsub_cnt, ready_cnt
            ) = slot_row
            t_cfg = LESSON_TYPE_CONFIG.get(l_type, LESSON_TYPE_CONFIG["ЛР"])
            subg_txt = f" • {subg} подгр." if subg in (1, 2) else ""
            room_txt = f"📍 ауд. {room}" if room else "📍 ауд. не указ."
            when_info = f"Дата: {format_date_ru(l_date)}" if l_date else f"Нед: {weeks_str}"

            meta_badges = [ft.Text(f"{room_txt} • {when_info}{subg_txt}", size=11, color=ft.Colors.GREY_300)]
            if teacher:
                meta_badges.append(ft.Text(f"👤 {teacher}", size=11, color=ft.Colors.GREY_300))
            if note:
                meta_badges.append(ft.Text(f"📝 {note}", size=11, italic=True, color=ft.Colors.GREY_400))

            if is_viewing_my_group and l_type == "ЛР" and is_tracked == 1:
                if ready_cnt > 0:
                    meta_badges.append(ft.Text(f"🟡 Готово к защите на паре: {ready_cnt} лаб.", size=11, color="#FDE047", weight=ft.FontWeight.BOLD))
                elif unsub_cnt > 0:
                    meta_badges.append(ft.Text(f"🔴 Не сдано по предмету: {unsub_cnt} лаб.", size=11, color="#FCA5A5"))
                else:
                    meta_badges.append(ft.Text("🟢 Все лабы по предмету сданы!", size=11, color="#4ADE80"))

            return ft.Container(
                bgcolor="#1E293B",
                padding=10,
                border_radius=8,
                border=ft.Border.all(1, "#334155"),
                on_click=lambda e, sid=sc_id: open_schedule_item_dialog(page, refresh_ui, show_in_app_toast, sid),
                content=ft.Row(
                    controls=[
                        ft.Column(
                            controls=[
                                ft.Text(st_time, weight=ft.FontWeight.BOLD, size=15, color="white"),
                                ft.Text(end_time, size=11, color=ft.Colors.GREY_400),
                            ],
                            spacing=1,
                            width=46,
                            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        ft.Container(width=3, height=48, bgcolor=t_cfg["color"], border_radius=2),
                        ft.Column(
                            controls=[
                                ft.Row(
                                    controls=[
                                        ft.Container(
                                            bgcolor=t_cfg["bg"],
                                            padding=ft.Padding.symmetric(horizontal=6, vertical=2),
                                            border_radius=4,
                                            border=ft.Border.all(1, t_cfg["color"]),
                                            content=ft.Text(l_type, size=10, weight=ft.FontWeight.BOLD, color=t_cfg["color"]),
                                        ),
                                        ft.Text(s_name, weight=ft.FontWeight.BOLD, size=14, expand=True),
                                    ],
                                    spacing=6,
                                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                ),
                                *meta_badges,
                            ],
                            spacing=2,
                            expand=True,
                        ),
                    ],
                    spacing=8,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
            )

        def build_event_row(ev_row):
            ev_id, ev_title, ev_desc, ev_date, ev_dow, ev_weeks, st_time, end_time, teacher, room = ev_row
            t_cfg = LESSON_TYPE_CONFIG["СОБ"]

            clean_desc = ev_desc or ""
            date_range_str = ""
            if "[" in clean_desc and clean_desc.endswith("]"):
                idx_b = clean_desc.rfind("[")
                date_range_str = f" ({clean_desc[idx_b + 1:-1]})"
                clean_desc = clean_desc[:idx_b].strip()

            display_title = ev_title or "Событие"
            if len(display_title) > 22:
                if not clean_desc:
                    clean_desc = display_title
                display_title = "Событие"

            room_txt = f"📍 ауд. {room}" if room else "📍 ауд. не указ."
            when_txt = f"Дата: {format_date_ru(ev_date)}" if ev_date else f"Нед: {ev_weeks or '1,2,3,4'}{date_range_str}"

            meta_lines = [
                ft.Text(f"{room_txt} • {when_txt}", size=11, color=ft.Colors.GREY_300),
            ]
            if teacher:
                meta_lines.append(ft.Text(f"👤 {teacher}", size=11, color=ft.Colors.GREY_300))
            if clean_desc and clean_desc != display_title:
                meta_lines.append(ft.Text(f"📝 {clean_desc}", size=11, color=ft.Colors.GREY_400))

            return ft.Container(
                bgcolor="#1E293B",
                padding=10,
                border_radius=8,
                border=ft.Border.all(1, "#475569"),
                on_click=lambda e, eid=ev_id: open_event_dialog(page, refresh_ui, eid),
                content=ft.Row(
                    controls=[
                        ft.Column(
                            controls=[
                                ft.Text(st_time, weight=ft.FontWeight.BOLD, size=15, color="white"),
                                ft.Text(end_time, size=11, color=ft.Colors.GREY_400),
                            ],
                            spacing=1,
                            width=46,
                            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        ft.Container(width=3, height=48, bgcolor=t_cfg["color"], border_radius=2),
                        ft.Column(
                            controls=[
                                ft.Row(
                                    controls=[
                                        ft.Container(
                                            bgcolor=t_cfg["bg"],
                                            padding=ft.Padding.symmetric(horizontal=6, vertical=2),
                                            border_radius=4,
                                            border=ft.Border.all(1, t_cfg["color"]),
                                            content=ft.Text("СОБ", size=10, weight=ft.FontWeight.BOLD, color=t_cfg["color"]),
                                        ),
                                        ft.Text(display_title, weight=ft.FontWeight.BOLD, size=14, expand=True, no_wrap=True),
                                    ],
                                    spacing=6,
                                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                ),
                                *meta_lines,
                            ],
                            spacing=2,
                            expand=True,
                        ),
                    ],
                    spacing=8,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
            )

        def merge_and_sort_by_time(day_lessons: list, day_events: list) -> list:
            combined = []
            for r in day_lessons:
                st_norm = r[8] if len(r[8]) == 5 else ("0" + r[8])
                combined.append((st_norm, 0, build_lesson_row(r)))
            for ev in day_events:
                st_norm = ev[6] if len(ev[6]) == 5 else ("0" + ev[6])
                combined.append((st_norm, 1, build_event_row(ev)))
            combined.sort(key=lambda item: (item[0], item[1]))
            return [item[2] for item in combined]

        prepared_slots = [
            (r, {x.strip() for x in r[4].split(",") if x.strip()})
            for r in filtered_slots
        ]
        prepared_events = [
            (ev, {x.strip() for x in (ev[5] or "1,2,3,4").split(",") if x.strip()})
            for ev in all_events
        ]

        if cur_view == "all":
            max_sem_days = max(14, (sem_end - today).days + 1)
            limit_days = min(max_sem_days, schedule_filter_state.get("days_limit", 14))
            has_any_rendered = False

            for offset in range(limit_days):
                dt_target = today + datetime.timedelta(days=offset)
                if dt_target.weekday() == 6:
                    continue
                wk_str = str(get_academic_week_number(dt_target, sem_start))
                dow_t = dt_target.weekday()
                iso_t = dt_target.isoformat()

                day_lessons = [
                    r for r, wks in prepared_slots
                    if (r[5] == iso_t) or (not r[5] and r[3] == dow_t and wk_str in wks)
                ]
                day_events = [
                    ev for ev, wks in prepared_events
                    if (ev[3] == iso_t) or (not ev[3] and ev[4] == dow_t and wk_str in wks)
                ]

                if not day_lessons and not day_events and offset > 1:
                    continue

                has_any_rendered = True
                day_header = f"{dt_target.day} {MONTHS_GENITIVE[dt_target.month]}, {WEEKDAYS_FULL[dow_t]} • {wk_str} нед."

                day_controls = [
                    ft.Row(
                        controls=[
                            ft.Text(day_header, weight=ft.FontWeight.BOLD, size=14, color="#38BDF8" if offset == 0 else "white", expand=True),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    )
                ]
                if not day_lessons and not day_events:
                    day_controls.append(ft.Text("Нет пар и событий 🎉", size=12, color=ft.Colors.GREY_400, italic=True))
                else:
                    day_controls.extend(merge_and_sort_by_time(day_lessons, day_events))

                content_area.controls.append(
                    ft.Card(
                        content=ft.Container(
                            padding=12,
                            border=ft.Border.all(1.5, "#38BDF8") if offset == 0 else None,
                            border_radius=12,
                            content=ft.Column(day_controls, spacing=8),
                        )
                    )
                )

            if limit_days < max_sem_days:
                content_area.controls.append(
                    ft.Row(
                        controls=[
                            ft.OutlinedButton(
                                "Показать ещё 2 недели ▾",
                                expand=True,
                                on_click=lambda e: (
                                    schedule_filter_state.update({"days_limit": limit_days + 14}),
                                    refresh_ui(check_alerts=False),
                                ),
                            ),
                            ft.TextButton(
                                "Весь семестр",
                                on_click=lambda e: (
                                    schedule_filter_state.update({"days_limit": max_sem_days}),
                                    refresh_ui(check_alerts=False),
                                ),
                            ),
                        ],
                        spacing=8,
                    )
                )

            if not has_any_rendered:
                content_area.controls.append(
                    ft.Text(f"Для группы {view_grp} нет запланированных пар.", size=13, color=ft.Colors.GREY_400, italic=True)
                )
        else:
            target_wk = cur_view
            has_any_in_week = False
            for dow_idx in range(6):
                day_lessons = []
                for r, wks in prepared_slots:
                    if r[3] != dow_idx:
                        continue
                    if not r[5] and target_wk in wks:
                        day_lessons.append(r)
                    elif r[5]:
                        dt_l = parse_date_safe(r[5])
                        if dt_l and str(get_academic_week_number(dt_l, sem_start)) == target_wk:
                            day_lessons.append(r)

                day_events = []
                for ev, wks in prepared_events:
                    if ev[4] != dow_idx:
                        continue
                    if not ev[3] and target_wk in wks:
                        day_events.append(ev)
                    elif ev[3]:
                        dt_e = parse_date_safe(ev[3])
                        if dt_e and str(get_academic_week_number(dt_e, sem_start)) == target_wk:
                            day_events.append(ev)

                if not day_lessons and not day_events:
                    continue
                has_any_in_week = True
                is_today_day = int(target_wk) == cur_week_num and today.weekday() == dow_idx

                day_controls = [
                    ft.Row(
                        controls=[
                            ft.Text(WEEKDAYS_FULL[dow_idx] + (" (Сегодня)" if is_today_day else ""), weight=ft.FontWeight.BOLD, size=15, color="#38BDF8" if is_today_day else "white"),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    )
                ]
                day_controls.extend(merge_and_sort_by_time(day_lessons, day_events))

                content_area.controls.append(
                    ft.Card(
                        content=ft.Container(
                            padding=12,
                            border=ft.Border.all(1.5, "#38BDF8") if is_today_day else None,
                            border_radius=12,
                            content=ft.Column(day_controls, spacing=8),
                        )
                    )
                )

            if not has_any_in_week:
                content_area.controls.append(
                    ft.Text(f"Для группы {view_grp} на {target_wk}-й неделе нет пар или событий.", size=13, color=ft.Colors.GREY_400, italic=True)
                )

    def refresh_ui(check_alerts: bool = True):
        if check_alerts or nav_bar.selected_index in (0, 1):
            deadline_alerts, planned_alerts = check_and_trigger_notifications()
            alert_count = len(deadline_alerts) + len(planned_alerts)
            badge_color = "#EF4444" if deadline_alerts else "#0284C7"
            nav_bar.destinations[1].icon = make_badged_icon(ft.Icons.EVENT_NOTE_ROUNDED, alert_count, badge_color)
            nav_bar.destinations[1].selected_icon = make_badged_icon(ft.Icons.EVENT_NOTE_ROUNDED, alert_count, badge_color)
        else:
            deadline_alerts, planned_alerts = [], []

        fab.tooltip = "Добавить пару в расписание" if nav_bar.selected_index == 2 else "Добавить предмет"

        content_area.controls.clear()
        if nav_bar.selected_index == 0:
            render_subjects_tab(deadline_alerts, planned_alerts)
        elif nav_bar.selected_index == 1:
            render_deadlines_tab(deadline_alerts, planned_alerts)
        else:
            render_schedule_tab()
        page.update()

    async def pulse_urgent_tiles_loop():
        state_on = False
        while True:
            await asyncio.sleep(0.75)
            if nav_bar.selected_index == 0 and urgent_tiles_refs:
                state_on = not state_on
                for tile in list(urgent_tiles_refs):
                    if state_on:
                        tile.border = ft.Border.all(3, "#FDE047")
                        tile.shadow = ft.BoxShadow(spread_radius=2, blur_radius=14, color="#FF4500")
                    else:
                        tile.border = ft.Border.all(2, "#FFFFFF")
                        tile.shadow = ft.BoxShadow(spread_radius=0, blur_radius=3, color="#EF4444")
                try:
                    page.update()
                except Exception:
                    break

    def on_fab_click(e):
        if nav_bar.selected_index == 2:
            open_schedule_item_dialog(page, refresh_ui, show_in_app_toast, None)
        else:
            open_add_subject_dialog(page, refresh_ui)

    nav_bar = ft.NavigationBar(
        selected_index=0,
        on_change=lambda e: refresh_ui(),
        destinations=[
            ft.NavigationBarDestination(icon=ft.Icons.GRID_VIEW_ROUNDED, label="Таблица лаб"),
            ft.NavigationBarDestination(icon=ft.Icons.EVENT_NOTE_ROUNDED, label="Дедлайны"),
            ft.NavigationBarDestination(icon=ft.Icons.CALENDAR_MONTH_ROUNDED, label="Расписание"),
        ],
    )

    fab = ft.FloatingActionButton(icon=ft.Icons.ADD, tooltip="Добавить предмет", on_click=on_fab_click)
    page.floating_action_button = fab
    page.navigation_bar = nav_bar

    page.add(
        ft.SafeArea(
            expand=True,
            content=ft.Column(controls=[toast_banner, content_wrapper], expand=True, spacing=8),
        )
    )
    refresh_ui()
    page.run_task(pulse_urgent_tiles_loop)

    if get_setting("is_onboarded", "0") == "0":
        open_onboarding_dialog(page, refresh_ui, show_in_app_toast)

    async def background_schedule_update_check():
        await asyncio.sleep(2.0)
        if get_setting("is_onboarded", "0") == "1":
            updated = await asyncio.to_thread(check_and_sync_all_saved_groups)
            if updated:
                grps_str = ", ".join(updated)
                show_in_app_toast(
                    f"🔄 Расписание в ИИС изменилось и было автоматически обновлено ({grps_str})!",
                    is_urgent=False,
                )
                refresh_ui(check_alerts=False)

    page.run_task(background_schedule_update_check)


if __name__ == "__main__":
    ft.run(main)