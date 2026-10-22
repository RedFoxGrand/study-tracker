import datetime

import flet as ft
from components import create_date_picker_block
from config import (
    BASE_DEFENSE_TITLE,
    BELL_PRESETS,
    WEEKDAYS_FULL,
    format_date_ru,
    format_short_date_ru,
)
from database import (
    NON_LAB_SUBJECTS,
    cleanup_orphan_and_non_lab_subjects,
    compute_subject_lr_analytics,
    delete_saved_group_schedule,
    ensure_base_step_for_lab,
    ensure_group_labs_initialized,
    get_categorized_alerts,
    get_conn,
    get_dropdown_subjects_for_schedule,
    get_saved_groups,
    get_setting,
    import_schedule_from_bsuir_api,
    renumber_subject_labs,
    set_setting,
)

CUSTOM_SUBJ_KEY = "__custom_new_subject__"

SCROLL_RIGHT_GAP = 10
FIELD_SPACING = 8


def make_dialog_header(page: ft.Page, title_text: str, color: str = "white") -> ft.Row:
    return ft.Row(
        controls=[
            ft.Text(title_text, weight=ft.FontWeight.BOLD, size=16, color=color, expand=True),
            ft.IconButton(
                icon=ft.Icons.CLOSE_ROUNDED,
                icon_size=24,
                visual_density=ft.VisualDensity.COMPACT,
                icon_color=ft.Colors.GREY_400,
                tooltip="Закрыть",
                on_click=lambda e: page.pop_dialog(),
            ),
        ],
        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )


def make_scrollable_form(controls_list: list, scrollable: bool = False) -> ft.Column:
    right_pad = SCROLL_RIGHT_GAP if scrollable else 0
    padded_items = [ft.Container(height=2)]
    for ctrl in controls_list:
        padded_items.append(
            ft.Container(
                padding=ft.Padding.only(right=right_pad),
                content=ctrl,
            )
        )
    padded_items.append(ft.Container(height=2))
    return ft.Column(
        controls=padded_items,
        tight=True,
        scroll=ft.ScrollMode.AUTO if scrollable else None,
        spacing=FIELD_SPACING,
    )


def create_compact_week_selector(page: ft.Page, initial_weeks: set):
    selected = {str(w) for w in initial_weeks if str(w) in ("1", "2", "3", "4")}
    if not selected:
        selected = {"1", "2", "3", "4"}

    chips_row = ft.Row(spacing=6)

    def toggle_wk(w_str: str):
        if w_str in selected:
            selected.remove(w_str)
        else:
            selected.add(w_str)
        render_chips()
        page.update()

    def render_chips():
        chips_row.controls.clear()
        for w in ("1", "2", "3", "4"):
            is_on = w in selected
            chips_row.controls.append(
                ft.Container(
                    expand=1,
                    height=32,
                    bgcolor="#2563EB" if is_on else "#1E293B",
                    border_radius=6,
                    border=ft.Border.all(1, "#38BDF8" if is_on else "#334155"),
                    alignment=ft.Alignment.CENTER,
                    on_click=lambda e, wk=w: toggle_wk(wk),
                    content=ft.Text(
                        f"{w} нед.",
                        size=12,
                        weight=ft.FontWeight.BOLD if is_on else ft.FontWeight.NORMAL,
                        color="white" if is_on else ft.Colors.GREY_400,
                    ),
                )
            )

    render_chips()
    return chips_row, lambda: [w for w in ("1", "2", "3", "4") if w in selected]


