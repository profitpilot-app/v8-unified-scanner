import main


def test_unadjusted_corporate_action_does_not_create_false_day_move():
    main.market["JAGX"].update({
        "price": 48.26,
        "volume": 72_263,
        "prev_close": 2.56,
        "prev_volume": 610,
        "bid": 48.20,
        "ask": 48.30,
    })
    tick = main.make_tick("JAGX")
    assert tick["corporate_action_unadjusted"] is True
    assert tick["day_change_pct"] == 0
    assert tick["float_shares"] == 10_000_000
