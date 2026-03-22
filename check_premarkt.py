"""Diagnostic strategy: log every minute bar timestamp to see if pre-market bars fire."""
from ktg.interfaces import Strategy, Event


class PremarketCheck(Strategy):
    __script_name__ = 'premarket_check'

    def __init__(self, **kwargs):
        self.buy_algo = kwargs.get('buy_algo', '10b39bea-8f18-4838-9207-cca44e05794d')
        self.sell_algo = kwargs.get('sell_algo', '8cfeb551-7c2a-4a9a-8888-601324d0fcd2')

    @classmethod
    def on_strategy_start(cls, md, service, account):
        pass

    @classmethod
    def is_symbol_qualified(cls, symbol, md, service, account):
        return False

    @classmethod
    def using_extra_symbols(cls, symbol, md, service, account):
        return False

    def on_start(self, md, order, service, account):
        self.bar_count = 0
        service.clear_event_triggers()
        service.add_event_trigger([md.symbol], [Event.MINUTE_BAR])
        service.info("PremarketCheck started")

    def on_minute_bar(self, event, md, order, service, account, bar):
        self.bar_count += 1
        # Log first 40 bars and last 10 bars
        if self.bar_count <= 40 or self.bar_count > 380:
            ts = service.time_to_string(event.timestamp)
            service.info(
                f"BAR {self.bar_count}: ts={ts} "
                f"O={event.open:.2f} H={event.high:.2f} "
                f"L={event.low:.2f} C={event.close:.2f} V={event.volume}"
            )

    def on_finish(self, md, order, service, account):
        service.info(f"Total bars received: {self.bar_count}")