def open_lab_editor(page: ft.Page, refresh_ui, lab_id: int, subj_id: int, subj_name: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT lab_num, status, deadline, planned_date, completed_date,
               title, goal, description, comment
        FROM labs WHERE id = ?
        """,
        (lab_id,),
    )
    row = cur.fetchone()
    if not row:
        conn.close()
        return
    (
        lab_num, cur_status, cur_deadline, cur_planned, cur_completed,
        cur_title, cur_goal, cur_desc, cur_comment
    ) = row

    ensure_base_step_for_lab(cur, lab_id, cur_status)
    conn.commit()

    cur.execute(
        "SELECT title, is_done FROM lab_steps WHERE lab_id = ? ORDER BY step_order ASC, id ASC",
        (lab_id,),
    )
    raw_steps = cur.fetchall()
    conn.close()

    steps_data = []
    for s_title, s_done in raw_steps:
        if s_title == BASE_DEFENSE_TITLE and not any(x.get("locked") for x in steps_data):
            steps_data.insert(0, {"title": BASE_DEFENSE_TITLE, "is_done": bool(s_done), "locked": True})
        else:
            steps_data.append({"title": s_title, "is_done": bool(s_done), "locked": False})

    if not steps_data or not steps_data[0].get("locked"):
        steps_data.insert(0, {"title": BASE_DEFENSE_TITLE, "is_done": (cur_status == 3), "locked": True})

    status_dropdown = ft.Dropdown(
        label="Статус работы",
        value=str(cur_status),
        options=[
            ft.DropdownOption(key="0", text="🔴 Не сделано"),
            ft.DropdownOption(key="1", text="🟠 Частично сделано"),
            ft.DropdownOption(key="2", text="🟡 Сделано, но не сдано"),
            ft.DropdownOption(key="3", text="🟢 Сдано"),
        ],
    )

    title_input = ft.TextField(
        label="Название лабы",
        value=cur_title or "",
        capitalization=ft.TextCapitalization.SENTENCES,
        dense=True,
        text_size=13,
    )
    goal_input = ft.TextField(
        label="Цель работы",
        value=cur_goal or "",
        capitalization=ft.TextCapitalization.SENTENCES,
        multiline=True,
        min_lines=1,
        max_lines=3,
        dense=True,
        text_size=13,
    )
    desc_input = ft.TextField(
        label="Краткое описание работы",
        value=cur_desc or "",
        capitalization=ft.TextCapitalization.SENTENCES,
        multiline=True,
        min_lines=1,
        max_lines=4,
        dense=True,
        text_size=13,
    )
    comment_input = ft.TextField(
        label="Заметки к защите",
        value=cur_comment or "",
        capitalization=ft.TextCapitalization.SENTENCES,
        multiline=True,
        min_lines=1,
        max_lines=3,
        dense=True,
        text_size=13,
    )

    deadline_ui, get_deadline_val, _ = create_date_picker_block(page, "Дедлайн", "📅", cur_deadline)
    planned_ui, get_planned_val, set_planned_val = create_date_picker_block(page, "Планирую сдать", "⏳", cur_planned)
    completed_ui, get_completed_val, set_completed_val = create_date_picker_block(page, "Дата сдачи", "✅", cur_completed)

    lr_info = compute_subject_lr_analytics().get(subj_id, {})
    upcoming_lrs = lr_info.get("upcoming_lrs", [])
    quick_lr_chips_box = ft.Container(visible=False)

    if upcoming_lrs:
        chips = []
        for slot in upcoming_lrs[:3]:
            dt_obj = slot["date"]
            chip_label = f"⚡ Пара ЛР: {format_short_date_ru(dt_obj)} ({slot['start_time']})"
            chips.append(
                ft.Container(
                    bgcolor="#0C4A6E",
                    padding=ft.Padding.symmetric(horizontal=8, vertical=4),
                    border_radius=6,
                    border=ft.Border.all(1, "#38BDF8"),
                    content=ft.Text(chip_label, size=11, color="#7DD3FC", weight=ft.FontWeight.W_600),
                    on_click=lambda e, iso_d=slot["iso"]: (set_planned_val(iso_d), page.update()),
                )
            )
        quick_lr_chips_box.content = ft.Column(
            controls=[
                ft.Text("Выбрать дату ближайшей пары ЛР по расписанию:", size=11, color=ft.Colors.GREY_400),
                ft.Row(chips, wrap=True, spacing=6, run_spacing=6),
            ],
            spacing=4,
        )

    dates_group_box = ft.Column(
        controls=[deadline_ui, planned_ui, quick_lr_chips_box, completed_ui],
        spacing=0,
        tight=True,
    )

    def sync_date_blocks_visibility():
        is_submitted = int(status_dropdown.value) == 3
        deadline_ui.visible = not is_submitted
        planned_ui.visible = not is_submitted
        quick_lr_chips_box.visible = (not is_submitted) and bool(upcoming_lrs)
        completed_ui.visible = is_submitted
        if is_submitted and not get_completed_val():
            set_completed_val(datetime.date.today().isoformat())

    sync_date_blocks_visibility()

    steps_column = ft.Column(spacing=4)
    reorder_mode = [False]  # Флаг режима сортировки

    # Автоматическое превращение первой буквы в заглавную при вводе
    def auto_cap(e):
        val = e.control.value or ""
        if len(val) == 1 and val[0].islower():
            e.control.value = val[0].upper()
            e.control.update()

    new_step_input = ft.TextField(
        hint_text="Добавить этап...",
        capitalization=ft.TextCapitalization.SENTENCES,
        on_change=auto_cap,
        expand=True,
        dense=True,
        text_size=13,
    )

    def recalculate_status_from_steps(triggered_by_defense: bool = False):
        defense_done = steps_data[0]["is_done"]
        custom_steps = steps_data[1:]

        if defense_done:
            status_dropdown.value = "3"
            if triggered_by_defense:
                for s in custom_steps:
                    s["is_done"] = True
        else:
            if len(custom_steps) > 0:
                done_custom = sum(1 for s in custom_steps if s["is_done"])
                if done_custom == len(custom_steps):
                    status_dropdown.value = "2"
                elif done_custom > 0:
                    status_dropdown.value = "1"
                else:
                    status_dropdown.value = "0"
            else:
                status_dropdown.value = "0"

        sync_date_blocks_visibility()

    def move_custom_step(idx: int, delta: int):
        target_idx = idx + delta
        if 1 <= target_idx < len(steps_data):
            steps_data[idx], steps_data[target_idx] = steps_data[target_idx], steps_data[idx]
            recalculate_status_from_steps()
            render_steps_list()
            page.update()

    def toggle_reorder_mode(e):
        reorder_mode[0] = not reorder_mode[0]
        reorder_btn.text = "✓ Готово" if reorder_mode[0] else "↕️ Порядок"
        reorder_btn.style = ft.ButtonStyle(color="#4ADE80" if reorder_mode[0] else "#38BDF8")
        add_step_row.visible = not reorder_mode[0]
        render_steps_list()
        page.update()

    reorder_btn = ft.TextButton(
        "↕️ Порядок",
        style=ft.ButtonStyle(color="#38BDF8"),
        on_click=toggle_reorder_mode,
    )

    def render_steps_list():
        steps_column.controls.clear()
        reorder_btn.visible = len(steps_data) > 2

        # --- РЕЖИМ 1: СОРТИРОВКА (Стрелки плотно рядом) ---
        if reorder_mode[0]:
            steps_column.controls.append(
                ft.Container(
                    height=42,
                    bgcolor="#1E293B",
                    padding=ft.Padding.only(left=10, right=10),
                    border_radius=8,
                    border=ft.Border.all(1, "#475569"),
                    content=ft.Row(
                        controls=[
                            ft.Text("1. Защита у преподавателя", weight=ft.FontWeight.BOLD, size=13, color="#94A3B8", expand=True),
                            ft.Container(
                                width=56,
                                alignment=ft.Alignment.CENTER_RIGHT,
                                content=ft.Icon(ft.Icons.LOCK_OUTLINE_ROUNDED, size=17, color="#64748B"),
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                )
            )
            for idx in range(1, len(steps_data)):
                step = steps_data[idx]
                steps_column.controls.append(
                    ft.Container(
                        height=42,
                        bgcolor="#1E293B",
                        padding=ft.Padding.only(left=10, right=6),
                        border_radius=8,
                        border=ft.Border.all(1, "#38BDF8"),
                        content=ft.Row(
                            controls=[
                                ft.Text(f"{idx + 1}. {step['title']}", weight=ft.FontWeight.W_600, size=13, expand=True),
                                ft.Row(
                                    controls=[
                                        ft.IconButton(
                                            icon=ft.Icons.ARROW_UPWARD_ROUNDED,
                                            icon_size=18,
                                            width=26,
                                            padding=0,
                                            visual_density=ft.VisualDensity.COMPACT,
                                            disabled=(idx == 1),
                                            tooltip="Выше",
                                            on_click=lambda e, i=idx: move_custom_step(i, -1),
                                        ),
                                        ft.IconButton(
                                            icon=ft.Icons.ARROW_DOWNWARD_ROUNDED,
                                            icon_size=18,
                                            width=26,
                                            padding=0,
                                            visual_density=ft.VisualDensity.COMPACT,
                                            disabled=(idx == len(steps_data) - 1),
                                            tooltip="Ниже",
                                            on_click=lambda e, i=idx: move_custom_step(i, 1),
                                        ),
                                    ],
                                    spacing=2,
                                    alignment=ft.MainAxisAlignment.END,
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                    )
                )
            return

        # --- РЕЖИМ 2: ОБЫЧНЫЙ (Замочек и крестики идеально симметричны) ---
        for idx, step in enumerate(steps_data):
            is_locked = step.get("locked", False)

            def on_check_change(e, i=idx):
                steps_data[i]["is_done"] = bool(e.control.value)
                if i > 0 and not steps_data[i]["is_done"] and steps_data[0]["is_done"]:
                    steps_data[0]["is_done"] = False
                recalculate_status_from_steps(triggered_by_defense=(i == 0))
                render_steps_list()
                page.update()

            if is_locked:
                step_row = ft.Container(
                    height=42,
                    bgcolor="#1E293B",
                    padding=ft.Padding.only(left=6, right=6),
                    border_radius=8,
                    border=ft.Border.all(1, "#22C55E" if step["is_done"] else "#475569"),
                    content=ft.Row(
                        controls=[
                            ft.Checkbox(value=step["is_done"], on_change=on_check_change),
                            ft.Text(f"{step['title']}", weight=ft.FontWeight.BOLD, size=13, expand=True),
                            ft.Container(
                                width=28,
                                height=28,
                                alignment=ft.Alignment.CENTER,
                                content=ft.Icon(ft.Icons.LOCK_OUTLINE_ROUNDED, size=17, color="#64748B"),
                            ),
                        ],
                        spacing=4,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                )
            else:
                def on_title_change(e, i=idx):
                    val = e.control.value or ""
                    if len(val) == 1 and val[0].islower():
                        val = val[0].upper()
                        e.control.value = val
                        e.control.update()
                    steps_data[i]["title"] = val

                def on_delete_step(e, i=idx):
                    steps_data.pop(i)
                    recalculate_status_from_steps()
                    render_steps_list()
                    page.update()

                step_row = ft.Container(
                    height=42,
                    bgcolor="#1E293B",
                    padding=ft.Padding.only(left=6, right=6),
                    border_radius=8,
                    border=ft.Border.all(1, "#22C55E" if step["is_done"] else "#334155"),
                    content=ft.Row(
                        controls=[
                            ft.Checkbox(value=step["is_done"], on_change=on_check_change),
                            ft.TextField(
                                value=step["title"],
                                on_change=on_title_change,
                                capitalization=ft.TextCapitalization.SENTENCES,
                                expand=True,
                                dense=True,
                                text_size=13,
                                border=ft.InputBorder.NONE,
                                content_padding=ft.Padding.symmetric(horizontal=4, vertical=0),
                            ),
                            ft.Container(
                                width=28,
                                height=28,
                                alignment=ft.Alignment.CENTER,
                                content=ft.IconButton(
                                    icon=ft.Icons.CLOSE_ROUNDED,
                                    icon_size=18,
                                    padding=0,
                                    visual_density=ft.VisualDensity.COMPACT,
                                    icon_color=ft.Colors.RED_300,
                                    tooltip="Удалить этап",
                                    on_click=on_delete_step,
                                ),
                            ),
                        ],
                        spacing=4,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                )
            steps_column.controls.append(step_row)

    def add_custom_step(e):
        txt = new_step_input.value.strip()
        if not txt:
            return
        txt = txt[0].upper() + txt[1:]
        steps_data.append({"title": txt, "is_done": False, "locked": False})
        new_step_input.value = ""
        if steps_data[0]["is_done"]:
            steps_data[0]["is_done"] = False
        recalculate_status_from_steps()
        render_steps_list()
        page.update()

    new_step_input.on_submit = add_custom_step

    add_step_row = ft.Row(
        controls=[
            new_step_input,
            ft.IconButton(
                icon=ft.Icons.ADD_CIRCLE_ROUNDED,
                icon_color="#22C55E",
                visual_density=ft.VisualDensity.COMPACT,
                tooltip="Добавить этап",
                on_click=add_custom_step,
            ),
        ],
        spacing=4,
    )

    checklist_header = ft.Row(
        controls=[
            ft.Text("Чек-лист этапов:", weight=ft.FontWeight.BOLD, size=15),
            reorder_btn,
        ],
        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )

    def on_manual_status_select(e):
        st_val = int(status_dropdown.value)
        if st_val == 3:
            for s in steps_data:
                s["is_done"] = True
        elif st_val == 2:
            steps_data[0]["is_done"] = False
            for s in steps_data[1:]:
                s["is_done"] = True
        elif st_val == 1:
            steps_data[0]["is_done"] = False
        elif st_val == 0:
            for s in steps_data:
                s["is_done"] = False
        sync_date_blocks_visibility()
        render_steps_list()
        page.update()

    status_dropdown.on_select = on_manual_status_select
    render_steps_list()

    def save_changes(e):
        final_status = int(status_dropdown.value)
        if final_status == 3:
            comp_date = get_completed_val() or datetime.date.today().isoformat()
            dl_val = get_deadline_val()
            pl_val = get_planned_val()
        else:
            comp_date = ""
            dl_val = get_deadline_val()
            pl_val = get_planned_val()

        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE labs
            SET status = ?, deadline = ?, planned_date = ?, completed_date = ?,
                title = ?, goal = ?, description = ?, comment = ?
            WHERE id = ?
            """,
            (
                final_status,
                dl_val,
                pl_val,
                comp_date,
                title_input.value.strip(),
                goal_input.value.strip(),
                desc_input.value.strip(),
                comment_input.value.strip(),
                lab_id,
            ),
        )
        cur.execute("DELETE FROM lab_steps WHERE lab_id = ?", (lab_id,))
        for idx, st_item in enumerate(steps_data):
            t_val = BASE_DEFENSE_TITLE if st_item.get("locked") else (st_item["title"].strip() or f"Этап {idx}")
            cur.execute(
                "INSERT INTO lab_steps (lab_id, step_order, title, is_done) VALUES (?, ?, ?, ?)",
                (lab_id, idx, t_val, 1 if st_item["is_done"] else 0),
            )
        conn.commit()
        conn.close()
        page.pop_dialog()
        refresh_ui()

    def perform_delete_lab(e):
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("DELETE FROM labs WHERE id = ?", (lab_id,))
        renumber_subject_labs(conn, subj_id)
        conn.commit()
        conn.close()
        page.pop_dialog()
        refresh_ui()

    form_content = make_scrollable_form([
        status_dropdown,
        title_input,
        goal_input,
        desc_input,
        ft.Divider(height=4),
        checklist_header,
        steps_column,
        add_step_row,
        ft.Divider(height=4),
        dates_group_box,
        comment_input,
    ], scrollable=True)

    default_lab_actions = [
        ft.TextButton("Удалить лабу", on_click=lambda e: ask_delete_lab_confirmation(e), style=ft.ButtonStyle(color=ft.Colors.RED_400)),
        ft.FilledButton("Сохранить", on_click=save_changes),
    ]

    def ask_delete_lab_confirmation(e):
        dialog.title = make_dialog_header(page, "⚠️ Удалить лабу?", color="#EF4444")
        dialog.content = make_scrollable_form([
            ft.Text(
                f"Вы действительно хотите удалить «{subj_name} — Лаба №{lab_num}»?\n\n"
                f"Все этапы и заметки этой лабы будут удалены, а номера оставшихся лаб автоматически сдвинутся.",
                size=13,
            )
        ], scrollable=False)
        dialog.actions = [
            ft.TextButton("Назад", on_click=restore_editor_view),
            ft.FilledButton(
                "Да, удалить",
                on_click=perform_delete_lab,
                style=ft.ButtonStyle(bgcolor="#EF4444", color="white"),
            ),
        ]
        page.update()

    def restore_editor_view(e):
        dialog.title = make_dialog_header(page, f"{subj_name} — Лаба №{lab_num}")
        dialog.content = form_content
        dialog.actions = default_lab_actions
        page.update()

    dialog = ft.AlertDialog(
        inset_padding=ft.Padding.symmetric(horizontal=14, vertical=16),
        title_padding=ft.Padding.only(left=16, right=8, top=10, bottom=0),
        content_padding=ft.Padding.only(left=16, right=6, top=4, bottom=6),
        title=make_dialog_header(page, f"{subj_name} — Лаба №{lab_num}"),
        content=form_content,
        actions=default_lab_actions,
        actions_alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
    )
    page.show_dialog(dialog)


