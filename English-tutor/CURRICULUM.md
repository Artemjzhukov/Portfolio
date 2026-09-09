# English Tutor Bot — Curriculum (CEFR-Aligned Spine)

> **Stage 2 output (Curriculum Planner)** — per `.clinerules` and `curriculum-planner/SKILL.md`.
> Status: **✅ Approved by owner** («Curriculum approved»). Stage 3 (Development) scheduled to start next session.
> This document is the **content spine** the bot serves (SPEC §5): 6 topics per level (A2, B1, B2), each with a goal in Russian, grammar points, drill vocabulary, a closing voice task, and chat themes. Owner-editable. The LLM generates lesson bodies from this spine at first use and caches them.

## 1. Learner Profile (generalized for the bot's audience)
- Russian-speaking adults, invited by the owner; 2–4 learners at a time.
- Levels A2–B2 after placement (A1 and C1/C2 excluded by design — SPEC §1).
- Main goal: confident everyday conversation; **speaking is the declared pain point**, so the curriculum is voice-first.
- Time: self-paced; rhythm set by bot reminders at 13:00 & 19:00 (~15–20 min per touch).
- Focus skills: speaking + listening first; grammar and vocabulary as support.
- Interests: handled at runtime via free-form theme lessons (SPEC §6), which reuse the level's grammar points.

## 2. Overall Learning Path
**A2 spine (6 topics) → B1 spine (6) → B2 spine (6).**
- Topics are numbered as the *recommended* order (pedagogical dependencies respected), but learners may pick any topic from the menu (SPEC Q11).
- Level promotion: complete ≥5 of 6 topics of the current spine + a short placement mini-test → bot suggests re-leveling → admin confirms.
- Weekly mix target across all levels: **40% speaking drills, 30% lessons, 20% corrected conversation, 10% SRS reviews** — voice-first per SPEC §8–9.

## 3. Level Assessment Map (feeds the placement test, SPEC §4)
| Band | Written MC (of 20) | Voice sample signals |
|---|---|---|
| **A2** | 6–11 | Short present/past sentences; frequent article & verb-form slips; needs simplified prompts |
| **B1** | 12–16 | Connected narrative; tense-choice errors; limited linking words |
| **B2** | 17–20 | Fluent opinion talk; rare structural errors; nuance and hedging attempts |

Suggested level = written-score band, adjusted ±half a level by voice signals; **admin confirms or overrides**. The voice sample is also stored as the learner's pronunciation/fluency baseline (comparison later is manual, not automated — SPEC §8).

## 4. Module A2 — «Фундамент для разговора»
*Goal of the level: learner can handle daily-life situations with simple connected speech.*

### A2-1. Present Simple vs Present Continuous — «Мой день»
- **Цель:** рассказывать о привычках и о том, что происходит прямо сейчас
- **Грамматика:** Present Simple vs Present Continuous; наречия частотности (always/usually/sometimes); предлоги времени
- **Лексика для тренировок:** daily routine, time, work & study
- **Голосовое задание:** «Опиши свой обычный день — 5–6 предложений»
- **Темы для чата:** будни и выходные, работа/учёба

### A2-2. Past Simple — «Вчера и давно»
- **Цель:** рассказать о прошедших событиях простыми фразами
- **Грамматика:** правильные/неправильные глаголы, was/were, указатели времени (yesterday, ago, last week)
- **Лексика для тренировок:** глаголы действия, время, воспоминания
- **Голосовое задание:** «Что ты делал(а) вчера? — 6 предложений»
- **Темы для чата:** прошлые выходные, детство

### A2-3. Будущее — «Что будет завтра?»
- **Цель:** говорить о планах и простых прогнозах
- **Грамматика:** going to / will; want to + infinitive; present continuous для договорённостей
- **Лексика для тренировок:** планы, погода, встречи
- **Голосовое задание:** «Твои планы на выходные»
- **Темы для чата:** планы, small talk о погоде

### A2-4. Еда, покупки и артикли — «В магазине»
- **Цель:** сделать заказ и покупку; описать количества
- **Грамматика:** a/an/the, some/any, much/many, исчисляемое/неисчисляемое
- **Лексика для тренировок:** еда, покупки, цены
- **Голосовое задание:** «Опиши свою корзину покупок или заказ в кафе»
- **Темы для чата:** еда, любимые блюда, магазины

