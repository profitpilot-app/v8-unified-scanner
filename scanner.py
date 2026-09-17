import time
from collections import defaultdict,deque
from dataclasses import dataclass,field
from typing import Optional
CFG={"min_price":.10,"max_price":20.0,"min_dv":100000,"max_float":15000000,"max_mc":500000000,"max_spread":5.0,"watch":35,"precursor":55,"confirmed":70,"chase":15.0}
T1=("merger","acquisition","fda approval","exclusive license","definitive agreement","contract award")
T2=("phase 2","clinical","strategic alternatives","compliance regained","patent issued","bylaw change")
TOX=("at-the-market","atm offering","prospectus supplement","chapter 11","notice of delisting","delisting","convertible")
class State:
 DISCOVERED="DISCOVERED";WATCH="WATCH";PRECURSOR="PRECURSOR";ENTRY="ENTRY ZONE";CONFIRMED="CONFIRMED";ACTIVE="ACTIVE";DECAY="MOMENTUM DECAY";REVERSAL="REVERSAL";EXTENDED="EXTENDED / CHASE RISK";REJECTED="REJECTED"
@dataclass
class Memory:
 state:str=State.DISCOVERED;trigger_price:Optional[float]=None;trigger_ts:Optional[float]=None;last_price:Optional[float]=None;high_score:int=0;history:deque=field(default_factory=lambda:deque(maxlen=240))
class UnifiedScannerV8:
 def __init__(self):self.mem=defaultdict(Memory)
 def hard_filter(self,t):
  p=float(t.get("price",0));dv=float(t.get("daily_volume_usd",0));fl=int(t.get("float_shares",50_000_000));mc=float(t.get("market_cap",0));sp=float(t.get("spread_pct",0))
  if not CFG["min_price"]<=p<=CFG["max_price"]:return "PRICE_FILTER"
  if dv<CFG["min_dv"]:return "LIQUIDITY_FILTER"
  if fl>CFG["max_float"]:return "FLOAT_FILTER"
  if mc and mc>CFG["max_mc"]:return "MARKET_CAP_FILTER"
  if sp>CFG["max_spread"]:return "SPREAD_FILTER"
  if t.get("halted"):return "HALTED"
 def score(self,t,event=None):
  text=str(t.get("sec_text","")).lower();form=str(t.get("form_type","")).upper()
  if form in {"S-1","S-3","424B3","424B5"} or any(k in text for k in TOX):return 0,{"risk":"TOXIC"}
  rv=float(t.get("rvol",1));pv=float(t.get("price_vector_1m",0));fl=int(t.get("float_shares",50_000_000))
  c={"volume":25 if rv>=8 else 20 if rv>=5 else 15 if rv>=3 else 9 if rv>=2 else 4 if rv>=1.5 else 0,"velocity":20 if pv>=3 else 17 if pv>=2 else 13 if pv>=1.2 else 8 if pv>=.7 else 3 if pv>0 else 0,"float":15 if fl<=2e6 else 13 if fl<=5e6 else 9 if fl<=1e7 else 5,"breakout":12 if t.get("breakout_valid") else 7 if t.get("near_breakout") else 0,"catalyst":20 if any(k in text for k in T1) else 12 if any(k in text for k in T2) else 0,"event":0,"asymmetry":min(10,max(0,int(t.get("asymmetry_score",0))))}
  if t.get("compression_break"):c["breakout"]=min(15,c["breakout"]+3)
  ev=set((event or {}).get("events",[]))
  if "RAPID_INCREASE" in ev:c["event"]+=7
  if "VOLUME_BURST" in ev:c["event"]+=6
  if "BUY_IMBALANCE" in ev:c["event"]+=4
  if "FAST_REVERSAL" in ev or "TOP_REVERSAL" in ev:c["event"]-=15
  if "SELL_IMBALANCE" in ev:c["event"]-=8
  return max(0,min(100,sum(v for v in c.values() if isinstance(v,(int,float))))),c
 def entry(self,t,m):
  if m.trigger_price is None:return None
  p=float(t["price"]);tr=m.trigger_price;width=max(1.5,min(float(t.get("volatility_pct",3)),6));hi=tr*(1+width/100);ch=tr*1.15;ex=(p-tr)/tr*100
  return {"trigger":tr,"entry_low":tr,"ideal_entry":(tr+hi)/2,"entry_high":hi,"chase_limit":ch,"expansion_pct":ex,"status":"BELOW_TRIGGER" if ex<0 else "ENTRY_ZONE" if p<=hi else "ABOVE_ENTRY" if p<ch else "CHASE_RISK"}
 def process_tick(self,t,event=None):
  sym=str(t.get("ticker","")).upper();m=self.mem[sym];bad=self.hard_filter(t)
  if bad:m.state=State.REJECTED;return {"ticker":sym,"state":m.state,"score":0,"reason":bad}
  score,c=self.score(t,event)
  if score==0 and c.get("risk"):m.state=State.REJECTED;return {"ticker":sym,"state":m.state,"score":0,"reason":c["risk"]}
  independent=sum([c["volume"]>0,c["velocity"]>0,c["breakout"]>0,c["catalyst"]>0,c["event"]>0,c["asymmetry"]>0])
  if m.trigger_price is None and score>=CFG["precursor"] and independent>=2 and (t.get("near_breakout") or t.get("breakout_valid") or c["event"]>0):
   m.trigger_price=float(t["price"]);m.trigger_ts=float(t.get("timestamp",time.time()))
  e=self.entry(t,m);ev=set((event or {}).get("events",[]))
  if m.state in {State.PRECURSOR,State.ENTRY,State.CONFIRMED,State.ACTIVE} and "TOP_REVERSAL" in ev:s=State.REVERSAL
  elif m.state in {State.PRECURSOR,State.ENTRY,State.CONFIRMED,State.ACTIVE} and ({"FAST_REVERSAL","SELL_IMBALANCE"}&ev):s=State.DECAY
  elif e and e["expansion_pct"]>=CFG["chase"]:s=State.EXTENDED
  elif e and e["expansion_pct"]<0:s=State.WATCH
  elif e and e["status"]=="ENTRY_ZONE" and score>=CFG["confirmed"]:s=State.CONFIRMED
  elif e and e["status"]=="ENTRY_ZONE":s=State.ENTRY
  elif e and e["status"]=="ABOVE_ENTRY" and score>=CFG["confirmed"]:s=State.ACTIVE
  elif score>=CFG["precursor"]:s=State.PRECURSOR
  elif score>=CFG["watch"]:s=State.WATCH
  else:s=State.DISCOVERED
  m.state=s;m.high_score=max(m.high_score,score);m.last_price=float(t["price"]);m.history.append({"ts":t.get("timestamp",time.time()),"price":m.last_price,"score":score,"state":s})
  return {"ticker":sym,"state":s,"score":score,"price":m.last_price,"trigger_price":m.trigger_price,"trigger_timestamp":m.trigger_ts,"entry_plan":e,"components":c}
