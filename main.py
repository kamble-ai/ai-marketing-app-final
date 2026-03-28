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
# INIT CLIENTS
# =========================
client = Groq(api_key=GROQ_API_KEY)

# =========================
# DB (MongoDB)
# =========================
try:
    mongo_client = MongoClient(MONGO_URI)
    mongo_client.admin.command('ping')

    db = mongo_client["marketing_db"]
    users_col = db["users"]
    history_col = db["history"]

    print("✅ MongoDB Connected")

except Exception as e:
    print("❌ MongoDB Connection Failed:", e)
    raise Exception("Database connection failed")

# =========================
# PASSWORD HASH (FIXED)
# =========================
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(password):
    return pwd_context.hash(password[:72])  # bcrypt safe limit

def verify_password(password, hashed):
    try:
        return pwd_context.verify(password[:72], hashed)
    except Exception as e:
        print("❌ Password verify error:", e)
        return False

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
    except Exception as e:
        print("❌ Token Error:", e)
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
# AI FUNCTION
# =========================
def ai_generate(prompt):
    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}]
        )
        return response.choices[0].message.content
    except Exception as e:
        print("❌ AI Error:", e)
        return "❌ AI Error"

# =========================
# AUTH (FINAL FIXED)
# =========================
@app.post("/signup")
def signup(data: dict):
    try:
        print("📩 Signup Request:", data)

        if data.get("password") != data.get("confirm_password"):
            return {"error": "Passwords do not match"}

        users_col.insert_one({
            "first_name": data.get("first_name"),
            "last_name": data.get("last_name"),
            "gender": data.get("gender"),
            "dob": data.get("dob"),
            "username": data.get("username"),
            "password": hash_password(data.get("password"))
        })

        return {"message": "Account created successfully"}

    except Exception as e:
        print("❌ REAL SIGNUP ERROR:", str(e))

        if "duplicate key" in str(e).lower():
            return {"error": "User already exists"}

        return {"error": str(e)}


@app.post("/login")
def login(data: dict):
    try:
        print("📩 Login Request:", data)

        user = users_col.find_one({"username": data.get("username")})

        if not user:
            return {"error": "User not found"}

        if not verify_password(data.get("password"), user.get("password")):
            return {"error": "Invalid password"}

        token = create_token({"username": data.get("username")})

        return {
            "message": "Login successful",
            "token": token
        }

    except Exception as e:
        print("❌ LOGIN ERROR:", e)
        return {"error": "Login failed"}

# =========================
# AGENTS
# =========================
def build_prompt(platform, product, audience):
    return f"""
Create a HIGH-CONVERTING {platform} marketing plan.

Product: {product}
Audience: {audience}

Give:
1. Strategy
2. Growth Plan
3. Do's & Don'ts
4. 5 Captions
5. Hashtags
6. CTA
"""

def run_agent(platform, product, audience):
    return ai_generate(build_prompt(platform, product, audience))

# =========================
# GENERATE (SECURE)
# =========================
@app.post("/generate")
def generate(data: dict, username: str = Depends(verify_token)):
    try:
        product = data.get("product")
        audience = data.get("audience")
        platform = data.get("platform")

        if platform == "all":
            platforms = [
                "Instagram", "Facebook Ads",
                "Google Ads", "YouTube Shorts", "YouTube Long"
            ]
            result = "\n\n".join([
                run_agent(p, product, audience) for p in platforms
            ])
        else:
            result = run_agent(platform, product, audience)

        history_col.insert_one({
            "username": username,
            "product": product,
            "audience": audience,
            "platform": platform,
            "result": result
        })

        return {"campaign": result}

    except Exception as e:
        print("❌ GENERATE ERROR:", e)
        return {"error": "Generate failed"}

# =========================
# HISTORY (SECURE)
# =========================
@app.get("/history")
def history(username: str = Depends(verify_token)):
    try:
        data = list(history_col.find(
            {"username": username},
            {"_id": 0}
        ))

        return {"history": data}

    except Exception as e:
        print("❌ HISTORY ERROR:", e)
        return {"error": "History failed"}

# =========================
# FRONTEND
# =========================
@app.get("/")
def home():
    return FileResponse("index.html")