### A2-5. Сравнения — «Город и люди»
- **Цель:** сравнивать и описывать людей и места
- **Грамматика:** сравнительная/превосходная степень, as...as
- **Лексика для тренировок:** прилагательные, город, транспорт
- **Голосовое задание:** «Сравни свой город и город мечты»
- **Темы для чата:** города, путешествия

### A2-6. Модальные глаголы — «Просить и советовать»
- **Цель:** вежливо просить, разрешать, советовать в типовых ситуациях
- **Грамматика:** can/could, have to, should, вежливые просьбы
- **Лексика для тренировок:** travel, directions, вежливость
- **Голосовое задание:** «Попроси о помощи голосом в 3 ситуациях»
- **Темы для чата:** дорожные ситуации, знакомство

## 5. Module B1 — «Связная речь и опыт»
*Goal of the level: learner tells connected stories about experience, plans and processes; holds a casual conversation.*

### B1-1. Present Perfect vs Past Simple — «Опыт и события жизни»
- **Цель:** рассказать о жизненном опыте, отличая результат от факта в прошлом
- **Грамматика:** Present Perfect (ever/never/just/already/yet) vs Past Simple
- **Лексика для тренировок:** life events, достижения, впечатления
- **Голосовое задание:** «Три самых важных события в твоей жизни»
- **Темы для чата:** путешествия, достижения

### B1-2. Present Perfect Continuous — «Как долго?»
- **Цель:** говорить о длительных процессах и их результатах
- **Грамматика:** PPC, for/since, how long questions
- **Лексика для тренировок:** хобби, прогресс в работе/учёбе
- **Голосовое задание:** «Чем ты занимаешься последние месяцы и какие успехи?»
- **Темы для чата:** хобби и прогресс

### B1-3. Past Continuous и повествование — «Истории и происшествия»
- **Цель:** связно рассказывать истории в прошлом
- **Грамматика:** Past Continuous vs Past Simple, when/while, связки (first, then, suddenly)
- **Лексика для тренировок:** происшествия, воспоминания, коннекторы
- **Голосовое задание:** «Забавная или страшная история из жизни»
- **Темы для чата:** воспоминания, истории

### B1-4. Будущее и вероятность — «Планы и прогнозы»
- **Цель:** обсуждать планы, вероятности и простые условия
- **Грамматика:** will / going to / present continuous; may/might/probably; First Conditional
- **Лексика для тренировок:** планы, решения, погода
- **Голосовое задание:** «Твои планы на следующий год»
- **Темы для чата:** планы, прогнозы, решения

### B1-5. Пассивный залог — «Как это сделано»
- **Цель:** описывать процессы и продукты без указания деятеля
- **Грамматика:** Passive (present/past), by/with
- **Лексика для тренировок:** технологии, процессы, еда
- **Голосовое задание:** «Как готовят твоё любимое блюдо?»
- **Темы для чата:** технологии, производство

### B1-6. Relative clauses и мнение — «Описание и оценка»
- **Цель:** описывать людей/вещи с определениями и выражать мнение
- **Грамматика:** who/which/that/whose; язык мнения (I think, in my opinion, seems)
- **Лексика для тренировок:** медиа, фильмы и книги, отношения
- **Голосовое задание:** «Советуй фильм/книгу и объясни почему»
- **Темы для чата:** фильмы, книги, сериалы

## 6. Module B2 — «Нюанс, аргумент, спонтанность»
*Goal of the level: learner argues, speculates, retells, and speaks spontaneously with nuance.*

### B2-1. Reported speech — «Передать чужие слова»
- **Цель:** пересказывать разговоры, вопросы и просьбы
- **Грамматика:** reported statements/questions/commands; reporting verbs (tell/say/ask/suggest)
- **Лексика для тренировок:** работа, новости, слухи
- **Голосовое задание:** «Перескажи недавний разговор с другом/коллегой»
- **Темы для чата:** новости, рабочие ситуации

### B2-2. Conditionals 2/3 и wish — «Гипотезы и сожаления»
- **Цель:** рассуждать о нереальном, сожалеть, фантазировать
- **Грамматика:** Second/Third Conditional, wish/if only, смешанные типы
- **Лексика для тренировок:** жизненные выборы, гипотезы
- **Голосовое задание:** «Что бы ты изменил(а) в своей жизни?»
- **Темы для чата:** «что, если бы…» сценарии

