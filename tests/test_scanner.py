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

def test_jagx_extreme_microfloat_override_alerts_at_2_to_5_percent():
 s=UnifiedScannerV8()
 r=s.process_tick(p(
  ticker="JAGX",price=.11,daily_volume_usd=50_000,cumulative_volume=2_132_000,
  float_shares=520_088,post_split_shares=520_088,reverse_split_sessions=4,
  day_change_pct=2.8,rvol=4.1,price_vector_1m=.8,price_vector_5m=2.2,
  sec_text="reverse split fda fee waiver"
 ))
 assert r["trigger_price"]==.11
 assert r["first_alert_move_pct"]==2.8
 assert r["structure"]["extreme_microfloat"] is True
 assert r["state"] in {State.PRECURSOR,State.BUILDING,State.ENTRY,State.CONFIRMED}

def test_sub_ten_cent_lane_is_scanned():
 r=UnifiedScannerV8().process_tick(p(price=.025,daily_volume_usd=250_000))
 assert r.get("reason")!="PRICE_FILTER"

def test_sub_one_tenth_cent_lane_is_scanned():
 r=UnifiedScannerV8().process_tick(p(price=.0005,daily_volume_usd=250_000))
 assert r.get("reason")!="PRICE_FILTER"

def test_recent_reverse_split_stays_armed_without_entry_signal():
 r=UnifiedScannerV8().process_tick(p(
  price=.20,daily_volume_usd=50_000,float_shares=800_000,post_split_shares=800_000,
  reverse_split_sessions=5,rvol=1,price_vector_1m=0,near_breakout=False,
  breakout_valid=False,sec_text=""
 ))
 assert r["structure"]["armed"] is True
 assert r["state"] in {State.ARMED,State.LATENT,State.WATCH,State.PRECURSOR}
