FROM python:3.11

WORKDIR /app

COPY . /app

RUN pip install --no-cache-dir fastapi[all] redis pydantic passlib bcrypt

EXPOSE 8000

CMD ["uvicorn", "FastAPI_project:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
