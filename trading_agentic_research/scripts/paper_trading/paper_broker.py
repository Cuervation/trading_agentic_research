from __future__ import annotations

class PaperBroker:
    def __init__(self, slippage_bps_per_side: float=10.0):
        self.slippage_bps=float(slippage_bps_per_side)
        self.live_broker=False
    def _assert_paper(self, order: dict):
        if order.get('PAPER') is not True: raise ValueError('order missing PAPER=true')
        if self.live_broker: raise ValueError('live broker disabled in paper runner')
    def fill_price(self, side: str, theoretical_price: float) -> float:
        mult=1+(self.slippage_bps/10000.0 if side.upper()=='BUY' else -self.slippage_bps/10000.0)
        return float(theoretical_price)*mult
    def submit(self, order: dict, market: dict) -> tuple[dict, dict|None]:
        self._assert_paper(order)
        if not market or market.get('price') is None:
            order={**order,'status':'REJECTED','reject_reason':'missing_next_open'}; return order,None
        fill_px=self.fill_price(order['side'], float(market['price']))
        order={**order,'status':'FILLED','fill_date':market['date']}
        fill={**order,'theoretical_price':float(market['price']),'simulated_fill_price':fill_px,'realized_slippage_bps':self.slippage_bps,'PAPER':True}
        return order,fill
