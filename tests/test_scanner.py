from scanner import UnifiedScannerV8,State
def p(**kw):
 d={"ticker":"TEST","price":1.0,"daily_volume_usd":500000,"float_shares":3000000,"market_cap":20000000,"spread_pct":1,"rvol":5.5,"vol_1m":100000,"price_vector_1m":1.5,"near_breakout":True,"breakout_valid":True,"sec_text":"definitive agreement contract award"};d.update(kw);return d
def test_trigger():
 s=UnifiedScannerV8();r=s.process_tick(p());assert r["trigger_price"]==1.0;assert r["state"] in {State.ENTRY,State.CONFIRMED}
def test_chase():
 s=UnifiedScannerV8();s.process_tick(p());assert s.process_tick(p(price=1.2))["state"]==State.EXTENDED
def test_toxic():
 assert UnifiedScannerV8().process_tick(p(form_type="S-3"))["state"]==State.REJECTED
def test_float():
 assert UnifiedScannerV8().process_tick(p(float_shares=30000000))["state"]==State.REJECTED
