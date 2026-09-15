"""Детерминированный движок проверки стандартных тестов.

Задания бинарные (Correct/Incorrect) с толерантностью к опечаткам.
Полу-баллы здесь не начисляются: "Partially Correct" возникает только
в ЕГЭ-пути (rubric-based оценка).
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Optional, Union

from app.schemas import ExtractedSubmission, OCRSegment, TaskBreakdown, derive_status

_ANSWER_SEPARATORS = re.compile(r"[,;/]")
_NUMERIC_NOISE = re.compile(r"[\"'«»„“”()\[\].!?,:;—–-]")


def normalize_answer(value: str) -> str:
    """Нормализация: нижний регистр, ё->е, пунктуация/кавычки/пробелы."""
    v = value.strip().lower().replace("ё", "е")
    v = _NUMERIC_NOISE.sub(" ", v)
    return re.sub(r"\s+", " ", v).strip()


def _as_number(v: str) -> Optional[float]:
    try:
        return float(v.replace(",", "."))
    except ValueError:
        return None


def answers_match(student: str, correct: str, fuzzy_threshold: float = 0.85) -> bool:
    """Точное совпадение после нормализации; числа; множества; нечёткий запас по опечаткам.

    Сравнение как множества — только если разделители есть в ОБЕИХ строках
    (мультивыбор "1,3,4"). Одна запятая-разделитель десятичных ("3,5")
    уходит в числовой/нечёткий путь.
    """
    s_raw, c_raw = student.strip(), correct.strip()
    if _ANSWER_SEPARATORS.search(s_raw) and _ANSWER_SEPARATORS.search(c_raw):
        s_tokens = {normalize_answer(t) for t in _ANSWER_SEPARATORS.split(s_raw) if t.strip()}
        c_tokens = {normalize_answer(t) for t in _ANSWER_SEPARATORS.split(c_raw) if t.strip()}
        return bool(s_tokens) and s_tokens == c_tokens
    ns, nc = normalize_answer(student), normalize_answer(correct)
    if not ns or not nc:
        return False
    snum, cnum = _as_number(ns), _as_number(nc)
    if snum is not None and cnum is not None:
        return abs(snum - cnum) < 1e-9
    if ns == nc:
        return True
    return SequenceMatcher(None, ns, nc).ratio() >= fuzzy_threshold


def _norm_task_key(key: Union[int, str]) -> Union[int, str]:
    s = str(key).strip()
    return int(s) if s.isdigit() else s


def check_standard_test(
    extracted: ExtractedSubmission,
    answer_key: dict[str, str],
    fuzzy_threshold: float = 0.85,
) -> tuple[list[TaskBreakdown], list[Union[int, str]]]:
    """Сверка сегментов работы с эталонными ключами.

    Returns:
        (breakdowns, unkeyed_numbers) — второе значение: номера задач,
        найденные в работе, но отсутствующие в answer_key (сигнал для проверки).
    """
    segments: dict[Union[int, str], OCRSegment] = {
        seg.task_number: seg for seg in extracted.segments if seg.task_number is not None
    }
    breakdowns: list[TaskBreakdown] = []
    keyed: list[Union[int, str]] = []

    for key, correct in sorted(answer_key.items(), key=lambda kv: _norm_task_key(kv[0])):
        num = _norm_task_key(key)
        keyed.append(num)
        seg = segments.get(num)
        if seg is None:
            breakdowns.append(
                TaskBreakdown(
                    task_number=num, max_points=1, earned_points=0, status="Not Submitted",
                    student_answer="", correct_answer_or_criteria=str(correct),
                    deduction_reason="Ответ не найден в работе",
                )
            )
        elif answers_match(seg.text, correct, fuzzy_threshold):
            breakdowns.append(
                TaskBreakdown(
                    task_number=num, max_points=1, earned_points=1, status="Correct",
                    student_answer=seg.text, correct_answer_or_criteria=str(correct),
                )
            )
        else:
            breakdowns.append(
                TaskBreakdown(
                    task_number=num, max_points=1, earned_points=0, status="Incorrect",
                    student_answer=seg.text, correct_answer_or_criteria=str(correct),
                    deduction_reason=f"Правильный ответ: {correct}. В работе: {seg.text}",
                )
            )

    unkeyed = [n for n in segments if n not in keyed]
    return breakdowns, unkeyed