### B2-3. Modal perfects — «Догадки о прошлом»
- **Цель:** строить предположения о прошлом, критиковать мягко
- **Грамматика:** must/can't/might/should have + V3
- **Лексика для тренировок:** загадки, новости, ошибки и извинения
- **Голосовое задание:** «Странная ситуация — что могло произойти?»
- **Темы для чата:** расследования, разбор ошибок

### B2-4. Артикли и абстрактные существительные — «Мир и общество»
- **Цель:** обсуждать абстрактные темы точным языком
- **Грамматика:** артикли с абстрактными/уникальными существительными; кванторы, each/every/all/whole
- **Лексика для тренировок:** экономика, общество, экология
- **Голосовое задание:** «Мини-мнение об экологической/социальной проблеме — 1 минута»
- **Темы для чата:** общество, экология

### B2-5. Verb patterns и фразовые глаголы — «Живая речь»
- **Цель:** звучать естественно; избегать типичных ошибок русскоговорящих
- **Грамматика:** gerund vs infinitive; verb + preposition; частотные фразовые глаголы
- **Лексика для тренировок:** коммуникация, рабочие фразовые глаголы
- **Голосовое задание:** «Опиши конфликт и то, как его решили»
- **Темы для чата:** рабочие истории, договорённости

### B2-6. Аргументация — «Спорить красиво»
- **Цель:** вести мини-дебаты: тезис → аргумент → контраргумент
- **Грамматика:** discourse markers (however, nevertheless), инверсия (rarely/hardly), cleft sentences, hedging
- **Лексика для тренировок:** дебаты, мнение, «политика без политики»
- **Голосовое задание:** «1-минутная речь: за или против»
- **Темы для чата:** дебаты на лёгкие темы

## 7. Weekly Schedule Example
*Учебная неделя при двух напоминаниях в день (13:00 и 19:00), ~15–20 минут на касание:*

| День | 13:00 | 19:00 |
|---|---|---|
| Пн | SRS-повторение (5–8 слов) + урок: объяснение | `/drill` — голосовое задание урока |
| Вт | Урок: упражнения 1–2 | Чат с ботом (тема из урока) |
| Ср | SRS-повторение + урок: упражнения 3–4 | `/drill` — свободный рассказ голосом |
| Чт | Урок: голосовое задание, завершение урока | Чат с ботом |
| Пт | SRS-повторение + новый урок: объяснение | Упражнения нового урока |
| Сб | Урок по выбранной теме (free-form) | Чат/дебаты на любимую тему |
| Вс | Только SRS (лёгкий день) | Свободный чат, без заданий |

**Норма недели:** 3–4 урока · ≥2 голосовых задания · SRS ежедневно · ≥1 диалог с ботом.

## 8. Progress Tracking Recommendations
- **Per learner:** % completed topics of the spine · SRS retention (correct ÷ due) · voice tasks per week · top recurring errors (from the `corrections` store).
- **Weekly bot summary to admin** via `/stats <id>`: streak, lessons done, weak grammar points, words to repeat.
- **Level reassessment:** when ≥5/6 topics of the current spine are done → short mini-test (5 MC + 1 voice) → bot suggests promotion → admin confirms (mirrors SPEC §4).
- **Success criteria for the pilot (2–4 learners, ~2 months):** each learner completes ≥1 full spine module, speaks ≥3×/week by voice, SRS retention ≥70%.

## 9. Resources & Next Steps (types of materials, free)
- Primary material: the bot's own cached lessons, drills and corrections (LLM-generated from this spine).
- Supplementary (learner-initiated, not integrated in v1): graded dialogues and readers for the level; learner podcasts of the «6 Minute English» type; subtitled YouTube channels for learners of English; Anki-compatible export of the SRS deck later.

## 10. Personalization Hooks (how this spine meets SPEC features)
- **Free-form themes (SPEC §6):** any learner theme reuses the grammar points of the learner's level with theme-specific vocabulary; such lessons are cached per student and feed the SRS.
- **SRS (SPEC §10):** vocabulary of completed lessons + words from chat corrections enter the personal deck automatically.
- **Chat suggestions (SPEC §7):** bot proposes 2–3 discussion topics from the vocabulary of recently completed lessons.
- **Drills (SPEC §9):** each topic's «Голосовое задание» and «Темы для чата» are the source of `/drill` prompts.

---

**End of curriculum. Approved.** Next: Stage 3 (Development with Superpowers: brainstorm → plan → TDD → implement → review), starting with Phase 1 MVP (SPEC §15).
