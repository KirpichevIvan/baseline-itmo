import time
import re
import random
import requests
import os
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import HttpUrl

from schemas.request import PredictionRequest, PredictionResponse
from utils.logger import setup_logger
from utils.gigachat_api import get_token, get_chat_completion

app = FastAPI()
logger = None
giga_token = None


@app.get("/")
async def root():
    """
    Простой GET, возвращает признак, что сервер жив.
    """
    return {"message": "Server is up and running"}


@app.get("/api/request")
async def handle_get_request():
    """
    Разрешаем GET на /api/request, но говорим, что поддерживается только POST.
    """
    return {"detail": "This route only supports POST requests."}


@app.get("/favicon.ico")
async def favicon():
    # Чтобы не сыпать логи 404
    return Response(status_code=204)


@app.on_event("startup")
async def startup_event():
    global logger, giga_token
    logger = await setup_logger()

    # base64 авторизация для Сбера (пример)
    sber_auth = "M2RmMzI0ZjEtMzJjMi00MDcxLThhY2ItM2RiOWFjNmQxOTEyOmJlMzM3ZDEyLTA0N2ItNDU1Yi1iZDJlLTE5YTgxYzA3NTg0Yw=="

    if not sber_auth:
        print("Не найдено SBER_AUTH в переменных окружения!")
        return

    response = get_token(sber_auth)
    if response.status_code == 200:
        data = response.json()
        giga_token = data["access_token"]
        print("GigaChat token получен:", giga_token)
    else:
        print("Ошибка при получении токена GigaChat:", response.text)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """
    Логирование запросов и ответов.
    """
    print(f"Incoming request: {request.method} {request.url}")
    start_time = time.time()

    body = b""
    if request.method in ("POST", "PUT", "PATCH"):
        body = await request.body()
        print(f"Request body: {body.decode()}")
    await logger.info(
        f"Incoming request: {request.method} {request.url}\n"
        f"Request body: {body.decode()}"
    )

    response = await call_next(request)
    process_time = time.time() - start_time

    # Чтобы перехватить тело ответа, нужно «прочитать» response.body_iterator
    response_body = b""
    async for chunk in response.body_iterator:
        response_body += chunk

    await logger.info(
        f"Request completed: {request.method} {request.url}\n"
        f"Status: {response.status_code}\n"
        f"Response body: {response_body.decode()}\n"
        f"Duration: {process_time:.3f}s"
    )

    return Response(
        content=response_body,
        status_code=response.status_code,
        headers=dict(response.headers),
        media_type=response.media_type,
    )


def parse_question(query: str):
    """
    Разделяет вопрос и варианты ответов вида:
    "1. вариант 1", "2. вариант 2" и т.д.
    Возвращает (текст_вопроса, список_найденных_вариантов).
    """
    # Ищем подстроки "\n1. ...", "\n2. ...", и т.д.
    pattern = r'(\d+)\.\s+'
    options = re.findall(pattern, query)
    # options будет списком номеров ("1","2",...) но без текста в данном примере.
    # Если хотим весь текст, можно доработать.

    # Удалим сами варианты из текста вопроса (грубо говоря)
    # или возьмём часть до первого варианта.
    # Тут можно улучшать логику как угодно.
    return query, options


@app.post("/api/request", response_model=PredictionResponse)
async def predict(body: PredictionRequest):
    """
    Обрабатывает входящий вопрос:
      - Пытается выделить варианты ответов (1. 2. 3. ...).
      - Если варианты найдены, выбирает "правильный" случайно.
      - Если вариантов нет, возвращает answer=null.
      - Обращается к GigaChat за рассуждением, кладёт его в reasoning.
      - Возвращает sources (до 3 ссылок).
    """
    try:
        await logger.info(f"Processing prediction request with id: {body.id}")

        if not giga_token:
            raise HTTPException(status_code=500, detail="GigaChat токен не инициализирован.")

        # Парсим варианты ответа из вопроса (если это multiple-choice)
        question_text, options = parse_question(body.query)
        parsed_answer = None
        if len(options) > 0:
            # Выбираем случайный вариант (пример!)
            parsed_answer = random.randint(1, len(options))

        # Теперь уходим в GigaChat, запрашиваем ответ
        giga_response = get_chat_completion(giga_token, body.query)
        if giga_response.status_code != 200:
            # Если ошибка на стороне GigaChat — логируем и выбрасываем 500
            msg = f"Ошибка от GigaChat: {giga_response.text}"
            await logger.error(msg)
            raise HTTPException(status_code=500, detail=msg)

        # Разбираем JSON
        # Предположим, что GigaChat возвращает структуру наподобие OpenAI:
        # {
        #   "id": "...",
        #   "choices": [
        #       {"index":0,"message":{"role":"assistant","content":"..."}}
        #   ]
        #   ...
        # }
        data = giga_response.json()
        if not data.get("choices"):
            # Если почему-то нет поля "choices"
            raise HTTPException(status_code=500, detail="В ответе GigaChat нет поля 'choices'")

        # Допустим, берём текст из первого choice
        giga_text = data["choices"][0]["message"]["content"]

        # Пример источников, как в вашем коде
        sources: List[HttpUrl] = [
            "https://itmo.ru/ru/",
            "https://abit.itmo.ru/"
        ]

        response = PredictionResponse(
            id=body.id,
            answer=parsed_answer,     # Если multiple choice
            reasoning="Модель-GigaChat: " + giga_text,      # Сюда пишем «рассуждение» от GigaChat
            sources=sources
        )

        await logger.info(f"Successfully processed request {body.id}")
        return response

    except ValueError as e:
        error_msg = str(e)
        await logger.error(f"Validation error for request {body.id}: {error_msg}")
        raise HTTPException(status_code=400, detail=error_msg)
    except Exception as e:
        await logger.error(f"Internal error processing request {body.id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")
