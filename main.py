from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from groq import Groq
from pymongo import MongoClient
from passlib.context import CryptContext
from jose import jwt

import os
from dotenv import load_dotenv
from datetime import datetime, timedelta

# =========================
# ENV
# =========================
load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")
SECRET_KEY = os.getenv("SECRET_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

if not MONGO_URI or not SECRET_KEY or not GROQ_API_KEY:
    raise Exception("❌ Missing ENV variables")

# =========================
# INIT CLIENT
# =========================
client = Groq(api_key=GROQ_API_KEY)

# =========================
# DB
# =========================
mongo_client = MongoClient(MONGO_URI)
db = mongo_client["marketing_db"]
users_col = db["users"]
history_col = db["history"]

# =========================
# PASSWORD
# =========================
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(password):
    return pwd_context.hash(password[:72])

def verify_password(password, hashed):
    return pwd_context.verify(password[:72], hashed)

# =========================
# JWT
# =========================
security = HTTPBearer()

def create_token(data: dict):
    expire = datetime.utcnow() + timedelta(hours=24)
    data.update({"exp": expire})
    return jwt.encode(data, SECRET_KEY, algorithm="HS256")

def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=["HS256"])
        return payload["username"]
    except:
        raise HTTPException(status_code=401, detail="Invalid token")

# =========================
# APP
# =========================
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================
# AI
# =========================
def ai_generate(prompt):
    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}]
        )
        return response.choices[0].message.content
    except:
        return None

# =========================
# AUTH
# =========================
@app.post("/signup")
def signup(data: dict):
    if data["password"] != data["confirm_password"]:
        return {"error": "Passwords do not match"}

    if users_col.find_one({"username": data["username"]}):
        return {"error": "User already exists"}

    users_col.insert_one({
        "username": data["username"],
        "password": hash_password(data["password"])
    })

    return {"message": "Signup successful"}


@app.post("/login")
def login(data: dict):
    user = users_col.find_one({"username": data["username"]})

    if not user:
        return {"error": "User not found"}

    if not verify_password(data["password"], user["password"]):
        return {"error": "Invalid password"}

    token = create_token({"username": data["username"]})
    return {"token": token}

# =========================
# GENERATE
# =========================
@app.post("/generate")
def generate(data: dict, username: str = Depends(verify_token)):

    product = data.get("product")
    audience = data.get("audience")
    platform = data.get("platform")

    if not product or not audience:
        return {"error": "Missing input"}

    prompt = f"""
Create marketing plan

Product: {product}
Audience: {audience}
Platform: {platform}

1. Strategy
2. Growth Plan
3. Do's & Don'ts
4. Captions
5. Hashtags
6. CTA
"""

    result = ai_generate(prompt)

    if not result:
        return {"error": "AI failed"}

    history_col.insert_one({
        "username": username,
        "product": product,
        "audience": audience,
        "platform": platform,
        "result": result
    })

    return {"campaign": result}

# =========================
# FRONTEND
# =========================
@app.get("/")
def home():
    return FileResponse("index.html")