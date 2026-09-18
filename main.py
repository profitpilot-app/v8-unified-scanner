import asyncio,json,os,time
from contextlib import asynccontextmanager
import websockets
from fastapi import FastAPI
from pydantic import BaseModel
from scanner import UnifiedScannerV8
from events import SubMinuteEventEngine
from audit import AlertAudit

scanner=UnifiedScannerV8();event_engine=SubMinuteEventEngine();audit=AlertAudit();latest={}
def env_value(name,default=None):
 v=os.getenv(name)
 if v is None:return default
 v=v.strip()
 if len(v)>=2 and v[0]==v[-1] and v[0] in ("'",'"'):v=v[1:-1].strip()
 return v or default
feed={"connected":False,"mode":"simulation","last_error":None,"last_event":None,"config":{"enabled":False,"api_key_present":False,"api_secret_present":False,"stream_url_present":False}}

def reference(symbol,price,volume):
 return {"ticker":symbol,"price":price,"daily_volume_usd":price*volume,"float_shares":int(os.getenv("DEFAULT_FLOAT_SHARES","10000000")),"market_cap":0,"spread_pct":0,"rvol":1,"vol_1m":volume,"price_vector_1m":0,"near_breakout":False,"breakout_valid":False,"sec_text":"","form_type":"","timestamp":time.time()}

async def live_feed():
 url=env_value("ALPACA_STREAM_URL","wss://stream.data.alpaca.markets/v2/iex");key=env_value("ALPACA_API_KEY");secret=env_value("ALPACA_API_SECRET");feed["config"].update({"api_key_present":bool(key),"api_secret_present":bool(secret),"stream_url_present":bool(url)})
 if not key or not secret:feed["last_error"]="Missing ALPACA_API_KEY/ALPACA_API_SECRET";return
 delay=2
 while True:
  try:
   async with websockets.connect(url,ping_interval=20,ping_timeout=20) as ws:
    await ws.send(json.dumps({"action":"auth","key":key,"secret":secret}));auth=json.loads(await ws.recv())
    if any(x.get("T")=="error" for x in auth):raise RuntimeError(str(auth))
    await ws.send(json.dumps({"action":"subscribe","bars":["*"],"trades":["*"]}));await ws.recv()
    feed.update({"connected":True,"mode":"live","last_error":None});delay=2
    async for raw in ws:
     for x in json.loads(raw):
      typ=x.get("T");sym=x.get("S")
      if not sym:continue
      if typ=="t":
       ev=event_engine.add_trade(sym,x.get("p",0),x.get("s",0),side=None);feed["last_event"]={"ticker":sym,**ev}
      elif typ=="b":
       p=float(x.get("c",0));v=float(x.get("v",0))
       if p<=0:continue
       t=reference(sym,p,v);r=scanner.process_tick(t,feed["last_event"] if feed.get("last_event",{}).get("ticker")==sym else None);latest[sym]=r;audit.record(r,"live_feed")
  except asyncio.CancelledError:raise
  except Exception as e:
   feed.update({"connected":False,"last_error":f"{type(e).__name__}: {e}"});await asyncio.sleep(delay);delay=min(delay*2,30)

@asynccontextmanager
async def lifespan(app):
 task=None
 enabled=(env_value("LIVE_FEED_ENABLED","false") or "false").lower()=="true";feed["config"]["enabled"]=enabled
 if enabled:task=asyncio.create_task(live_feed())
 yield
 if task:task.cancel()

app=FastAPI(title="V8 Unified Scanner",version="8.0.0",lifespan=lifespan)
class Tick(BaseModel):
 ticker:str;price:float;daily_volume_usd:float=0;float_shares:int=50_000_000;market_cap:float=0;spread_pct:float=0;rvol:float=1;vol_1m:float=0;price_vector_1m:float=0;near_breakout:bool=False;breakout_valid:bool=False;compression_break:bool=False;volatility_pct:float=3;sec_text:str="";form_type:str="";asymmetry_score:int=0;halted:bool=False;timestamp:float|None=None
@app.get("/")
def root():return {"name":"V8 Unified Scanner","version":"8.0.0","feed":feed,"signals":len(latest)}
@app.get("/health")
def health():return {"ok":True,"feed":feed,"symbols":len(scanner.mem)}
@app.post("/tick")
def tick(t:Tick):
 d=t.model_dump();d["timestamp"]=d["timestamp"] or time.time();r=scanner.process_tick(d);latest[t.ticker.upper()]=r;audit.record(r,"manual_tick");return r
@app.get("/signals")
def signals():return sorted(latest.values(),key=lambda x:x.get("score",0),reverse=True)
@app.get("/signal/{ticker}")
def signal(ticker:str):return latest.get(ticker.upper(),{"ticker":ticker.upper(),"state":"UNKNOWN"})

@app.get("/audit/{ticker}")
def audit_history(ticker:str):return {"ticker":ticker.upper(),"alerts":audit.history(ticker)}
@app.post("/audit/mover/{ticker}")
def audit_mover(ticker:str,price:float,gain:float):return audit.audit_mover(ticker,price,gain)
