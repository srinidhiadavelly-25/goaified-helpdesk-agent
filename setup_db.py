"""
Stage 4 - Create the PostgreSQL tables and load SYNTHETIC employee data.

    python setup_db.py          # create tables + insert data (safe to re-run)
    python setup_db.py --reset  # drop everything and start fresh
"""
import sys

from src import database as db


def main() -> None:
    reset = "--reset" in sys.argv
    db.init_db(reset=reset)
    print("Database ready." + (" (tables were reset)" if reset else ""))
    print("\nDemo logins (synthetic data):")
    print(f"  {'ID':<7}{'Name':<15}{'Role':<10}PIN")
    for e in db.EMPLOYEES:
        print(f"  {e[0]:<7}{e[1]:<15}{e[6]:<10}{e[11]}")


if __name__ == "__main__":
    main()