def open_add_subject_dialog(page: ft.Page, refresh_ui):
    main_grp = get_setting("main_group", "")
    if not main_grp:
        open_onboarding_dialog(page, refresh_ui, lambda msg, is_urgent=False: None)
        return

    name_field = ft.TextField(
        label="Название предмета",
        capitalization=ft.TextCapitalization.SENTENCES,
        autofocus=True,
        dense=True,
    )
    count_field = ft.TextField(label="Количество лаб", value="5", keyboard_type=ft.KeyboardType.NUMBER, dense=True)
    error_banner = ft.Text("", color="#EF4444", size=13, weight=ft.FontWeight.W_600, visible=False)

    def create_subject(ev):
        name = name_field.value.strip()
        if not name:
            error_banner.value = "⚠️ Введите название предмета!"
            error_banner.visible = True
            page.update()
            return
        if not count_field.value.strip().isdigit():
            error_banner.value = "⚠️ Количество лаб должно быть целым числом!"
            error_banner.visible = True
            page.update()
            return

        num_labs = int(count_field.value.strip())
        low_target = name.casefold()

        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT id, name, is_tracked FROM subjects WHERE group_name = ?", (main_grp,))
        existing = None
        for s_id, s_name, is_tr in cur.fetchall():
            if s_name.strip().casefold() == low_target:
                existing = (s_id, s_name, is_tr)
                break

        if existing:
            s_id, s_name, is_tr = existing
            if is_tr == 1:
                conn.close()
                error_banner.value = f"⚠️ Предмет «{s_name}» уже отслеживается в группе {main_grp}!"
                error_banner.visible = True
                page.update()
                return
            else:
                cur.execute("UPDATE subjects SET name = ?, is_tracked = 1 WHERE id = ?", (name, s_id))
                cur.execute("DELETE FROM labs WHERE subject_id = ?", (s_id,))
                for i in range(1, num_labs + 1):
                    cur.execute("INSERT INTO labs (subject_id, lab_num, status) VALUES (?, ?, 0)", (s_id, i))
                    ensure_base_step_for_lab(cur, cur.lastrowid, 0)
        else:
            cur.execute(
                "INSERT INTO subjects (group_name, name, is_tracked, from_api) VALUES (?, ?, 1, 0)",
                (main_grp, name),
            )
            subj_id = cur.lastrowid
            for i in range(1, num_labs + 1):
                cur.execute("INSERT INTO labs (subject_id, lab_num, status) VALUES (?, ?, 0)", (subj_id, i))
                ensure_base_step_for_lab(cur, cur.lastrowid, 0)

        conn.commit()
        conn.close()
        page.pop_dialog()
        refresh_ui()

    dlg = ft.AlertDialog(
        inset_padding=ft.Padding.symmetric(horizontal=16, vertical=20),
        title_padding=ft.Padding.only(left=16, right=8, top=10, bottom=0),
        content_padding=ft.Padding.only(left=16, right=6, top=4, bottom=6),
        title=make_dialog_header(page, f"Добавить предмет ({main_grp})"),
        content=make_scrollable_form([name_field, count_field, error_banner], scrollable=False),
        actions=[ft.FilledButton("Создать", on_click=create_subject)],
        actions_alignment=ft.MainAxisAlignment.END,
    )
    page.show_dialog(dlg)


def open_edit_subject_dialog(page: ft.Page, refresh_ui, subj_id: int, current_name: str):
    main_grp = get_setting("main_group", "")
    name_field = ft.TextField(
        label="Новое название предмета",
        value=current_name,
        capitalization=ft.TextCapitalization.SENTENCES,
        autofocus=True,
        dense=True,
    )
    error_banner = ft.Text("", color="#EF4444", size=13, weight=ft.FontWeight.W_600, visible=False)
    edit_content = make_scrollable_form([name_field, error_banner], scrollable=False)

    def save_subject_name(ev):
        new_name = name_field.value.strip()
        if not new_name:
            error_banner.value = "⚠️ Название предмета не может быть пустым!"
            error_banner.visible = True
            page.update()
            return

        low_new = new_name.casefold()
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            "SELECT id, name, is_tracked FROM subjects WHERE group_name = ? AND id != ?",
            (main_grp, subj_id),
        )
        conflict = None
        for other_id, other_name, other_tr in cur.fetchall():
            if other_name.strip().casefold() == low_new:
                conflict = (other_id, other_name, other_tr)
                break

        if conflict:
            other_id, other_name, other_tr = conflict
            if other_tr == 1:
                conn.close()
                error_banner.value = f"⚠️ Предмет «{other_name}» уже есть в списке!"
                error_banner.visible = True
                page.update()
                return
            else:
                cur.execute("UPDATE schedule SET subject_id = ? WHERE subject_id = ?", (subj_id, other_id))
                cur.execute("DELETE FROM subjects WHERE id = ?", (other_id,))

        cur.execute("UPDATE subjects SET name = ? WHERE id = ?", (new_name, subj_id))
        conn.commit()
        conn.close()
        page.pop_dialog()
        refresh_ui()

    def perform_untrack_subject(ev):
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("DELETE FROM labs WHERE subject_id = ?", (subj_id,))
        cur.execute("UPDATE subjects SET is_tracked = 0 WHERE id = ?", (subj_id,))
        cleanup_orphan_and_non_lab_subjects(cur)
        conn.commit()
        conn.close()
        page.pop_dialog()
        refresh_ui()

    default_subj_actions = [
        ft.TextButton("Удалить из лаб", on_click=lambda ev: ask_delete_subject_confirmation(ev), style=ft.ButtonStyle(color=ft.Colors.RED_400)),
        ft.FilledButton("Сохранить", on_click=save_subject_name),
    ]

    def ask_delete_subject_confirmation(ev):
        dlg.title = make_dialog_header(page, "⚠️ Убрать предмет из лаб?", color="#EF4444")
        dlg.content = make_scrollable_form([
            ft.Text(
                f"Вы действительно хотите удалить предмет «{current_name}» и все его лабы из таблицы лаб?\n\n"
                f"При обновлении расписания он больше не будет автоматически добавляться в таблицу лаб.",
                size=13,
            )
        ], scrollable=False)
        dlg.actions = [
            ft.TextButton("Назад", on_click=restore_subject_edit_view),
            ft.FilledButton(
                "Да, удалить",
                on_click=perform_untrack_subject,
                style=ft.ButtonStyle(bgcolor="#EF4444", color="white"),
            ),
        ]
        page.update()

    def restore_subject_edit_view(ev):
        dlg.title = make_dialog_header(page, "Редактировать предмет")
        dlg.content = edit_content
        dlg.actions = default_subj_actions
        page.update()

    dlg = ft.AlertDialog(
        inset_padding=ft.Padding.symmetric(horizontal=16, vertical=20),
        title_padding=ft.Padding.only(left=16, right=8, top=10, bottom=0),
        content_padding=ft.Padding.only(left=16, right=6, top=4, bottom=6),
        title=make_dialog_header(page, "Редактировать предмет"),
        content=edit_content,
        actions=default_subj_actions,
        actions_alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
    )
    page.show_dialog(dlg)


