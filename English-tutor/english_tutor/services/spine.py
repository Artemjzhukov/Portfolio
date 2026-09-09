SPINE = {
    "A2": [
        "Present Simple vs Present Continuous",
        "Past Simple",
        "Future: going to / will",
        "Articles and Countability (food, shopping)",
        "Comparatives and Superlatives",
        "Modals: can, have to, should",
    ],
    "B1": [
        "Present Perfect vs Past Simple",
        "Present Perfect Continuous",
        "Past Continuous and Narrative",
        "Future and Probability (will/going to, may/might, First Conditional)",
        "Passive Voice (present/past)",
        "Relative Clauses and Giving Opinions",
    ],
    "B2": [
        "Reported Speech",
        "Conditionals 2/3 and wish",
        "Modal Perfects (must have, can't have, should have)",
        "Articles with Abstract Nouns and Quantifiers",
        "Verb Patterns and Phrasal Verbs",
        "Argumentation and Discourse Markers",
    ],
}


def topics(level: str) -> list[str]:
    return list(SPINE[level])
