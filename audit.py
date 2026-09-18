import sqlite3,time
class AlertAudit:
 def __init__(self,path="v8_audit.db"):
  self.db=sqlite3.connect(path,check_same_thread=False)
  self.db.execute("""CREATE TABLE IF NOT EXISTS alerts(id INTEGER PRIMARY KEY,timestamp REAL,ticker TEXT,state TEXT,score INTEGER,price REAL,trigger REAL,source TEXT,UNIQUE(ticker,state,trigger))""")
  self.db.execute("""CREATE TABLE IF NOT EXISTS mover_audit(id INTEGER PRIMARY KEY,timestamp REAL,ticker TEXT,observed_price REAL,observed_gain REAL,result TEXT,first_alert_ts REAL,first_alert_price REAL)""");self.db.commit()
 def record(self,r,source="scanner"):
  if r.get("state") not in {"PRECURSOR","ENTRY ZONE","CONFIRMED","ACTIVE"}:return
  self.db.execute("INSERT OR IGNORE INTO alerts(timestamp,ticker,state,score,price,trigger,source) VALUES(?,?,?,?,?,?,?)",(time.time(),r["ticker"],r["state"],r.get("score",0),r.get("price",0),r.get("trigger_price"),source));self.db.commit()
 def history(self,ticker):
  cur=self.db.execute("SELECT timestamp,state,score,price,trigger,source FROM alerts WHERE ticker=? ORDER BY timestamp",(ticker.upper(),))
  return [{"timestamp":x[0],"state":x[1],"score":x[2],"price":x[3],"trigger":x[4],"source":x[5]} for x in cur.fetchall()]
 def audit_mover(self,ticker,price,gain):
  h=self.history(ticker);first=h[0] if h else None;result="CAUGHT" if first else "MISSED"
  self.db.execute("INSERT INTO mover_audit(timestamp,ticker,observed_price,observed_gain,result,first_alert_ts,first_alert_price) VALUES(?,?,?,?,?,?,?)",(time.time(),ticker.upper(),price,gain,result,first["timestamp"] if first else None,first["price"] if first else None));self.db.commit()
  return {"ticker":ticker.upper(),"result":result,"first_alert":first,"observed_price":price,"observed_gain":gain}
