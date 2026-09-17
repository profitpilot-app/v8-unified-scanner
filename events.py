import time
from collections import defaultdict,deque
class SubMinuteEventEngine:
 def __init__(self):self.trades=defaultdict(lambda:deque(maxlen=10000))
 def add_trade(self,symbol,price,size,ts=None,side=None):
  now=float(ts or time.time());q=self.trades[symbol];q.append((now,float(price),float(size),side))
  while q and now-q[0][0]>120:q.popleft()
  def w(sec):return [x for x in q if now-x[0]<=sec]
  def ch(a):return 0 if len(a)<2 or a[0][1]<=0 else (a[-1][1]-a[0][1])/a[0][1]*100
  a,b,c=w(5),w(15),w(60);c5,c15,c60=ch(a),ch(b),ch(c);v5=sum(x[2] for x in a);prior=[x for x in q if 10<now-x[0]<=70];base=(sum(x[2] for x in prior)/12) if prior else v5;burst=v5/base if base else 1
  buy=sum(x[2] for x in b if x[3]=="buy");sell=sum(x[2] for x in b if x[3]=="sell");total=buy+sell;br=buy/total if total else .5;sr=sell/total if total else .5;e=[]
  if c5>=1:e.append("RAPID_INCREASE")
  if c15>=2:e.append("15S_SURGE")
  if c60>=5:e.append("60S_SURGE")
  if burst>=2:e.append("VOLUME_BURST")
  if br>=.65:e.append("BUY_IMBALANCE")
  if c5<=-1.5:e.append("FAST_REVERSAL")
  if c15<=-3:e.append("TOP_REVERSAL")
  if sr>=.65:e.append("SELL_IMBALANCE")
  return {"events":e,"change_5s_pct":c5,"change_15s_pct":c15,"change_60s_pct":c60,"volume_burst_ratio":burst,"buy_ratio":br,"sell_ratio":sr}
