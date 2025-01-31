import requests
import uuid

def get_token(auth_token, scope='GIGACHAT_API_PERS'):
    """
    Получаем access_token у Сбера (GigaChat).
    :param auth_token: Base64-строка авторизации (SBER_AUTH) из переменных окружения
    :param scope: 'GIGACHAT_API_PERS' по умолчанию
    :return: response (requests.Response) — нужно брать .json(), где access_token
    """
    rq_uid = str(uuid.uuid4())
    url = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
    headers = {
        'Content-Type': 'application/x-www-form-urlencoded',
        'Accept': 'application/json',
        'RqUID': rq_uid,
        'Authorization': f'Basic {auth_token}'
    }
    payload = {'scope': scope}

    response = requests.post(url, headers=headers, data=payload)
    return response


def get_chat_completion(auth_token: str, system_prompt: str, user_prompt: str):
    """
    Отправляет запрос к GigaChat, используя 2 сообщения:
      - system: system_prompt (устанавливает контекст)
      - user: user_prompt (текст вопроса/запроса)

    :param auth_token: str — Bearer-токен GigaChat (получаем через get_token)
    :param system_prompt: str — контекст/инструкции
    :param user_prompt: str — сообщение от пользователя
    :return: requests.Response (где .json() содержит обычную структуру "choices")
    """
    url = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"

    payload = {
        "model": "GigaChat",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ],
        "temperature": 1,
        "top_p": 0.1,
        "n": 1,
        "stream": False,
        "max_tokens": 512,
        "repetition_penalty": 1,
        "update_interval": 0
    }
    headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'Authorization': f'Bearer {auth_token}'
    }

    response = requests.post(url, json=payload, headers=headers)
    return response
