FROM python:3.9-slim

RUN apt-get update && apt-get install -y curl

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN curl -k "https://gu-st.ru/content/Other/doc/russian_trusted_root_ca.cer" -o /tmp/russian_trusted_root_ca.cer \
    && echo "" >> $(python -m certifi) \
    && cat /tmp/russian_trusted_root_ca.cer >> $(python -m certifi)

COPY . .

RUN chmod +x start.sh
CMD ["bash", "./start.sh"]