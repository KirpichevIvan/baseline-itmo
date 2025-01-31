import time
import re
import random
import requests
import json
import os
from dotenv import load_dotenv
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
    """Простой GET, проверка работы сервера."""
    return {"message": "Server is up and running"}


@app.get("/api/request")
async def handle_get_request():
    """Для GET-запросов сообщаем, что есть только POST."""
    return {"detail": "This route only supports POST requests."}


@app.get("/favicon.ico")
async def favicon():
    """Чтобы не было лишних ошибок по /favicon.ico."""
    return Response(status_code=204)


@app.on_event("startup")
async def startup_event():
    """
    При запуске:
      1. Настраиваем logger
      2. Загружаем .env
      3. Получаем GigaChat-токен (giga_token)
    """
    global logger, giga_token
    logger = await setup_logger()

    load_dotenv()

    sber_auth = os.getenv("SBER_AUTH")
    if not sber_auth:
        raise ValueError("Не найдено значение SBER_AUTH в переменных окружения!")

    resp = get_token(sber_auth)
    if resp.status_code == 200:
        data = resp.json()
        giga_token = data["access_token"]
        print("GigaChat token получен:", giga_token)
    else:
        print("Ошибка при получении токена GigaChat:", resp.text)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """
    Мидлварь: логгирование запросов/ответов.
    Если хотите убрать полностью, удалите или закомментируйте.
    """
    start_time = time.time()

    body_bytes = b""
    if request.method in ("POST", "PUT", "PATCH"):
        body_bytes = await request.body()

    await logger.info(
        f"Incoming request: {request.method} {request.url}\n"
        f"Request body: {body_bytes.decode()}"
    )

    response = await call_next(request)
    process_time = time.time() - start_time

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


@app.post("/api/request", response_model=PredictionResponse)
async def predict(body: PredictionRequest):
    """
    Основной метод.
    1) Проверяем, что у нас есть токен GigaChat.
    2) Формируем system_prompt (где просим отдавать JSON).
    3) Вызываем get_chat_completion(...)
    4) Парсим JSON, если модель вернула нестрогий ответ — пытаемся выделить answer.
    5) Возвращаем PredictionResponse (answer, reasoning, sources).
    """
    try:
        await logger.info(f"Processing prediction request with id: {body.id}")

        if not giga_token:
            raise HTTPException(status_code=500, detail="GigaChat токен не инициализирован.")

        final_sources = [
            "https://itmo.ru/ru/",
            "https://abit.itmo.ru/"
        ]

        system_prompt = (
            "Ты — официальный информационный агент Университета ИТМО.\n"
            "Если вопрос содержит варианты (1..N), выбери нужный вариант.\n"
            "Если нет вариантов — answer=null.\n"
            "Ответ ДОЛЖЕН быть в формате JSON, без лишних слов:\n"
            "{\n"
            '  "answer": 2 или null,\n'
            '  "reasoning": "Пояснение..."\n'
            "}\n\n"
        )

        giga_response = get_chat_completion(
            auth_token=giga_token,
            system_prompt=system_prompt,
            user_prompt=body.query
        )
        if giga_response.status_code != 200:
            msg = f"Ошибка от GigaChat: {giga_response.text}"
            await logger.error(msg)
            raise HTTPException(status_code=500, detail=msg)

        data = giga_response.json()
        if not data.get("choices"):
            raise HTTPException(status_code=500, detail="В ответе GigaChat нет поля 'choices'")

        model_text = data["choices"][0]["message"]["content"].strip()

        answer_val = None
        reasoning_val = ""

        try:
            parsed = json.loads(model_text)
            answer_val = parsed.get("answer", None)
            reasoning_val = parsed.get("reasoning", "")
        except json.JSONDecodeError:
            match = re.search(r"\b(\d{1,2})\b", model_text)
            if match:
                answer_val = int(match.group(1))
            else:
                answer_val = None
            reasoning_val = model_text

        if isinstance(answer_val, str) and answer_val.isdigit():
            answer_val = int(answer_val)

        response_obj = PredictionResponse(
            id=body.id,
            answer=answer_val,
            reasoning=reasoning_val,
            sources=final_sources
        )

        await logger.info(f"Successfully processed request {body.id}")
        return response_obj

    except Exception as e:
        err_str = str(e)
        await logger.error(f"Internal error processing request {body.id}: {err_str}")
        raise HTTPException(status_code=500, detail="Internal server error")