def open_schedule_item_dialog(page: ft.Page, refresh_ui, show_toast, sched_id=None):
    view_grp = get_setting("view_group", "")
    main_grp = get_setting("main_group", "")
    if not view_grp:
        show_toast("Сначала выберите или добавьте группу в расписании!", is_urgent=True)
        return

    init_subj_id = None
    init_dow = str(datetime.date.today().weekday() if datetime.date.today().weekday() < 6 else 0)
    init_weeks = {"1", "2", "3", "4"}
    init_lesson_date = ""
    init_subg = "0"
    init_type = "ЛР"
    init_start = "08:30"
    init_end = "09:55"
    init_room = ""
    init_teacher = ""
    init_note = ""

    if sched_id is not None:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT subject_id, day_of_week, weeks, lesson_date, subgroup, lesson_type,
                   start_time, end_time, room, teacher, note
            FROM schedule WHERE id = ?
            """,
            (sched_id,),
        )
        row = cur.fetchone()
        conn.close()
        if row:
            init_subj_id = row[0]
            init_dow = str(row[1])
            init_weeks = {x.strip() for x in (row[2] or "1,2,3,4").split(",") if x.strip()}
            init_lesson_date = row[3] or ""
            init_subg = str(row[4])
            init_type = row[5]
            init_start = row[6]
            init_end = row[7]
            init_room = row[8] or ""
            init_teacher = row[9] or ""
            init_note = row[10] or ""

    subjects_list = get_dropdown_subjects_for_schedule(view_grp, include_subj_id=init_subj_id)

    dd_options = [ft.DropdownOption(key=str(s_id), text=s_name) for s_id, s_name in subjects_list]
    dd_options.append(ft.DropdownOption(key=CUSTOM_SUBJ_KEY, text="➕ Добавить свой предмет..."))

    default_dd_val = (
        str(init_subj_id)
        if init_subj_id is not None
        else (str(subjects_list[0][0]) if subjects_list else CUSTOM_SUBJ_KEY)
    )

    subj_dd = ft.Dropdown(
        label="Предмет",
        value=default_dd_val,
        options=dd_options,
    )

    custom_subj_input = ft.TextField(
        label="Название нового предмета",
        capitalization=ft.TextCapitalization.SENTENCES,
        visible=(default_dd_val == CUSTOM_SUBJ_KEY),
        dense=True,
        text_size=13,
    )

    def on_subj_dd_change(e):
        custom_subj_input.visible = subj_dd.value == CUSTOM_SUBJ_KEY
        page.update()

    subj_dd.on_select = on_subj_dd_change

    type_dd = ft.Dropdown(
        label="Тип занятия",
        value=init_type,
        options=[
            ft.DropdownOption(key="ЛР", text="🟢 Лабораторная работа (ЛР)"),
            ft.DropdownOption(key="ПЗ", text="🔵 Практическое занятие (ПЗ)"),
            ft.DropdownOption(key="ЛК", text="🟣 Лекция (ЛК)"),
        ],
    )

    subg_dd = ft.Dropdown(
        label="Подгруппа",
        value=init_subg,
        options=[
            ft.DropdownOption(key="0", text="Обе подгруппы"),
            ft.DropdownOption(key="1", text="1-я подгруппа"),
            ft.DropdownOption(key="2", text="2-я подгруппа"),
        ],
    )

    is_one_time_init = bool(init_lesson_date)
    mode_state = {"one_time": is_one_time_init}

    lesson_date_ui, get_lesson_date, _ = create_date_picker_block(
        page, "Дата разовой пары", "📅", init_lesson_date or datetime.date.today().isoformat()
    )

    dow_dd = ft.Dropdown(
        label="День недели",
        value=init_dow,
        options=[ft.DropdownOption(key=str(idx), text=WEEKDAYS_FULL[idx]) for idx in range(6)],
    )

    weeks_row_ui, get_selected_weeks = create_compact_week_selector(page, init_weeks)

    periodic_box = ft.Column(
        controls=[
            dow_dd,
            ft.Text("Учебные недели:", size=12, weight=ft.FontWeight.BOLD),
            weeks_row_ui,
        ],
        spacing=6,
        visible=not is_one_time_init,
    )
    one_time_box = ft.Container(content=lesson_date_ui, visible=is_one_time_init)

    mode_switch_row = ft.Row(spacing=6)

    def set_schedule_mode(one_time: bool):
        mode_state["one_time"] = one_time
        periodic_box.visible = not one_time
        one_time_box.visible = one_time
        render_mode_buttons()
        page.update()

    def render_mode_buttons():
        is_ot = mode_state["one_time"]
        mode_switch_row.controls = [
            ft.Container(
                expand=1,
                bgcolor="#2563EB" if not is_ot else "#1E293B",
                padding=ft.Padding.symmetric(vertical=7, horizontal=8),
                border_radius=8,
                border=ft.Border.all(1, "#38BDF8" if not is_ot else "#334155"),
                alignment=ft.Alignment.CENTER,
                content=ft.Text("🔄 По неделям", size=12, weight=ft.FontWeight.BOLD if not is_ot else ft.FontWeight.NORMAL, color="white"),
                on_click=lambda e: set_schedule_mode(False),
            ),
            ft.Container(
                expand=1,
                bgcolor="#2563EB" if is_ot else "#1E293B",
                padding=ft.Padding.symmetric(vertical=7, horizontal=8),
                border_radius=8,
                border=ft.Border.all(1, "#38BDF8" if is_ot else "#334155"),
                alignment=ft.Alignment.CENTER,
                content=ft.Text("📅 Конкретный день", size=12, weight=ft.FontWeight.BOLD if is_ot else ft.FontWeight.NORMAL, color="white"),
                on_click=lambda e: set_schedule_mode(True),
            ),
        ]

    render_mode_buttons()

    start_input = ft.TextField(label="Начало", value=init_start, expand=True, dense=True, text_size=13)
    end_input = ft.TextField(label="Конец", value=init_end, expand=True, dense=True, text_size=13)

    def apply_bell_preset(st_val: str, end_val: str):
        start_input.value = st_val
        end_input.value = end_val
        page.update()

    bell_chips = [
        ft.Container(
            bgcolor="#1E293B",
            padding=ft.Padding.symmetric(horizontal=6, vertical=4),
            border_radius=6,
            border=ft.Border.all(1, "#475569"),
            content=ft.Text(f"{st}-{en}", size=10, color=ft.Colors.GREY_300),
            on_click=lambda e, s=st, en_t=en: apply_bell_preset(s, en_t),
        )
        for st, en in BELL_PRESETS
    ]

    room_input = ft.TextField(
        label="Аудитория",
        value=init_room,
        capitalization=ft.TextCapitalization.SENTENCES,
        dense=True,
        text_size=13,
    )
    teacher_input = ft.TextField(
        label="Преподаватель",
        value=init_teacher,
        capitalization=ft.TextCapitalization.SENTENCES,
        dense=True,
        text_size=13,
    )
    note_input = ft.TextField(
        label="Примечание к предмету",
        value=init_note,
        capitalization=ft.TextCapitalization.SENTENCES,
        multiline=True,
        min_lines=1,
        max_lines=3,
        dense=True,
        text_size=13,
    )
    err_text = ft.Text("", color="#EF4444", size=12, visible=False)

    def save_schedule_slot(ev):
        is_ot = mode_state["one_time"]
        if is_ot:
            l_date_val = get_lesson_date()
            if not l_date_val:
                err_text.value = "⚠️ Выберите дату проведения разовой пары!"
                err_text.visible = True
                page.update()
                return
            try:
                dt_obj = datetime.date.fromisoformat(l_date_val)
                dow_val = min(5, dt_obj.weekday())
            except ValueError:
                dow_val = 0
            weeks_str = "1,2,3,4"
        else:
            l_date_val = ""
            selected_weeks = get_selected_weeks()
            if not selected_weeks:
                err_text.value = "⚠️ Выберите хотя бы одну учебную неделю!"
                err_text.visible = True
                page.update()
                return
            dow_val = int(dow_dd.value)
            weeks_str = ",".join(selected_weeks)

        st_t = start_input.value.strip() or "08:30"
        end_t = end_input.value.strip() or "09:55"
        if len(st_t) == 4:
            st_t = "0" + st_t
        if len(end_t) == 4:
            end_t = "0" + end_t

        conn = get_conn()
        cur = conn.cursor()

        if subj_dd.value == CUSTOM_SUBJ_KEY:
            new_s_name = custom_subj_input.value.strip()
            if not new_s_name:
                conn.close()
                err_text.value = "⚠️ Введите название нового предмета!"
                err_text.visible = True
                page.update()
                return

            low_new = new_s_name.casefold()
            cur.execute("SELECT id, is_tracked FROM subjects WHERE group_name = ?", (view_grp,))
            found_id = None
            found_tracked = 0
            for ex_id, ex_tr in cur.fetchall():
                cur.execute("SELECT name FROM subjects WHERE id = ?", (ex_id,))
                nm = cur.fetchone()[0]
                if nm.strip().casefold() == low_new:
                    found_id = ex_id
                    found_tracked = ex_tr
                    break

            should_track_new = (not is_ot) and (type_dd.value == "ЛР") and (low_new not in NON_LAB_SUBJECTS) and (view_grp == main_grp)

            if found_id is not None:
                target_subj_id = found_id
                if should_track_new and found_tracked == 0:
                    cur.execute("UPDATE subjects SET is_tracked = 1 WHERE id = ?", (target_subj_id,))
                    cur.execute("SELECT COUNT(*) FROM labs WHERE subject_id = ?", (target_subj_id,))
                    if cur.fetchone()[0] == 0:
                        for i in range(1, 5):
                            cur.execute("INSERT INTO labs (subject_id, lab_num, status) VALUES (?, ?, 0)", (target_subj_id, i))
                            ensure_base_step_for_lab(cur, cur.lastrowid, 0)
            else:
                cur.execute(
                    "INSERT INTO subjects (group_name, name, is_tracked, from_api) VALUES (?, ?, ?, 0)",
                    (view_grp, new_s_name, 1 if should_track_new else 0),
                )
                target_subj_id = cur.lastrowid
                if should_track_new:
                    for i in range(1, 5):
                        cur.execute("INSERT INTO labs (subject_id, lab_num, status) VALUES (?, ?, 0)", (target_subj_id, i))
                        ensure_base_step_for_lab(cur, cur.lastrowid, 0)
        else:
            target_subj_id = int(subj_dd.value)

        if sched_id is None:
            cur.execute(
                """
                INSERT INTO schedule
                (group_name, subject_id, day_of_week, weeks, lesson_date, subgroup, lesson_type,
                 start_time, end_time, room, teacher, note, is_api_synced)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                """,
                (
                    view_grp,
                    target_subj_id,
                    dow_val,
                    weeks_str,
                    l_date_val,
                    int(subg_dd.value),
                    type_dd.value,
                    st_t,
                    end_t,
                    room_input.value.strip(),
                    teacher_input.value.strip(),
                    note_input.value.strip(),
                ),
            )
        else:
            cur.execute(
                """
                UPDATE schedule
                SET subject_id = ?, day_of_week = ?, weeks = ?, lesson_date = ?, subgroup = ?,
                    lesson_type = ?, start_time = ?, end_time = ?, room = ?, teacher = ?, note = ?,
                    is_api_synced = 0
                WHERE id = ?
                """,
                (
                    target_subj_id,
                    dow_val,
                    weeks_str,
                    l_date_val,
                    int(subg_dd.value),
                    type_dd.value,
                    st_t,
                    end_t,
                    room_input.value.strip(),
                    teacher_input.value.strip(),
                    note_input.value.strip(),
                    sched_id,
                ),
            )

        cleanup_orphan_and_non_lab_subjects(cur)
        conn.commit()
        conn.close()
        page.pop_dialog()
        refresh_ui()

    def perform_delete_schedule_slot(ev):
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT subject_id FROM schedule WHERE id = ?", (sched_id,))
        r_s = cur.fetchone()
        cur.execute("DELETE FROM schedule WHERE id = ?", (sched_id,))
        if r_s:
            s_id_del = r_s[0]
            cur.execute("SELECT COUNT(*) FROM schedule WHERE subject_id = ?", (s_id_del,))
            if cur.fetchone()[0] == 0:
                cur.execute("SELECT from_api FROM subjects WHERE id = ?", (s_id_del,))
                fa_row = cur.fetchone()
                if fa_row and fa_row[0] == 0:
                    cur.execute("DELETE FROM subjects WHERE id = ?", (s_id_del,))
        cleanup_orphan_and_non_lab_subjects(cur)
        conn.commit()
        conn.close()
        page.pop_dialog()
        refresh_ui()

    form_content = make_scrollable_form([
        subj_dd,
        custom_subj_input,
        type_dd,
        subg_dd,
        mode_switch_row,
        periodic_box,
        one_time_box,
        ft.Row([start_input, end_input], spacing=8),
        ft.Row(bell_chips, wrap=True, spacing=4, run_spacing=4),
        room_input,
        teacher_input,
        note_input,
        err_text,
    ], scrollable=True)

    def ask_delete_slot_confirmation(ev):
        dlg.title = make_dialog_header(page, "⚠️ Удалить пару?", color="#EF4444")
        dlg.content = make_scrollable_form([
            ft.Text("Вы действительно хотите удалить эту пару из расписания?", size=13)
        ], scrollable=False)
        dlg.actions = [
            ft.TextButton("Назад", on_click=restore_slot_view),
            ft.FilledButton(
                "Да, удалить",
                on_click=perform_delete_schedule_slot,
                style=ft.ButtonStyle(bgcolor="#EF4444", color="white"),
            ),
        ]
        page.update()

    def restore_slot_view(ev):
        dlg.title = make_dialog_header(page, f"Редактировать пару ({view_grp})")
        dlg.content = form_content
        dlg.actions = default_slot_actions
        page.update()

    if sched_id is not None:
        default_slot_actions = [
            ft.TextButton("Удалить пару", on_click=ask_delete_slot_confirmation, style=ft.ButtonStyle(color=ft.Colors.RED_400)),
            ft.FilledButton("Сохранить", on_click=save_schedule_slot),
        ]
    else:
        default_slot_actions = [
            ft.FilledButton("Сохранить", on_click=save_schedule_slot),
        ]

    dlg = ft.AlertDialog(
        inset_padding=ft.Padding.symmetric(horizontal=14, vertical=16),
        title_padding=ft.Padding.only(left=16, right=8, top=10, bottom=0),
        content_padding=ft.Padding.only(left=16, right=6, top=4, bottom=6),
        title=make_dialog_header(page, f"Редактировать пару ({view_grp})" if sched_id else f"Добавить пару ({view_grp})"),
        content=form_content,
        actions=default_slot_actions,
        actions_alignment=ft.MainAxisAlignment.SPACE_BETWEEN if sched_id is not None else ft.MainAxisAlignment.END,
    )
    page.show_dialog(dlg)


def open_event_dialog(page: ft.Page, refresh_ui, event_id=None):
    view_grp = get_setting("view_group", "")
    if not view_grp:
        return

    init_title = ""
    init_desc = ""
    init_date = datetime.date.today().isoformat()
    init_dow = str(datetime.date.today().weekday() if datetime.date.today().weekday() < 6 else 0)
    init_weeks = {"1", "2", "3", "4"}
    init_start = "08:30"
    init_end = "09:55"
    init_teacher = ""
    init_room = ""
    is_one_time_init = True

    if event_id is not None:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT title, description, event_date, day_of_week, weeks,
                   start_time, end_time, teacher, room
            FROM schedule_events WHERE id = ?
            """,
            (event_id,),
        )
        row = cur.fetchone()
        conn.close()
        if row:
            init_title = row[0] or ""
            init_desc = row[1] or ""
            init_date = row[2] or ""
            is_one_time_init = bool(init_date)
            init_dow = str(row[3] or 0)
            init_weeks = {x.strip() for x in (row[4] or "1,2,3,4").split(",") if x.strip()}
            init_start = row[5] or "08:30"
            init_end = row[6] or "09:55"
            init_teacher = row[7] or ""
            init_room = row[8] or ""

    title_input = ft.TextField(
        label="Название события",
        value=init_title,
        capitalization=ft.TextCapitalization.SENTENCES,
        autofocus=True,
        dense=True,
        text_size=13,
    )
    desc_input = ft.TextField(
        label="Примечание",
        value=init_desc,
        capitalization=ft.TextCapitalization.SENTENCES,
        multiline=True,
        min_lines=1,
        max_lines=3,
        dense=True,
        text_size=13,
    )

    ev_mode_state = {"one_time": is_one_time_init}
    date_ui, get_event_date, _ = create_date_picker_block(
        page, "Дата события", "📅", init_date or datetime.date.today().isoformat()
    )

    dow_dd = ft.Dropdown(
        label="День недели",
        value=init_dow,
        options=[ft.DropdownOption(key=str(idx), text=WEEKDAYS_FULL[idx]) for idx in range(6)],
    )

    ev_weeks_row_ui, get_ev_selected_weeks = create_compact_week_selector(page, init_weeks)

    ev_periodic_box = ft.Column(
        controls=[
            dow_dd,
            ft.Text("Недели повторения:", size=12, weight=ft.FontWeight.BOLD),
            ev_weeks_row_ui,
        ],
        spacing=6,
        visible=not is_one_time_init,
    )
    ev_one_time_box = ft.Container(content=date_ui, visible=is_one_time_init)
    ev_mode_row = ft.Row(spacing=6)

    def set_ev_mode(one_time: bool):
        ev_mode_state["one_time"] = one_time
        ev_periodic_box.visible = not one_time
        ev_one_time_box.visible = one_time
        render_ev_mode_btns()
        page.update()

    def render_ev_mode_btns():
        is_ot = ev_mode_state["one_time"]
        ev_mode_row.controls = [
            ft.Container(
                expand=1,
                bgcolor="#2563EB" if is_ot else "#1E293B",
                padding=ft.Padding.symmetric(vertical=7, horizontal=8),
                border_radius=8,
                border=ft.Border.all(1, "#38BDF8" if is_ot else "#334155"),
                alignment=ft.Alignment.CENTER,
                content=ft.Text("📅 Конкретный день", size=12, weight=ft.FontWeight.BOLD if is_ot else ft.FontWeight.NORMAL, color="white"),
                on_click=lambda e: set_ev_mode(True),
            ),
            ft.Container(
                expand=1,
                bgcolor="#2563EB" if not is_ot else "#1E293B",
                padding=ft.Padding.symmetric(vertical=7, horizontal=8),
                border_radius=8,
                border=ft.Border.all(1, "#38BDF8" if not is_ot else "#334155"),
                alignment=ft.Alignment.CENTER,
                content=ft.Text("🔄 По неделям", size=12, weight=ft.FontWeight.BOLD if not is_ot else ft.FontWeight.NORMAL, color="white"),
                on_click=lambda e: set_ev_mode(False),
            ),
        ]

    render_ev_mode_btns()

    start_input = ft.TextField(label="Начало", value=init_start, expand=True, dense=True, text_size=13)
    end_input = ft.TextField(label="Конец", value=init_end, expand=True, dense=True, text_size=13)

    def apply_bell_preset(st_val: str, end_val: str):
        start_input.value = st_val
        end_input.value = end_val
        page.update()

    bell_chips = [
        ft.Container(
            bgcolor="#1E293B",
            padding=ft.Padding.symmetric(horizontal=6, vertical=4),
            border_radius=6,
            border=ft.Border.all(1, "#475569"),
            content=ft.Text(f"{st}-{en}", size=10, color=ft.Colors.GREY_300),
            on_click=lambda e, s=st, en_t=en: apply_bell_preset(s, en_t),
        )
        for st, en in BELL_PRESETS
    ]

    teacher_input = ft.TextField(
        label="Преподаватель",
        value=init_teacher,
        capitalization=ft.TextCapitalization.SENTENCES,
        dense=True,
        text_size=13,
    )
    room_input = ft.TextField(
        label="Аудитория",
        value=init_room,
        capitalization=ft.TextCapitalization.SENTENCES,
        dense=True,
        text_size=13,
    )
    err_text = ft.Text("", color="#EF4444", size=12, visible=False)

    def save_event(ev):
        t_val = title_input.value.strip()
        if not t_val:
            err_text.value = "⚠️ Введите название события!"
            err_text.visible = True
            page.update()
            return

        if ev_mode_state["one_time"]:
            ev_date = get_event_date()
            if not ev_date:
                err_text.value = "⚠️ Выберите дату события!"
                err_text.visible = True
                page.update()
                return
            try:
                dt_obj = datetime.date.fromisoformat(ev_date)
                dow_val = min(5, dt_obj.weekday())
            except ValueError:
                dow_val = 0
            weeks_str = "1,2,3,4"
        else:
            ev_date = ""
            selected_weeks = get_ev_selected_weeks()
            if not selected_weeks:
                err_text.value = "⚠️ Выберите хотя бы одну неделю!"
                err_text.visible = True
                page.update()
                return
            dow_val = int(dow_dd.value)
            weeks_str = ",".join(selected_weeks)

        st_t = start_input.value.strip() or "08:30"
        end_t = end_input.value.strip() or "09:55"
        if len(st_t) == 4:
            st_t = "0" + st_t
        if len(end_t) == 4:
            end_t = "0" + end_t

        conn = get_conn()
        cur = conn.cursor()
        if event_id is None:
            cur.execute(
                """
                INSERT INTO schedule_events
                (group_name, title, description, event_date, day_of_week, weeks,
                 start_time, end_time, teacher, room, is_api_synced)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                """,
                (
                    view_grp,
                    t_val,
                    desc_input.value.strip(),
                    ev_date,
                    dow_val,
                    weeks_str,
                    st_t,
                    end_t,
                    teacher_input.value.strip(),
                    room_input.value.strip(),
                ),
            )
        else:
            cur.execute(
                """
                UPDATE schedule_events
                SET title = ?, description = ?, event_date = ?, day_of_week = ?, weeks = ?,
                    start_time = ?, end_time = ?, teacher = ?, room = ?, is_api_synced = 0
                WHERE id = ?
                """,
                (
                    t_val,
                    desc_input.value.strip(),
                    ev_date,
                    dow_val,
                    weeks_str,
                    st_t,
                    end_t,
                    teacher_input.value.strip(),
                    room_input.value.strip(),
                    event_id,
                ),
            )
        conn.commit()
        conn.close()
        page.pop_dialog()
        refresh_ui()

    def perform_delete_event(ev):
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("DELETE FROM schedule_events WHERE id = ?", (event_id,))
        conn.commit()
        conn.close()
        page.pop_dialog()
        refresh_ui()

    form_content = make_scrollable_form([
        title_input,
        desc_input,
        ev_mode_row,
        ev_one_time_box,
        ev_periodic_box,
        ft.Row([start_input, end_input], spacing=8),
        ft.Row(bell_chips, wrap=True, spacing=4, run_spacing=4),
        teacher_input,
        room_input,
        err_text,
    ], scrollable=True)

    def ask_delete_event_confirmation(ev):
        dlg.title = make_dialog_header(page, "⚠️ Удалить событие?", color="#EF4444")
        dlg.content = make_scrollable_form([
            ft.Text("Вы действительно хотите удалить это событие из расписания?", size=13)
        ], scrollable=False)
        dlg.actions = [
            ft.TextButton("Назад", on_click=restore_event_view),
            ft.FilledButton(
                "Да, удалить",
                on_click=perform_delete_event,
                style=ft.ButtonStyle(bgcolor="#EF4444", color="white"),
            ),
        ]
        page.update()

    def restore_event_view(ev):
        dlg.title = make_dialog_header(page, f"Редактировать событие ({view_grp})")
        dlg.content = form_content
        dlg.actions = default_ev_actions
        page.update()

    if event_id is not None:
        default_ev_actions = [
            ft.TextButton("Удалить событие", on_click=ask_delete_event_confirmation, style=ft.ButtonStyle(color=ft.Colors.RED_400)),
            ft.FilledButton("Сохранить", on_click=save_event),
        ]
    else:
        default_ev_actions = [
            ft.FilledButton("Сохранить", on_click=save_event),
        ]

    dlg = ft.AlertDialog(
        inset_padding=ft.Padding.symmetric(horizontal=14, vertical=40),
        title_padding=ft.Padding.only(left=16, right=8, top=10, bottom=0),
        content_padding=ft.Padding.only(left=16, right=6, top=4, bottom=6),
        title=make_dialog_header(page, f"Редактировать событие ({view_grp})" if event_id else f"📌 Событие ({view_grp})"),
        content=form_content,
        actions=default_ev_actions,
        actions_alignment=ft.MainAxisAlignment.SPACE_BETWEEN if event_id is not None else ft.MainAxisAlignment.END,
    )
    page.show_dialog(dlg)


