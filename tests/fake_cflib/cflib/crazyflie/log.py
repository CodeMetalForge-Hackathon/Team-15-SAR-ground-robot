class Caller:
    def __init__(self):
        self.cbs = []

    def add_callback(self, cb):
        self.cbs.append(cb)

    def call(self, *a):
        for cb in list(self.cbs):
            cb(*a)


class LogConfig:
    def __init__(self, name, period_in_ms):
        self.name, self.period_in_ms = name, period_in_ms
        self.variables = []
        self.data_received_cb = Caller()
        self.cf = None
        self.started = False

    def add_variable(self, name, fetch_as=None):
        self.variables.append(name)

    def start(self):
        self.started = True

    def stop(self):
        self.started = False
