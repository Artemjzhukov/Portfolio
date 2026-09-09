from english_tutor.bot import create_bot, create_dispatcher
from english_tutor.config import load_config


CFG = load_config({"BOT_TOKEN": "1:t", "GROQ_API_KEY": "g", "ADMIN_TELEGRAM_ID": "9"})


class L:
    def chat_json(self, system, user):
        return {}

    def transcribe(self, path):
        return "hello"


def test_dispatcher_registers_routers_and_data():
    dp = create_dispatcher(CFG, conn=None, llm=L())
    assert len(dp.sub_routers) >= 3
    assert dp.workflow_data["admin_id"] == 9
    assert "conn" in dp.workflow_data and "llm" in dp.workflow_data


def test_create_bot():
    assert create_bot(CFG).token == "1:t"
