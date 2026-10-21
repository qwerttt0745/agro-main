import argparse
import getpass
from app.auth import configure

if __name__=='__main__':
    parser=argparse.ArgumentParser(description='Створити/змінити єдиний сімейний обліковий запис; старі сесії втратять чинність.')
    parser.add_argument('--username',required=True)
    args=parser.parse_args()
    password=getpass.getpass('Пароль (щонайменше 12 символів): ')
    if password!=getpass.getpass('Повторіть пароль: '):raise SystemExit('Паролі не збігаються')
    configure(args.username,password);print('Обліковий запис налаштовано.')
