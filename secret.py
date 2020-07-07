import os


USER_TOKENS = set(os.environ.get('USER_TOKENS', '').split(':'))


def is_user_token_valid(token):
    return token in USER_TOKENS
