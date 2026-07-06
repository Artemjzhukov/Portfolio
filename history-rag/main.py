import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))
    
from core.chains import create_history_assistant

def main():
    print("=== Analysis of Historical Materials ===")
    
    try:
        # Try to create the assistant, which will connect to Qdrant and Ollama
        assistant = create_history_assistant()
        
        print("\nSystem initialized.")
        print("Caution: on another machine it may not work.")
        print("Code must be adjusted for different environments.\n")
        
        # Example of how we will make requests to our bot/assistant:
        query = "Какие тесты у меня есть по Александру II?"
        print(f"Send '{query}' to Llama")
        result = assistant.invoke(query)
        print("----------Answer Llama------")
        print(result)
        print("---------------------")
        
    except Exception as e:
        print(f"\n Error during startup: {e}")
        print("If the error is related to 'Connection refused' to Qdrant/Ollama — this is normal for Dell!")

if __name__ == "__main__":
    main()