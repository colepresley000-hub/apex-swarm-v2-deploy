from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, EmailStr
import secrets, sqlite3

app = FastAPI()

def init_db():
    conn = sqlite3.connect('apex.db')
    c = conn.cursor()
    c.execute('CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, email TEXT UNIQUE, license_key TEXT, api_key TEXT UNIQUE)')
    conn.commit()
    conn.close()

init_db()

class ActivateRequest(BaseModel):
    email: EmailStr
    license_key: str

@app.get("/")
def root():
    return {"message": "APEX SWARM - Visit /activate to get started"}

@app.get("/activate")
def activate_page():
    html = """<html><body style='background:#0a0e1a;color:white;padding:50px;font-family:Arial'>
    <div style='max-width:400px;margin:0 auto;background:rgba(255,255,255,0.05);padding:40px;border-radius:20px'>
    <h1 style='text-align:center'>Activate</h1>
    <input type='email' id='email' placeholder='Email' style='width:100%;padding:15px;margin:10px 0;background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.1);border-radius:10px;color:white'>
    <input type='text' id='key' placeholder='License' style='width:100%;padding:15px;margin:10px 0;background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.1);border-radius:10px;color:white'>
    <button onclick='act()' style='width:100%;padding:15px;background:#667eea;border:none;border-radius:10px;color:white;font-weight:bold;cursor:pointer'>Activate</button>
    <div id='msg' style='display:none;margin-top:20px;padding:15px;background:rgba(0,255,136,0.1);border-radius:10px;text-align:center'>Success!</div>
    </div>
    <script>
    async function act(){
    const r=await fetch('/api/v1/activate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:document.getElementById('email').value,license_key:document.getElementById('key').value})});
    const d=await r.json();
    if(d.success){localStorage.setItem('apex_api_key',d.api_key);document.getElementById('msg').style.display='block';alert('Activated! API Key: '+d.api_key);}
    }
    </script>
    </body></html>"""
    return HTMLResponse(html)

@app.post("/api/v1/activate")
def activate(request: ActivateRequest):
    conn = sqlite3.connect('apex.db')
    try:
        api_key = f"apex_{secrets.token_urlsafe(32)}"
        c = conn.cursor()
        c.execute("INSERT INTO users (email, license_key, api_key) VALUES (?, ?, ?)", (request.email, request.license_key, api_key))
        conn.commit()
        return {"success": True, "api_key": api_key}
    except:
        return {"success": False}
    finally:
        conn.close()

@app.get("/health")
def health():
    return {"status": "ok"}
