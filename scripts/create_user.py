"""Administrator-only interactive account creation; never replaces an account."""
import argparse
import getpass
import sqlite3
from app.auth import configure


def main():
    parser=argparse.ArgumentParser(description='Додати користувача без зміни існуючих акаунтів.')
    parser.add_argument('--username',required=True)
    args=parser.parse_args()
    password=getpass.getpass('Пароль (12–256 символів): ')
    if password!=getpass.getpass('Повторіть пароль: '):
        raise SystemExit('Паролі не збігаються')
    try:configure(args.username,password,create=True)
    except sqlite3.IntegrityError:raise SystemExit('Такий користувач уже існує.') from None
    except ValueError as exc:raise SystemExit(str(exc)) from None
    print('Користувача додано.')


if __name__=='__main__':main()
