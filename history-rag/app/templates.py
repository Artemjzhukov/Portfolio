"""Рендер дашборда ученика: Jinja2 + Tailwind CDN, мобильная вёрстка, только русский."""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.schemas import TASK_STATUS_RU, TOPIC_MASTERY_RU

_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=select_autoescape(["html"]),
)


def render_dashboard(dashboard) -> str:
    """Единственная точка HTML-рендера StudentDashboard."""
    template = _env.get_template("dashboard.html")
    return template.render(
        dashboard=dashboard,
        task_status_ru=TASK_STATUS_RU,
        topic_labels=TOPIC_MASTERY_RU,
    )