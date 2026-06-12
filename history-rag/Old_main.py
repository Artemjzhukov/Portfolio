from pathlib import Path
from langchain_community.llms import Ollama
from langchain.agents import initialize_agent, Tool
from langchain.chains import LLMMathChain
from dotenv import load_dotenv
import os

load_dotenv()

# new folders
BASE_DIR = Path(__file__).resolve().parent
DB_DIR = BASE_DIR / "history_database"
DATA_DIR = BASE_DIR / "data"

def init_project():
    print("--- Initialise ---")
    
    # Create folders if they don't exist
    DB_DIR.mkdir(exist_ok=True)
    DATA_DIR.mkdir(exist_ok=True)
    
    print(f" Folder for database created here: {DB_DIR}")
    print(f" Files for history should be placed here: {DATA_DIR}")
    print("Architecture is ready for use on any laptop!")

def translate_text(text: str) -> str:
    return f"Translate (заглушка): {text}"

llm = Ollama(model="qwen2:7b")
llm_math = LLMMathChain.from_llm(llm=llm)

tools = [
    Tool(
        name="Calculator",
        func=llm_math.run,
        description="Useful for solving mathematical problems."
    ),
    Tool(
        name="Translator",
        func=translate_text,
        description="Translates text. Input parameter is a string."
    )
]

agent = initialize_agent(
    tools,
    llm,
    agent="zero-shot-react-description",
    verbose=True
)

if __name__ == "__main__":
    init_project()
    response = agent.run("What is 15 multiplied by 23? And translate the answer to English.")
    print(response)