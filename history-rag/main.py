from pathlib import Path

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

if __name__ == "__main__":
    init_project()