def open_my_group_dialog(page: ft.Page, refresh_ui):
    cur_main_grp = get_setting("main_group", "")
    cur_main_sub = get_setting("main_subgroup", "1")

    saved_rows = get_saved_groups()
    group_names = [r[0] for r in saved_rows]
    if cur_main_grp and cur_main_grp not in group_names:
        group_names.insert(0, cur_main_grp)

    main_group_dd = ft.Dropdown(
        label="Моя группа",
        value=cur_main_grp if cur_main_grp else None,
        dense=True,
        options=[ft.DropdownOption(key=g, text=f"Группа {g}") for g in group_names],
    )
    main_sub_dd = ft.Dropdown(
        label="Моя подгруппа",
        value=cur_main_sub,
        dense=True,
        options=[
            ft.DropdownOption(key="1", text="1-я подгруппа"),
            ft.DropdownOption(key="2", text="2-я подгруппа"),
            ft.DropdownOption(key="0", text="Обе подгруппы"),
        ],
    )

    def save_my_data(ev):
        chosen_main_grp = main_group_dd.value or ""
        set_setting("main_group", chosen_main_grp)
        set_setting("main_subgroup", main_sub_dd.value or "1")
        if chosen_main_grp:
            ensure_group_labs_initialized(chosen_main_grp)
        page.pop_dialog()
        refresh_ui()

    dlg = ft.AlertDialog(
        inset_padding=ft.Padding.symmetric(horizontal=16, vertical=20),
        title_padding=ft.Padding.only(left=16, right=8, top=10, bottom=0),
        content_padding=ft.Padding.only(left=16, right=6, top=4, bottom=6),
        title=make_dialog_header(page, "🎓 Моя группа и подгруппа"),
        content=make_scrollable_form([
            ft.Text(
                "От выбранной здесь группы и подгруппы зависит ваша Таблица лаб, очередь дедлайнов и расчёт оставшихся пар ЛР:",
                size=12,
                color=ft.Colors.GREY_300,
            ),
            main_group_dd,
            main_sub_dd,
        ], scrollable=False),
        actions=[ft.FilledButton("Сохранить", on_click=save_my_data)],
        actions_alignment=ft.MainAxisAlignment.END,
    )
    page.show_dialog(dlg)


