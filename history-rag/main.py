import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, star(BASE_DIR))
    
from core.chains import create_history_assistant

def main():
    print("=== ЗАПУСК СИСТЕМЫ АНАЛИЗА ИСТОРИЧЕСКИХ МАТЕРИАЛОВ ===")
    
    try:
        # Пытаемся собрать нашего ассистента
        assistant = create_history_assistant()
        
        print("\nСистема готова к тестовому запросу.")
        print("Внимание: На Dell этот запрос выдаст ошибку подключения, так как Mac еще не настроен.")
        print("Но сам код должен инициализироваться без ошибок Python.\n")
        
        # Пример того, как мы будем делать запросы к нашему боту/помощнику:
        # query = "Какие тесты у меня есть по Александру II?"
        # result = assistant({"query": query})
        # print("Ответ:", result["result"])
        
    except Exception as e:
        print(f"\n Ошибка при запуске: {e}")
        print("Если ошибка связана с 'Connection refused' к Qdrant/Ollama — это нормально для Dell!")

if __name__ == "__main__":
    main()