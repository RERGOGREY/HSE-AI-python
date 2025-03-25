from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel
from typing import Dict, Optional, List
from datetime import datetime, timedelta, timezone
import string
import random
from passlib.hash import bcrypt
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
import asyncpg
import asyncio
import os
import jwt

app = FastAPI()

SECRET_KEY = "your_secret_key"  # Секретный ключ для JWT
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30


db: Dict[str, Dict] = {}  # Временно, для хранения ссылок в памяти, если бд не работает
users: Dict[str, Dict] = {}  # Временно, для хранения пользователей, если бд не работает
expired_links: Dict[str, Dict] = {}

DISABLE_POSTGRES = os.getenv("DISABLE_POSTGRES", "0") == "1"
DISABLE_REDIS = os.getenv("DISABLE_REDIS", "0") == "1"

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://your_user:your_password@localhost/url_shortener")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost")

if DISABLE_REDIS:
    print("Redis отключён")
    redis = None
else:
    try:
        from redis import Redis  
        print("Redis подключён")
        redis = Redis.from_url(REDIS_URL, decode_responses=True)
    except ImportError:
        print("Библиотека 'redis' не установлена. Установите её с помощью 'pip install redis'.")
        redis = None
    except Exception as e:
        print(f"Ошибка при подключении к Redis: {e}")
        redis = None


def generate_short_code(length: int = 6) -> str:
    characters = string.ascii_letters + string.digits
    return ''.join(random.choices(characters, k=length))


async def cache_link(short_code: str, original_url: str):
    if redis:
        try:
            await redis.set(short_code, original_url, ex=3600)  # Кешируем на 1 час
        except Exception as e:
            print(f"Ошибка при сохранении кеша в Redis: {e}")


async def get_cached_link(short_code: str):
    if redis:
        try:
            return await redis.get(short_code)
        except Exception as e:
            print(f"Ошибка при получении кеша из Redis: {e}")
    return None


async def delete_cache(short_code: str):
    if redis:
        try:
            await redis.delete(short_code)
        except Exception as e:
            print(f"Ошибка при удалении кеша из Redis: {e}")

class URLCreate(BaseModel):
    original_url: str
    custom_alias: Optional[str] = None
    expires_at: Optional[datetime] = None


def check_link_expiration():
    now = datetime.now(timezone.utc)  
    for code, link in list(db.items()):
        if link['expires_at'] and now > link['expires_at']:
            expired_links[code] = db.pop(code)


@app.post("/links/shorten")
async def create_link(data: URLCreate):
    check_link_expiration()
    short_code = data.custom_alias if data.custom_alias else generate_short_code()

    if short_code in db:
        raise HTTPException(status_code=400, detail="Short code already in use")
    
    if data.expires_at and data.expires_at.tzinfo is None:
        data.expires_at = data.expires_at.replace(tzinfo=timezone.utc)


    db[short_code] = {
        "original_url": data.original_url,
        "created_at": datetime.now(),
        "expires_at": data.expires_at,
        "clicks": 0,
        "last_used": None
    }
    await cache_link(short_code, data.original_url)
    return {"short_code": short_code, "original_url": data.original_url}


@app.get("/links/{short_code}")
async def redirect_link(short_code: str):
    check_link_expiration()
    cached_url = await get_cached_link(short_code)
    if cached_url:
        return {"original_url": cached_url}

    if short_code not in db:
        raise HTTPException(status_code=404, detail="Link not found")

    link = db[short_code]
    if link['expires_at'] and datetime.now(timezone.utc) > link['expires_at']:  
        expired_links[short_code] = db.pop(short_code)
        await delete_cache(short_code)
        raise HTTPException(status_code=404, detail="Link has expired")

    link['clicks'] += 1
    link['last_used'] = datetime.now(timezone.utc)  
    await cache_link(short_code, link['original_url'])
    return {"original_url": link['original_url']}


@app.get("/links/{short_code}/stats")
async def link_stats(short_code: str):
    if short_code not in db:
        raise HTTPException(status_code=404, detail="Link not found")

    link = db[short_code]
    return {
        "original_url": link['original_url'],
        "created_at": datetime.now(timezone.utc),
        "expires_at": link['expires_at'],
        "clicks": link['clicks'],
        "last_used": link['last_used']
    }


@app.put("/links/{short_code}")
async def update_link(short_code: str, new_url: str):
    if short_code not in db:
        raise HTTPException(status_code=404, detail="Link not found")

    db[short_code]['original_url'] = new_url
    await cache_link(short_code, new_url)
    return {"detail": "Link updated successfully"}


@app.delete("/links/{short_code}")
async def delete_link(short_code: str):
    if short_code not in db:
        raise HTTPException(status_code=404, detail="Link not found")

    del db[short_code]
    await delete_cache(short_code)
    return {"detail": "Link deleted successfully"}


@app.get("/links/search")
async def search_link(original_url: str):
    for code, link in db.items():
        if link['original_url'] == original_url:
            return {"short_code": code}
    raise HTTPException(status_code=404, detail="Link not found")