def open_schedule_settings_dialog(page: ft.Page, refresh_ui, show_toast):
    cur_start = get_setting("semester_start", "2026-09-01")
    cur_end = get_setting("semester_end", "2026-12-26")
    cur_main_grp = get_setting("main_group", "")
    cur_view_grp = get_setting("view_group", cur_main_grp)

    start_ui, get_start_val, _ = create_date_picker_block(page, "Начало 1-й недели", "🏁", cur_start)
    end_ui, get_end_val, _ = create_date_picker_block(page, "Конец семестра", "🎓", cur_end)
    sem_dates_group = ft.Column([start_ui, end_ui], spacing=0, tight=True)

    bg_input = ft.TextField(
        label="URL фонового изображения",
        value=get_setting("bg_image_url", ""),
        hint_text="https://... или оставьте пустым",
        dense=True,
        text_size=12,
    )

    theme_chip_containers = {}
    presets = [
        ("🌌 Космос", "/space.jpg"),
        ("🔮 Абстракция", "/abstract.jpg"),
        ("🚫 Без фона", ""),
    ]

    # Функция мгновенного перемещения синей рамки на нажатую кнопку
    def update_theme_chips_borders(active_url: str):
        for u_val, chip_ctrl in theme_chip_containers.items():
            is_active = (u_val == active_url)
            chip_ctrl.border = ft.Border.all(1.5 if is_active else 1, "#38BDF8" if is_active else "#334155")
        page.update()

    def set_preset_bg(url_val: str):
        bg_input.value = url_val
        update_theme_chips_borders(url_val)

    theme_chips = ft.Row(spacing=6)
    for label, u_val in presets:
        is_init_active = (bg_input.value.strip() == u_val)
        chip = ft.Container(
            expand=1,
            height=34,
            bgcolor="#1E293B",
            border_radius=8,
            border=ft.Border.all(1.5 if is_init_active else 1, "#38BDF8" if is_init_active else "#334155"),
            alignment=ft.Alignment.CENTER,
            content=ft.Text(label, size=11, color="white", no_wrap=True),
            on_click=lambda e, u=u_val: set_preset_bg(u),
        )
        theme_chip_containers[u_val] = chip
        theme_chips.controls.append(chip)

    # Если пользователь вставит ссылку вручную — кнопки снимут выделение
    bg_input.on_change = lambda e: update_theme_chips_borders(bg_input.value.strip())

    
    cur_bg_op = int(get_setting("bg_opacity", "25"))
    cur_card_op = int(get_setting("card_opacity", "75"))

    bg_op_label = ft.Text(f"Яркость фона: {cur_bg_op}%", size=12, color=ft.Colors.GREY_300)
    bg_op_slider = ft.Slider(
        min=0,
        max=100,
        divisions=20,
        value=cur_bg_op,
        on_change=lambda e: (setattr(bg_op_label, "value", f"Яркость фона: {int(e.control.value)}%"), page.update()),
    )

    card_op_label = ft.Text(f"Плотность карточек: {cur_card_op}%", size=12, color=ft.Colors.GREY_300)
    card_op_slider = ft.Slider(
        min=0,
        max=100,
        divisions=20,
        value=cur_card_op,
        on_change=lambda e: (setattr(card_op_label, "value", f"Плотность карточек: {int(e.control.value)}%"), page.update()),
    )

    new_group_input = ft.TextField(
        label="Номер группы",
        keyboard_type=ft.KeyboardType.NUMBER,
        expand=True,
        dense=True,
        text_size=13,
    )
    status_msg = ft.Text("", size=12, color="#4ADE80", visible=False)
    saved_groups_col = ft.Column(spacing=6)

    state = {"view_grp": cur_view_grp}

    def rebuild_groups_ui():
        saved_rows = get_saved_groups()
        group_names = [r[0] for r in saved_rows]

        if state["view_grp"] not in group_names and group_names:
            state["view_grp"] = group_names[0]

        saved_groups_col.controls.clear()
        if not saved_rows:
            saved_groups_col.controls.append(
                ft.Text("Нет сохранённых расписаний групп.", size=12, color=ft.Colors.GREY_400, italic=True)
            )

        for g_name, is_init, upd_at in saved_rows:
            is_viewing = g_name == state["view_grp"]

            def on_select_view_grp(e, gn=g_name):
                state["view_grp"] = gn
                set_setting("view_group", gn)
                rebuild_groups_ui()
                refresh_ui()
                page.update()

            def on_sync_grp(e, gn=g_name):
                status_msg.visible = True
                status_msg.color = "#38BDF8"
                status_msg.value = f"⏳ Обновление расписания {gn}..."
                page.update()
                ok, msg = import_schedule_from_bsuir_api(gn)
                status_msg.color = "#4ADE80" if ok else "#FCA5A5"
                status_msg.value = ("✅ " if ok else "⚠️ ") + msg
                rebuild_groups_ui()
                if ok:
                    refresh_ui()
                page.update()

            def on_delete_grp(e, gn=g_name):
                delete_saved_group_schedule(gn)
                remaining = [x for x in group_names if x != gn]
                if state["view_grp"] == gn:
                    state["view_grp"] = remaining[0] if remaining else ""
                    set_setting("view_group", state["view_grp"])
                if get_setting("main_group", "") == gn:
                    set_setting("main_group", remaining[0] if remaining else "")
                status_msg.visible = True
                status_msg.color = "#FDE047"
                status_msg.value = f"🗑️ Расписание группы {gn} удалено."
                rebuild_groups_ui()
                refresh_ui()
                page.update()

            row_card = ft.Container(
                bgcolor="#2563EB" if is_viewing else "#1E293B",
                padding=ft.Padding.symmetric(horizontal=10, vertical=6),
                border_radius=8,
                border=ft.Border.all(1, "#38BDF8" if is_viewing else "#334155"),
                content=ft.Row(
                    controls=[
                        ft.Container(
                            expand=True,
                            on_click=on_select_view_grp,
                            content=ft.Column(
                                controls=[
                                    ft.Text(
                                        f"Группа {g_name}",
                                        weight=ft.FontWeight.BOLD,
                                        size=13,
                                        color="white",
                                    ),
                                    ft.Text(
                                        f"Обновлено: {format_date_ru(upd_at) if upd_at else 'недавно'}",
                                        size=10,
                                        color=ft.Colors.GREY_300,
                                    ),
                                ],
                                spacing=1,
                            ),
                        ),
                        ft.IconButton(
                            icon=ft.Icons.REFRESH_ROUNDED,
                            icon_size=18,
                            visual_density=ft.VisualDensity.COMPACT,
                            icon_color="white",
                            tooltip=f"Обновить {g_name}",
                            on_click=on_sync_grp,
                        ),
                        ft.IconButton(
                            icon=ft.Icons.DELETE_OUTLINE_ROUNDED,
                            icon_size=18,
                            visual_density=ft.VisualDensity.COMPACT,
                            icon_color="#FCA5A5",
                            tooltip=f"Удалить {g_name}",
                            on_click=on_delete_grp,
                        ),
                    ],
                    spacing=4,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
            )
            saved_groups_col.controls.append(row_card)

    def add_new_group_schedule(ev):
        grp = new_group_input.value.strip()
        if not grp:
            status_msg.visible = True
            status_msg.color = "#FCA5A5"
            status_msg.value = "⚠️ Введите номер группы!"
            page.update()
            return

        status_msg.visible = True
        status_msg.color = "#38BDF8"
        status_msg.value = f"⏳ Поиск группы {grp} в ИИС БГУИР..."
        page.update()

        ok, msg = import_schedule_from_bsuir_api(grp)
        status_msg.color = "#4ADE80" if ok else "#FCA5A5"
        status_msg.value = ("✅ " if ok else "⚠️ ") + msg
        if ok:
            new_group_input.value = ""
            state["view_grp"] = grp
            set_setting("view_group", grp)
            if not get_setting("main_group", ""):
                set_setting("main_group", grp)
            rebuild_groups_ui()
            refresh_ui()
        page.update()

    rebuild_groups_ui()

    def save_settings(ev):
        if get_start_val():
            set_setting("semester_start", get_start_val())
        if get_end_val():
            set_setting("semester_end", get_end_val())
        set_setting("view_group", state["view_grp"] or "")
        set_setting("bg_image_url", bg_input.value.strip())
        set_setting("bg_opacity", str(int(bg_op_slider.value))) 
        set_setting("card_opacity", str(int(card_op_slider.value)))  
        page.pop_dialog()
        refresh_ui()

    dlg = ft.AlertDialog(
        inset_padding=ft.Padding.symmetric(horizontal=12, vertical=14),
        title_padding=ft.Padding.only(left=14, right=8, top=10, bottom=0),
        content_padding=ft.Padding.only(left=14, right=6, top=4, bottom=6),
        title=make_dialog_header(page, "⚙️ Настройки расписания"),
        content=make_scrollable_form([
            ft.Text("1. Сохранённые расписания групп:", weight=ft.FontWeight.BOLD, size=13, color="#38BDF8"),
            ft.Row(
                controls=[
                    new_group_input,
                    ft.FilledButton("➕ Добавить", on_click=add_new_group_schedule),
                ],
                spacing=6,
            ),
            status_msg,
            saved_groups_col,
            ft.Divider(height=6),
            ft.Text("2. Границы семестра:", weight=ft.FontWeight.BOLD, size=13, color="#38BDF8"),
            sem_dates_group,
            ft.Divider(height=6),
            ft.Text("3. Оформление и фон:", weight=ft.FontWeight.BOLD, size=13, color="#38BDF8"),
            theme_chips,
            bg_input,
            ft.Container(height=4),
            bg_op_label,
            bg_op_slider,
            card_op_label,
            card_op_slider,
        ], scrollable=True),
        actions=[ft.FilledButton("Сохранить", on_click=save_settings)],
        actions_alignment=ft.MainAxisAlignment.END,
    )
    page.show_dialog(dlg)


def open_notifications_dialog(page: ft.Page, refresh_ui):
    deadline_alerts, planned_alerts = get_categorized_alerts()
    total_len = len(deadline_alerts) + len(planned_alerts)
    items = []

    if total_len == 0:
        items.append(
            ft.Text(
                "Сейчас нет горящих дедлайнов или плановых сдач на ближайшие дни 🎉",
                size=13,
                color=ft.Colors.GREY_400,
            )
        )
    else:
        if deadline_alerts:
            items.append(
                ft.Text(
                    f"🔥 Горящие дедлайны ({len(deadline_alerts)}):",
                    weight=ft.FontWeight.BOLD,
                    size=13,
                    color="#FCA5A5",
                )
            )
            for a in deadline_alerts:
                items.append(
                    ft.Container(
                        bgcolor="#451A1A",
                        padding=10,
                        border_radius=8,
                        border=ft.Border.all(1, "#EF4444"),
                        content=ft.Text(a["text"], size=12, color="white"),
                        on_click=lambda ev, lid=a["lab_id"], sid=a["subj_id"], sn=a["subj_name"]: (
                            page.pop_dialog(),
                            open_lab_editor(page, refresh_ui, lid, sid, sn),
                        ),
                    )
                )

        if planned_alerts:
            items.append(
                ft.Text(
                    f"ℹ️ Плановые сдачи ({len(planned_alerts)}):",
                    weight=ft.FontWeight.BOLD,
                    size=13,
                    color="#7DD3FC",
                )
            )
            for a in planned_alerts:
                items.append(
                    ft.Container(
                        bgcolor="#0C2D48",
                        padding=10,
                        border_radius=8,
                        border=ft.Border.all(1, "#38BDF8"),
                        content=ft.Text(a["text"], size=12, color="white"),
                        on_click=lambda ev, lid=a["lab_id"], sid=a["subj_id"], sn=a["subj_name"]: (
                            page.pop_dialog(),
                            open_lab_editor(page, refresh_ui, lid, sid, sn),
                        ),
                    )
                )

    dlg = ft.AlertDialog(
        inset_padding=ft.Padding.symmetric(horizontal=14, vertical=16),
        title_padding=ft.Padding.only(left=16, right=8, top=10, bottom=0),
        content_padding=ft.Padding.only(left=16, right=6, top=4, bottom=6),
        title=make_dialog_header(page, f"🔔 Уведомления ({total_len})"),
        content=make_scrollable_form(items, scrollable=(len(items) > 5)),
    )
    page.show_dialog(dlg)


def open_onboarding_dialog(page: ft.Page, refresh_ui, show_toast):
    grp_input = ft.TextField(
        label="Номер вашей группы БГУИР",
        keyboard_type=ft.KeyboardType.NUMBER,
        autofocus=True,
        dense=True,
        text_size=13,
    )
    subg_dd = ft.Dropdown(
        label="Ваша подгруппа",
        value="1",
        dense=True,
        options=[
            ft.DropdownOption(key="1", text="1-я подгруппа"),
            ft.DropdownOption(key="2", text="2-я подгруппа"),
            ft.DropdownOption(key="0", text="Обе подгруппы"),
        ],
    )
    status_txt = ft.Text("", size=12, color="#38BDF8", visible=False)

    def start_setup(ev):
        grp = grp_input.value.strip()
        if not grp:
            status_txt.visible = True
            status_txt.color = "#FCA5A5"
            status_txt.value = "⚠️ Введите номер своей учебной группы!"
            page.update()
            return

        status_txt.visible = True
        status_txt.color = "#38BDF8"
        status_txt.value = f"⏳ Загружаем расписание и создаём таблицу лаб для {grp}..."
        page.update()

        set_setting("main_group", grp)
        set_setting("view_group", grp)
        set_setting("main_subgroup", subg_dd.value or "1")
        set_setting("view_subgroup", "0")

        ok, msg = import_schedule_from_bsuir_api(grp)
        if not ok:
            status_txt.color = "#FCA5A5"
            status_txt.value = f"⚠️ {msg}"
            page.update()
            return

        set_setting("is_onboarded", "1")
        page.pop_dialog()
        refresh_ui()
        show_toast(f"🎉 Группа {grp} настроена! Таблица лаб и расписание созданы.", is_urgent=False)

    dlg = ft.AlertDialog(
        inset_padding=ft.Padding.symmetric(horizontal=16, vertical=24),
        title_padding=ft.Padding.only(left=16, right=16, top=12, bottom=0),
        content_padding=ft.Padding.only(left=16, right=6, top=4, bottom=6),
        title=make_dialog_header(page, "👋 Добро пожаловать!"),
        content=make_scrollable_form([
            ft.Text(
                "Укажите свою учебную группу и подгруппу. Приложение автоматически загрузит расписание из ИИС БГУИР и сформирует список предметов с лабораторными работами:",
                size=12,
                color=ft.Colors.GREY_300,
            ),
            grp_input,
            subg_dd,
            status_txt,
        ], scrollable=False),
        actions=[ft.FilledButton("Начать работу 🚀", on_click=start_setup)],
        actions_alignment=ft.MainAxisAlignment.END,
    )
    page.show_dialog(dlg)