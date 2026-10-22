import calendar
import datetime

import flet as ft
from config import (
    MONTHS_GENITIVE,
    MONTHS_NOMINATIVE,
    WEEKDAYS_SHORT,
    format_date_ru,
    parse_date_safe,
)


def make_badged_icon(icon_data, count: int, badge_bg: str = "#EF4444", icon_color=None):
    """Создаёт иконку с красным/синим бейджем количества уведомлений."""
    base_icon = ft.Icon(icon_data, color=icon_color, size=27)
    if count <= 0:
        return base_icon
    badge_str = str(count) if count < 100 else "..99"
    return ft.Stack(
        controls=[
            ft.Container(content=base_icon, padding=ft.Padding.only(right=8, top=3)),
            ft.Container(
                right=0,
                top=0,
                bgcolor=badge_bg,
                border_radius=10,
                padding=ft.Padding.symmetric(horizontal=5, vertical=1),
                alignment=ft.Alignment.CENTER,
                content=ft.Text(badge_str, size=10, color="white", weight=ft.FontWeight.BOLD),
            ),
        ],
        width=40,
        height=36,
    )


def build_collapsible_alert_box(
    state_dict: dict,
    state_key: str,
    title_text: str,
    alerts_list: list,
    border_color: str,
    bg_color: str,
    accent_color: str,
    icon_data,
    on_toggle_callback,
    on_item_click_callback,
):
    """Сворачиваемый блок уведомлений (аккордеон)."""
    is_expanded = state_dict.get(state_key, False)

    def toggle_expand(e):
        state_dict[state_key] = not state_dict.get(state_key, False)
        on_toggle_callback()

    header_row = ft.Container(
        on_click=toggle_expand,
        border_radius=8,
        padding=ft.Padding.symmetric(horizontal=2, vertical=2),
        content=ft.Row(
            controls=[
                ft.Icon(icon_data, color=accent_color, size=18),
                ft.Text(
                    f"{title_text} ({len(alerts_list)})",
                    weight=ft.FontWeight.BOLD,
                    size=13,
                    color=accent_color,
                    expand=True,
                ),
                ft.Text(
                    "Свернуть" if is_expanded else "Показать",
                    size=11,
                    color=ft.Colors.GREY_300,
                ),
                ft.Icon(
                    ft.Icons.KEYBOARD_ARROW_UP_ROUNDED if is_expanded else ft.Icons.KEYBOARD_ARROW_DOWN_ROUNDED,
                    color=accent_color,
                    size=20,
                ),
            ],
            spacing=6,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
    )

    box_controls = [header_row]

    if is_expanded:
        box_controls.append(ft.Divider(height=6, color=border_color))
        for a in alerts_list:
            item_row = ft.Container(
                padding=ft.Padding.symmetric(horizontal=4, vertical=3),
                border_radius=6,
                tooltip="Нажмите, чтобы открыть лабораторную",
                on_click=lambda ev, alert_obj=a: on_item_click_callback(alert_obj),
                content=ft.Text(f"• {a['text']}", size=12, color="white"),
            )
            box_controls.append(item_row)

    return ft.Container(
        bgcolor=bg_color,
        padding=10,
        border_radius=10,
        border=ft.Border.all(1.5, border_color),
        content=ft.Column(box_controls, spacing=4),
    )


def create_date_picker_block(page: ft.Page, title_prefix: str, icon_emoji: str, initial_iso: str):
    """Адаптивный виджет выбора даты (Сетка календаря Пн-Вс + Барабан День/Месяц/Год)."""
    today = datetime.date.today()
    parsed_init = parse_date_safe(initial_iso)
    state = {"date_str": parsed_init.isoformat() if parsed_init else ""}
    init_dt = parsed_init if parsed_init else today

    picker_state = {
        "open": False,
        "mode": "grid",
        "year": init_dt.year,
        "month": init_dt.month,
        "day": init_dt.day,
    }

    label_text = ft.Text(
        f"{icon_emoji} {title_prefix}: {format_date_ru(state['date_str'])}",
        weight=ft.FontWeight.W_600,
        size=12,
        expand=True,
    )
    calendar_container = ft.Container(visible=False)

    def clamp_day(year: int, month: int, day: int) -> int:
        return min(day, calendar.monthrange(year, month)[1])

    def set_date_external(iso_val: str):
        dt = parse_date_safe(iso_val)
        if dt:
            state["date_str"] = dt.isoformat()
            picker_state["year"], picker_state["month"], picker_state["day"] = dt.year, dt.month, dt.day
        else:
            state["date_str"] = ""
        label_text.value = f"{icon_emoji} {title_prefix}: {format_date_ru(state['date_str'])}"

    def apply_picked_date(y: int, m: int, d: int):
        d = clamp_day(y, m, d)
        picker_state["year"], picker_state["month"], picker_state["day"] = y, m, d
        state["date_str"] = datetime.date(y, m, d).isoformat()
        label_text.value = f"{icon_emoji} {title_prefix}: {format_date_ru(state['date_str'])}"
        render_picker()
        page.update()

    def clear_date(e):
        state["date_str"] = ""
        label_text.value = f"{icon_emoji} {title_prefix}: не указано"
        picker_state["open"] = False
        calendar_container.visible = False
        page.update()

    def toggle_open(e):
        picker_state["open"] = not picker_state["open"]
        calendar_container.visible = picker_state["open"]
        if picker_state["open"] and not state["date_str"]:
            apply_picked_date(today.year, today.month, today.day)
        else:
            render_picker()
            page.update()

    def switch_mode(e):
        picker_state["mode"] = "wheel" if picker_state["mode"] == "grid" else "grid"
        render_picker()
        page.update()

    def shift_month(delta: int):
        m = picker_state["month"] + delta
        y = picker_state["year"]
        if m > 12:
            m = 1
            y += 1
        elif m < 1:
            m = 12
            y -= 1
        apply_picked_date(y, m, picker_state["day"])

    def render_picker():
        y, m, d = picker_state["year"], picker_state["month"], picker_state["day"]
        mode_arrow = "▾" if picker_state["mode"] == "wheel" else "▸"

        header = ft.Row(
            controls=[
                ft.Container(
                    expand=True,
                    on_click=switch_mode,
                    padding=ft.Padding.symmetric(vertical=4, horizontal=4),
                    content=ft.Text(
                        f"{mode_arrow} {MONTHS_NOMINATIVE[m]} {y} г.",
                        color=ft.Colors.WHITE,
                        weight=ft.FontWeight.BOLD,
                        size=13,
                    ),
                ),
                ft.Row(
                    controls=[
                        ft.IconButton(
                            icon=ft.Icons.KEYBOARD_ARROW_UP_ROUNDED,
                            icon_size=18,
                            visual_density=ft.VisualDensity.COMPACT,
                            on_click=lambda e: shift_month(-1),
                        ),
                        ft.IconButton(
                            icon=ft.Icons.KEYBOARD_ARROW_DOWN_ROUNDED,
                            icon_size=18,
                            visual_density=ft.VisualDensity.COMPACT,
                            on_click=lambda e: shift_month(1),
                        ),
                    ],
                    spacing=0,
                ),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        if picker_state["mode"] == "grid":
            wk_row = ft.Row(
                controls=[
                    ft.Container(
                        width=30,
                        alignment=ft.Alignment.CENTER,
                        content=ft.Text(w, size=11, color=ft.Colors.GREY_400),
                    )
                    for w in WEEKDAYS_SHORT
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                spacing=2,
            )

            cal = calendar.Calendar(firstweekday=0)
            month_weeks = cal.monthdatescalendar(y, m)
            grid_rows = [wk_row]

            for week in month_weeks:
                day_cells = []
                for dt_cell in week:
                    is_cur_month = dt_cell.month == m
                    is_selected = (
                        state["date_str"] == dt_cell.isoformat()
                        or (dt_cell.year == y and dt_cell.month == m and dt_cell.day == d)
                    )
                    is_today = dt_cell == today

                    txt_color = (
                        "#FFFFFF" if is_selected
                        else ("#F8FAFC" if is_cur_month else "#64748B")
                    )
                    bg_color = "#2563EB" if is_selected else None
                    border = ft.Border.all(1, "#3B82F6") if (is_today and not is_selected) else None

                    cell = ft.Container(
                        width=30,
                        height=30,
                        bgcolor=bg_color,
                        border_radius=15,
                        border=border,
                        alignment=ft.Alignment.CENTER,
                        content=ft.Text(str(dt_cell.day), size=11, color=txt_color),
                        on_click=lambda e, cy=dt_cell.year, cm=dt_cell.month, cd=dt_cell.day: apply_picked_date(cy, cm, cd),
                    )
                    day_cells.append(cell)

                grid_rows.append(
                    ft.Row(controls=day_cells, alignment=ft.MainAxisAlignment.SPACE_BETWEEN, spacing=2)
                )
            body = ft.Column(controls=grid_rows, spacing=3)
        else:
            max_days = calendar.monthrange(y, m)[1]

            def step_day(delta: int):
                apply_picked_date(y, m, ((d - 1 + delta) % max_days) + 1)

            def step_month(delta: int):
                apply_picked_date(y, ((m - 1 + delta) % 12) + 1, d)

            def step_year(delta: int):
                new_y = max(today.year - 2, min(today.year + 5, y + delta))
                apply_picked_date(new_y, m, d)

            prev_d = ((d - 2) % max_days) + 1
            next_d = (d % max_days) + 1
            prev_m = ((m - 2) % 12) + 1
            next_m = (m % 12) + 1

            def make_wheel_col(prev_txt, cur_txt, next_txt, on_up, on_down, width):
                return ft.Column(
                    controls=[
                        ft.IconButton(
                            icon=ft.Icons.KEYBOARD_ARROW_UP,
                            icon_size=18,
                            visual_density=ft.VisualDensity.COMPACT,
                            on_click=lambda e: on_up(),
                        ),
                        ft.Text(str(prev_txt), size=11, color=ft.Colors.GREY_500),
                        ft.Container(
                            width=width,
                            height=32,
                            bgcolor="#2563EB",
                            border_radius=6,
                            alignment=ft.Alignment.CENTER,
                            content=ft.Text(str(cur_txt), size=13, weight=ft.FontWeight.BOLD, color="white"),
                        ),
                        ft.Text(str(next_txt), size=11, color=ft.Colors.GREY_500),
                        ft.IconButton(
                            icon=ft.Icons.KEYBOARD_ARROW_DOWN,
                            icon_size=18,
                            visual_density=ft.VisualDensity.COMPACT,
                            on_click=lambda e: on_down(),
                        ),
                    ],
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=1,
                )

            body = ft.Row(
                controls=[
                    make_wheel_col(prev_d, d, next_d, lambda: step_day(-1), lambda: step_day(1), 54),
                    make_wheel_col(MONTHS_GENITIVE[prev_m], MONTHS_GENITIVE[m], MONTHS_GENITIVE[next_m], lambda: step_month(-1), lambda: step_month(1), 98),
                    make_wheel_col(y - 1, y, y + 1, lambda: step_year(-1), lambda: step_year(1), 64),
                ],
                alignment=ft.MainAxisAlignment.SPACE_EVENLY,
            )

        footer = ft.Row(
            controls=[
                ft.TextButton("Сегодня", on_click=lambda e: apply_picked_date(today.year, today.month, today.day)),
                ft.TextButton("Готово", on_click=toggle_open),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        )

        calendar_container.content = ft.Container(
            bgcolor="#1E293B",
            padding=8,
            border_radius=10,
            border=ft.Border.all(1, "#334155"),
            content=ft.Column([header, body, footer], spacing=4),
        )

    control_block = ft.Container(
        content=ft.Column(
            controls=[
                ft.Row(
                    controls=[
                        label_text,
                        ft.Row(
                            controls=[
                                ft.IconButton(
                                    icon=ft.Icons.CALENDAR_MONTH_ROUNDED,
                                    icon_size=18,
                                    padding=4,
                                    visual_density=ft.VisualDensity.COMPACT,
                                    tooltip="Выбрать дату",
                                    on_click=toggle_open,
                                ),
                                ft.IconButton(
                                    icon=ft.Icons.CLEAR_ROUNDED,
                                    icon_size=16,
                                    padding=4,
                                    visual_density=ft.VisualDensity.COMPACT,
                                    tooltip="Сбросить дату",
                                    on_click=clear_date,
                                ),
                            ],
                            spacing=0,
                        ),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                calendar_container,
            ],
            spacing=0,
            tight=True,
        )
    )

    return control_block, lambda: state["date_str"], set_date_external